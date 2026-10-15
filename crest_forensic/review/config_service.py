"""Config viewer/editor rules for the review app (Build Plan 11.1 screen 6, 11.2).

Everyone can view the config. Only the forensic lead can change or approve it.
The version-making rules themselves live in crest_forensic/config_store.py.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic import config_store as store
from crest_forensic.db.models import AppUser, ConfigVersion
from crest_forensic.review.service import RuleError, require


def _wrap(fn, *args):
    try:
        return fn(*args)
    except store.ConfigError as exc:
        raise RuleError(str(exc), exc.status)


def _kind(path: str, value) -> str:
    if "severity" in path:
        return "severity"
    return "text" if isinstance(value, str) else "number"


def _label(path: str) -> str:
    rest = path.split(".", 2)[2] if path.count(".") >= 2 else path
    return rest.replace(".", " › ").replace("_", " ")


def _version_row(session: Session, row: ConfigVersion | None, baseline: dict) -> dict:
    parent = session.get(ConfigVersion, row.parent_id) if row and row.parent_id else None
    before = parent.content if parent is not None else baseline
    return {"id": row.id, "version": row.version, "created_by": row.created_by, "note": row.note,
            "created_at": row.created_at.isoformat(), "approved_by": row.approved_by,
            "approved_at": row.approved_at, "changes": store.diff(before, row.content)}


def overview(session: Session) -> dict:
    live = store.live_version(session)
    config = store.active_config(session)
    approval = config.get("approval") or {}
    baseline = store.load_file_config()
    checks = []
    for check_id, body in config["checks"].items():
        settings = [{"path": n["path"] + ".value", "label": _label(n["path"]), "value": n["value"],
                     "source": n["source"], "kind": _kind(n["path"], n["value"])}
                    for n in store.setting_nodes({"checks": {check_id: body}})]
        checks.append({"check_id": check_id, "name": body.get("name"), "metric": body.get("metric"),
                       "rule_id": body.get("rule_id"), "settings": settings,
                       "implemented": body.get("metric") is not None})
    editor_versions = session.execute(select(ConfigVersion).where(ConfigVersion.origin == "editor")
                                      .order_by(ConfigVersion.id.desc())).scalars().all()
    return {
        "live": {"from": "database" if live else "file", "version": config.get("version"),
                 "version_id": live.id if live else None, "approved": bool(approval.get("approved_by")),
                 "approved_by": approval.get("approved_by"), "approved_at": approval.get("approved_at"),
                 "note": live.note if live else None, "created_by": live.created_by if live else None},
        "summary": {"settings": sum(len(c["settings"]) for c in checks),
                    "unconfirmed_proposals": len(store.unconfirmed(config)),
                    "undefined": len(store.undefined(config))},
        "checks": checks,
        "versions": [_version_row(session, v, baseline) for v in editor_versions],
        "sources": {"spec": "a number stated in the CREST job specs",
                    "proposal": "a developer proposal, not yet confirmed by the forensic lead",
                    "needs_lead": "no number exists yet; the check shows the metric and never raises a flag",
                    "lead": "set or confirmed by the forensic lead"},
    }


def edit(session: Session, user: AppUser, changes: list[dict], reason: str) -> dict:
    require(user, "edit_config")
    row = _wrap(store.apply_changes, session, user.username, changes, reason)
    return {"version": row.version, "id": row.id}


def confirm(session: Session, user: AppUser, reason: str) -> dict:
    require(user, "edit_config")
    row = _wrap(store.confirm_proposals, session, user.username, reason)
    return {"version": row.version, "id": row.id}


def approve(session: Session, user: AppUser, reason: str) -> dict:
    require(user, "approve_config")
    row = _wrap(store.approve, session, user.username, reason)
    return {"version": row.version, "id": row.id}
