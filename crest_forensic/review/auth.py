"""Sign-in for the review app: usernames and passwords kept as salted scrypt hashes, and a cookie session.

Design (kept deliberately small; can be swapped for a hosted provider later):
  - Passwords are never stored or logged. Only a salted scrypt hash is saved. The Python standard library does the hashing.
  - A successful login creates a random session token. The browser keeps it in an HttpOnly cookie; the database keeps only its
    SHA-256, so a copy of the database cannot be used to sign in.
  - Sessions expire after SESSION_HOURS and can be revoked (sign out, password change).
  - Too many wrong passwords for one username locks that username for a while (in memory, per process).
  - The same message is returned whether the username or the password was wrong, and for unknown users a dummy hash is checked,
    so a visitor cannot tell which usernames exist.
Only the forensic lead creates users or resets other people's passwords.
Every sign-in (good, wrong, locked), sign-out and account change is written to auth_events (append-only, no passwords or tokens).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import ROLES, AppUser, AuthEvent, AuthSession
from crest_forensic.review.service import RuleError, require

SESSION_HOURS = 12
MIN_PASSWORD = 10
MAX_FAILS, FAIL_WINDOW_SECONDS = 5, 15 * 60
_N, _R, _P = 2 ** 14, 8, 1
_fails: dict[str, list[float]] = {}


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        scheme, n, r, p, salt, digest = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("not-a-real-password")


def check_new_password(password: str, username: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise RuleError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if password.strip().lower() == username.lower():
        raise RuleError("The password cannot be the same as the username.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _clean(text: str | None, limit: int) -> str:
    return "".join(ch for ch in (text or "") if ch.isprintable())[:limit]


def log_event(session: Session, event: str, username: str, actor: str | None = None, ip: str | None = None, detail: str = "") -> None:
    """Add one audit row to the caller's transaction (it is saved when the caller commits)."""
    session.add(AuthEvent(event=event, username=_clean(username, 60), actor=_clean(actor, 60) or None,
                          ip=_clean(ip, 45) or None, detail=_clean(detail, 200)))


def _locked_for(username: str) -> int:
    """Seconds left on a lock, 0 if none."""
    now = time.time()
    recent = [t for t in _fails.get(username, []) if now - t < FAIL_WINDOW_SECONDS]
    _fails[username] = recent
    if len(recent) >= MAX_FAILS:
        return int(FAIL_WINDOW_SECONDS - (now - recent[0])) + 1
    return 0


def _refuse(session: Session, event: str, username: str, ip: str | None, detail: str, message: str, status: int):
    log_event(session, event, username, ip=ip, detail=detail)
    session.commit()          # the caller rolls back on a refusal; the audit row must survive that
    raise RuleError(message, status)


def login(session: Session, username: str, password: str, ip: str | None = None) -> tuple[str, AppUser]:
    username = (username or "").strip().lower()
    wait = _locked_for(username)
    if wait:
        _refuse(session, "login_locked", username, ip, "refused: too many wrong attempts",
                f"Too many wrong attempts. Try again in {max(1, wait // 60)} minute(s).", 429)
    user =session.execute(select(AppUser).where(AppUser.username == username)).scalars().first()
    ok = verify_password(password or "", user.password_hash if user else _DUMMY)
    if user is None or not ok or not user.active:
        _fails.setdefault(username, []).append(time.time())
        why = "unknown user" if user is None else ("account switched off" if not user.active else "wrong password")
        _refuse(session, "login_failed", username, ip, why, "Wrong username or password.", 401)
    _fails.pop(username, None)
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(token_hash=_token_hash(token), username=user.username, expires_at=_now() + dt.timedelta(hours=SESSION_HOURS)))
    log_event(session, "login_ok", user.username, ip=ip)
    session.flush()
    return token, user


def user_for_token(session: Session, token: str | None) -> AppUser | None:
    if not token:
        return None
    row = session.execute(select(AuthSession).where(AuthSession.token_hash == _token_hash(token))).scalars().first()
    if row is None or row.revoked:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=dt.timezone.utc)
    if expires < _now():
        return None
    user = session.execute(select(AppUser).where(AppUser.username == row.username)).scalars().first()
    return user if user is not None and user.active else None


def logout(session: Session, token: str | None) -> None:
    if not token:
        return
    row = session.execute(select(AuthSession).where(AuthSession.token_hash == _token_hash(token))).scalars().first()
    if row is not None:
        row.revoked = True
        log_event(session, "logout", row.username)
        session.flush()


