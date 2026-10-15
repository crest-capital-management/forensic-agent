"""Config guardrail: a run refuses to start on unapproved limits (Build Plan 7.4, 9)."""
from __future__ import annotations


class ConfigNotApproved(Exception):
    pass


def is_approved(config: dict) -> bool:
    approval = config.get("approval") or {}
    return bool(approval.get("approved_by")) and bool(approval.get("approved_at"))


def unapproved_values(config: dict) -> list[str]:
    """Paths of every limit still marked 'proposal' or 'needs_lead'."""
    found: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("source") in ("proposal", "needs_lead"):
                found.append(f"{path} [{node['source']}]")
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))

    walk(config.get("checks", {}), "")
    return found


def ensure_config_runnable(config: dict, allow_draft: bool) -> bool:
    """Returns True if approved. Raises ConfigNotApproved unless allow_draft."""
    if is_approved(config):
        return True
    if not allow_draft:
        raise ConfigNotApproved(
            "The check config has not been approved by the forensic lead "
            "(config/check_config.yaml: approval.approved_by / approved_at are empty). "
            "A run refuses to start on unapproved limits. For development only, "
            "pass --allow-draft-config; every flag will be stamped as a draft."
        )
    return False
