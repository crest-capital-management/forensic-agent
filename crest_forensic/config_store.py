"""Which check config is live, and how a new version is made (Build Plan 7.4, 11.1 screen 6).

The YAML file is the starting copy. Once the forensic lead saves a change in the
app, every version lives in the database and the newest editor version is the live
config for `run-screen`. Rules enforced here, in code:

- Every change needs a named person and a reason, and makes a NEW version; old versions are never edited.
- Any change clears the approval: an approval belongs to one exact set of values.
- Approval is refused while any limit is still an unconfirmed `proposal`.
- A value the lead sets or confirms gets source "lead".
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import ConfigVersion

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "check_config.yaml"
SEVERITIES = ("high", "medium", "low")
SOURCES = ("spec", "proposal", "needs_lead", "lead")


class ConfigError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def content_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def load_file_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def live_version(session: Session) -> ConfigVersion | None:
    """The newest version made in the editor, or None if the file is still the live config."""
    return session.execute(select(ConfigVersion).where(ConfigVersion.origin == "editor")
                           .order_by(ConfigVersion.id.desc())).scalars().first()


def active_config(session: Session) -> dict:
    """The live config. If the code gained checks after the live version was saved, those checks are added
    from the file as unconfirmed proposals and the approval is cleared: it covers settings the lead has not seen."""
    row = live_version(session)
    if row is None:
        return load_file_config()
    config = copy.deepcopy(row.content)
    newer = [c for c in load_file_config()["checks"] if c not in config["checks"]]
    if newer:
        base = load_file_config()
        for c in newer:
            config["checks"][c] = base["checks"][c]
        config["approval"] = {"approved_by": None, "approved_at": None}
    return config


def setting_nodes(config: dict) -> list[dict]:
    """Every limit or severity rule: a dict under `checks` that holds both `value` and `source`."""
    out: list[dict] = []

    def walk(node, path):
        if isinstance(node, dict):
            if "value" in node and "source" in node:
                out.append({"path": path, "value": node["value"], "source": node["source"]})
            else:
                for k, v in node.items():
                    walk(v, f"{path}.{k}")

    for check_id, body in (config.get("checks") or {}).items():
        walk(body, f"checks.{check_id}")
    return out


def _node(config: dict, path: str) -> dict:
    cur = config
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ConfigError(f"Unknown setting: {path}", 404)
        cur = cur[part]
    if not (isinstance(cur, dict) and "value" in cur and "source" in cur):
        raise ConfigError(f"{path} is not an editable setting.")
    return cur


def validate_value(path: str, old, new):
    """Return the cleaned value, or raise ConfigError. Severity rules take high/medium/low/none;
    text settings take text; every other limit takes a number >= 0 or none."""
    if "severity" in path:
        if new in (None, "", "none"):
            return None
        if new not in SEVERITIES:
            raise ConfigError(f"{path}: severity must be high, medium, low or none.")
        return new
    if isinstance(old, str):
        if not isinstance(new, str) or not new.strip():
            raise ConfigError(f"{path}: a text value is required.")
        return new.strip()
    if new in (None, ""):
        return None
    if isinstance(new, bool) or not isinstance(new, (int, float)):
        raise ConfigError(f"{path}: a number is required.")
    if new < 0:
        raise ConfigError(f"{path}: a limit cannot be negative.")
    return new


def _check_order(config: dict) -> None:
    """For every check with a numeric high and medium limit, high must not be below medium."""
    for check_id, body in (config.get("checks") or {}).items():
        t = (body or {}).get("thresholds") or {}
        hi, med = (t.get("high") or {}).get("value"), (t.get("medium") or {}).get("value")
        if isinstance(hi, (int, float)) and isinstance(med, (int, float)) and hi < med:
            raise ConfigError(f"{check_id}: the high limit ({hi}) cannot be lower than the medium limit ({med}).")


def _check_zones(config: dict) -> None:
    """Altman zones: the stress limit cannot be above the safe limit."""
    z = (((config.get("checks") or {}).get("J1-16") or {}).get("zones") or {})
    safe, low = (z.get("safe_above") or {}).get("value"), (z.get("stress_below") or {}).get("value")
    if isinstance(safe, (int, float)) and isinstance(low, (int, float)) and low > safe:
        raise ConfigError(f"J1-16: the stress limit ({low}) cannot be above the safe limit ({safe}).")


def unconfirmed(config: dict) -> list[str]:
    return [n["path"] for n in setting_nodes(config) if n["source"] == "proposal"]


def undefined(config: dict) -> list[str]:
    return [n["path"] for n in setting_nodes(config) if n["source"] == "needs_lead" and n["value"] is None]


def _new_version(session: Session, config: dict, user: str, note: str, parent: ConfigVersion | None) -> ConfigVersion:
    config["approval"] = {"approved_by": None, "approved_at": None}   # any change clears the approval
    base_version = parent.version if parent is not None else int(config.get("version") or 1)
    config["version"] = base_version + 1
    row = ConfigVersion(version=config["version"], content=config, content_hash=content_hash(config),
                        owner=config.get("owner"), origin="editor", created_by=user, note=note,
                        parent_id=parent.id if parent is not None else None)
    session.add(row)
    session.flush()
    return row


def apply_changes(session: Session, user: str, changes: list[dict], reason: str) -> ConfigVersion:
    """changes: [{"path": "checks.J1-03.thresholds.high.value", "value": 2.5}]. Source becomes "lead"."""
    if not reason.strip():
        raise ConfigError("A reason is required for every change.")
    if not changes:
        raise ConfigError("No changes were given.")
    config = active_config(session)
    parent = live_version(session)
    changed = 0
    for ch in changes:
        path = ch["path"]
        if not path.endswith(".value"):
            raise ConfigError(f"{path}: give the path of a setting's value.")
        node = _node(config, path[: -len(".value")])
        new = validate_value(path, node["value"], ch.get("value"))
        if new == node["value"] and node["source"] in ("lead", "spec"):
            continue
        node["value"], node["source"] = new, ("lead" if new is not None else "needs_lead")
        changed += 1
    if not changed:
        raise ConfigError("Nothing changed: every value is already set to that.")
    _check_order(config)
    _check_zones(config)
    return _new_version(session, config, user, reason.strip(), parent)


def confirm_proposals(session: Session, user: str, reason: str) -> ConfigVersion:
    """The lead accepts every remaining developer proposal exactly as it stands."""
    if not reason.strip():
        raise ConfigError("A reason is required.")
    config = active_config(session)
    todo = unconfirmed(config)
    if not todo:
        raise ConfigError("There are no unconfirmed proposals.")
    for path in todo:
        _node(config, path)["source"] = "lead"
    return _new_version(session, config, user, f"Confirmed {len(todo)} proposals as they stand. {reason.strip()}",
                        live_version(session))


def approve(session: Session, user: str, reason: str) -> ConfigVersion:
    if live_version(session) is None:
        raise ConfigError("There is no edited version to approve. Save or confirm the limits first.")
    config = active_config(session)
    parent = live_version(session)
    left = unconfirmed(config)
    if left:
        raise ConfigError(f"{len(left)} limits are still unconfirmed proposals (for example {left[0]}). "
                          "Change or confirm each before approving.")
    if (config.get("approval") or {}).get("approved_by"):
        raise ConfigError("This version is already approved.")
    config["approval"] = {"approved_by": user, "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    config["version"] = parent.version + 1
    row = ConfigVersion(version=config["version"], content=config, content_hash=content_hash(config),
                        owner=config.get("owner"), approved_by=user, approved_at=config["approval"]["approved_at"],
                        origin="editor", created_by=user, note=f"Approved. {reason.strip()}".strip(),
                        parent_id=parent.id)
    session.add(row)
    session.flush()
    return row


def diff(old: dict | None, new: dict) -> list[dict]:
    before = {n["path"]: n for n in setting_nodes(old)} if old else {}
    out = []
    for n in setting_nodes(new):
        b = before.get(n["path"])
        if b is None or b["value"] != n["value"] or b["source"] != n["source"]:
            out.append({"path": n["path"], "old_value": None if b is None else b["value"],
                        "old_source": None if b is None else b["source"],
                        "new_value": n["value"], "new_source": n["source"]})
    return out