def _revoke_all(session: Session, username: str, keep_token: str | None = None) -> None:
    keep = _token_hash(keep_token) if keep_token else None
    for row in session.execute(select(AuthSession).where(AuthSession.username == username, AuthSession.revoked.is_(False))).scalars():
        if row.token_hash != keep:
            row.revoked = True


def logout_everywhere(session: Session, user: AppUser) -> int:
    """Sign this person out on every device, including this one. Returns how many sessions were ended."""
    rows = session.execute(select(AuthSession).where(AuthSession.username == user.username, AuthSession.revoked.is_(False))).scalars().all()
    for row in rows:
        row.revoked = True
    log_event(session, "logout_all", user.username, detail=f"{len(rows)} session(s) ended")
    session.flush()
    return len(rows)


def active_session_count(session: Session, user: AppUser) -> int:
    now = _now()
    rows = session.execute(select(AuthSession).where(AuthSession.username == user.username, AuthSession.revoked.is_(False))).scalars().all()
    return sum(1 for r in rows if (r.expires_at if r.expires_at.tzinfo else r.expires_at.replace(tzinfo=dt.timezone.utc)) > now)


def change_own_password(session: Session, user: AppUser, current: str, new: str, token: str | None = None) -> None:
    if not verify_password(current or "", user.password_hash):
        raise RuleError("The current password is wrong.", 403)
    check_new_password(new, user.username)
    user.password_hash = hash_password(new)
    user.password_set_at = _now()
    _revoke_all(session, user.username, keep_token=token)     # other devices are signed out
    log_event(session, "password_changed", user.username)
    session.flush()


def set_password_for(session: Session, actor: AppUser, username: str, new: str) -> None:
    """The forensic lead resets someone's password."""
    require(actor, "manage_users")
    user = session.execute(select(AppUser).where(AppUser.username == username)).scalars().first()
    if user is None:
        raise RuleError("User not found.", 404)
    check_new_password(new, user.username)
    user.password_hash = hash_password(new)
    user.password_set_at = _now()
    _revoke_all(session, user.username)
    _fails.pop(user.username, None)
    log_event(session, "password_reset", user.username, actor=actor.username)
    session.flush()


def create_user(session: Session, actor: AppUser, username: str, display_name: str, role: str, password: str) -> AppUser:
    require(actor, "manage_users")
    username = (username or "").strip().lower()
    if not username.replace("_", "").replace(".", "").replace("-", "").isalnum() or len(username) > 60:
        raise RuleError("A username may use letters, digits, dots, dashes and underscores only.")
    if role not in ROLES:
        raise RuleError(f"Role must be one of: {', '.join(ROLES)}.")
    if not (display_name or "").strip():
        raise RuleError("A display name is required.")
    if session.execute(select(AppUser).where(AppUser.username == username)).scalars().first() is not None:
        raise RuleError("That username is already taken.")
    check_new_password(password, username)
    user = AppUser(username=username, display_name=display_name.strip(), role=role, password_hash=hash_password(password),
                   password_set_at=_now())
    session.add(user)
    log_event(session, "user_created", username, actor=actor.username, detail=f"role {role}")
    session.flush()
    return user


def set_active(session: Session, actor: AppUser, username: str, active: bool) -> AppUser:
    require(actor, "manage_users")
    user = session.execute(select(AppUser).where(AppUser.username == username)).scalars().first()
    if user is None:
        raise RuleError("User not found.", 404)
    if user.username == actor.username and not active:
        raise RuleError("You cannot switch off your own account.")
    user.active = active
    if not active:
        _revoke_all(session, user.username)
    log_event(session, "user_switched_on" if active else "user_switched_off", user.username, actor=actor.username)
    session.flush()
    return user


def recent_events(session: Session, actor: AppUser, limit: int = 100) -> list[dict]:
    require(actor, "manage_users")
    rows = session.execute(select(AuthEvent).order_by(AuthEvent.id.desc()).limit(max(1, min(limit, 500)))).scalars()
    return [{"id": e.id, "at": e.created_at.isoformat(), "event": e.event, "username": e.username,
             "actor": e.actor, "ip": e.ip, "detail": e.detail} for e in rows]


def admin_list(session: Session, actor: AppUser) -> list[dict]:
    require(actor, "manage_users")
    return [{"username": u.username, "display_name": u.display_name, "role": u.role, "active": u.active,
             "has_password": bool(u.password_hash), "password_set_at": u.password_set_at.isoformat() if u.password_set_at else None}
            for u in session.execute(select(AppUser).order_by(AppUser.id)).scalars()]
