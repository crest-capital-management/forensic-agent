"""Shared types and helpers for the Job 1 checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from crest_forensic.db.models import LineItem, Snapshot
from crest_forensic.ingestion.resolve import AGREE, CONFLICT, DERIVED_ESTIMATE, NO_DATA, load_policy, resolve_value

STATUS_COMPLETED = "COMPLETED"
STATUS_NOT_ENOUGH_DATA = "NOT_ENOUGH_DATA"
STATUS_METRIC_ONLY = "METRIC_ONLY"
STATUS_NEEDS_DEFINITION = "NEEDS_DEFINITION"
STATUS_NEEDS_SOURCE = "NEEDS_SOURCE"

CONF_HIGH, CONF_MEDIUM, CONF_LOW = "high", "medium", "low"


@dataclass(frozen=True)
class Input:
    """One number a check used, traceable to the exact saved row."""

    name: str  # the formula's name for it, e.g. "pat", "receivables_prior"
    standard_field: str
    fy: str
    basis: str
    value: float
    line_item_id: int
    snapshot_id: int
    provider: str
    resolution: str  # SINGLE_SOURCE / AGREE / DERIVED_ESTIMATE
    derived: bool
    snapshot_fetched_at: str
    # Every provider whose value supports this input (two when both sources agree).
    providers: tuple[str, ...] = ()

    def ref(self) -> dict[str, Any]:
        return {
            "name": self.name, "field": self.standard_field, "fy": self.fy, "basis": self.basis,
            "value": self.value, "line_item_id": self.line_item_id, "snapshot_id": self.snapshot_id,
            "provider": self.provider, "providers": list(self.providers or (self.provider,)),
            "resolution": self.resolution, "derived": self.derived,
            "snapshot_fetched_at": self.snapshot_fetched_at,
        }


@dataclass(frozen=True)
class Missing:
    standard_field: str
    fy: str
    reason: str  # NO_DATA or SOURCE_CONFLICT
    detail: str = ""

    def text(self) -> str:
        return f"{self.standard_field}@{self.fy}: {self.reason}{(' ' + self.detail) if self.detail else ''}"


@dataclass
class Skip:
    fy: str
    reason: str
    detail: str = ""


@dataclass
class Observation:
    check_id: str
    fy: str
    metric_name: str
    metric_value: float | None
    severity: str | None  # high / medium / low, or None = metric shown, no flag
    severity_rule_id: str
    formula_id: str
    technique: str
    what_observed: str
    inputs: list[Input]
    thresholds_applied: dict[str, Any]
    materiality: dict[str, Any]
    figures: dict[str, Any]
    # Text checks: the verified passages behind this observation (empty for number checks).
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CheckResult:
    check_id: str
    check_version: int
    status: str
    observations: list[Observation] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class InputStore:
    """Reads check inputs through the source-precedence policy, for ONE basis."""

    def __init__(self, session: Session, company_id: int, basis: str, policy: dict | None = None) -> None:
        self.session, self.company_id, self.basis = session, company_id, basis
        self.policy = policy or load_policy()
        self._cache: dict[tuple[str, str], Input | Missing] = {}

    def get(self, name: str, standard_field: str, fy: str) -> Input | Missing:
        key = (standard_field, fy)
        if key not in self._cache:
            self._cache[key] = self._resolve(standard_field, fy)
        got = self._cache[key]
        if isinstance(got, Input):
            return Input(**{**got.__dict__, "name": name})
        return got

    def _resolve(self, standard_field: str, fy: str) -> Input | Missing:
        r = resolve_value(self.session, self.company_id, standard_field, fy, self.basis, self.policy)
        if r.status == NO_DATA:
            return Missing(standard_field, fy, "NO_DATA")
        if r.status == CONFLICT:
            vals = ", ".join(f"{p}={v:,.0f}" for p, v in sorted(r.candidates.items()))
            return Missing(standard_field, fy, "SOURCE_CONFLICT", f"({vals})")
        snap = self.session.get(Snapshot, r.snapshot_id)
        return Input(
            name=standard_field, standard_field=standard_field, fy=fy, basis=self.basis,
            value=r.value, line_item_id=r.line_item_id, snapshot_id=r.snapshot_id,
            provider=r.provider, resolution=r.status, derived=(r.status == DERIVED_ESTIMATE),
            snapshot_fetched_at=snap.fetched_at.isoformat() if snap else "",
            providers=tuple(sorted(r.candidates)) or (r.provider,),
        )

    def gather(self, specs: list[tuple[str, str, str]]) -> tuple[dict[str, Input] | None, list[Missing]]:
        """specs: [(name, standard_field, fy)]. Returns (inputs by name, missing)."""
        got, missing = {}, []
        for name, std, fy in specs:
            item = self.get(name, std, fy)
            if isinstance(item, Missing):
                missing.append(item)
            else:
                got[name] = item
        return (None, missing) if missing else (got, [])


def prior_fy(fy: str) -> str | None:
    if fy.startswith("FY") and fy[2:].isdigit():
        return f"FY{int(fy[2:]) - 1}"
    return None


def threshold(cfg: dict, level: str) -> float | None:
    t = (cfg.get("thresholds") or {}).get(level)
    return None if t is None else t.get("value")


def severity_for(value: float, cfg: dict) -> str | None:
    """High / medium by the config limits; None if below both or no approved limit."""
    high, medium = threshold(cfg, "high"), threshold(cfg, "medium")
    if high is not None and value > high:
        return "high"
    if medium is not None and value > medium:
        return "medium"
    return None


def thresholds_applied(cfg: dict) -> dict[str, Any]:
    return {
        level: {"value": t.get("value"), "source": t.get("source")}
        for level, t in (cfg.get("thresholds") or {}).items()
    }


def materiality(store: InputStore, fy: str, amount: float, cfg: dict) -> tuple[dict[str, Any], list[Input]]:
    """Amount at issue as a % of a base (revenue). Label only — never suppresses a flag."""
    m_cfg = cfg.get("materiality") or {}
    base_field = m_cfg.get("base_field", "revenue_from_operations")
    base = store.get("materiality_base", base_field, fy)
    limit = ((m_cfg.get("material_if_ge_pct") or {}).get("value"))
    out = {"basis": f"{m_cfg.get('amount', 'amount at issue')} as % of {base_field}",
           "limit_pct": limit, "limit_source": (m_cfg.get("material_if_ge_pct") or {}).get("source")}
    if isinstance(base, Missing) or base.value == 0 or limit is None:
        out.update({"value_pct": None, "label": "unassessed"})
        return out, []
    pct = abs(amount) / abs(base.value) * 100.0
    out.update({"value_pct": pct, "label": "material" if pct >= limit else "not_material"})
    return out, [base]


def evidence_confidence(inputs: list[Input]) -> str:
    """low: any estimate, or no single provider supports every input.
    medium: one provider supports every input. high: every input confirmed by two."""
    if not inputs or any(i.derived for i in inputs):
        return CONF_LOW
    common = set.intersection(*[set(i.providers or (i.provider,)) for i in inputs])
    if not common:
        return CONF_LOW
    return CONF_HIGH if all(i.resolution == AGREE for i in inputs) else CONF_MEDIUM


def crore(x: float) -> str:
    return f"{x / 1e7:,.0f}"


def skip_from_missing(fy: str, missing: list[Missing]) -> Skip:
    reason = "SOURCE_CONFLICT" if any(m.reason == "SOURCE_CONFLICT" for m in missing) else "NOT_ENOUGH_DATA"
    return Skip(fy, reason, "; ".join(m.text() for m in missing))


def finish(check_id: str, cfg: dict, observations: list[Observation], skipped: list[Skip],
           metric_only: bool = False) -> CheckResult:
    if not observations and skipped:
        status = STATUS_NOT_ENOUGH_DATA
    elif metric_only:
        status = STATUS_METRIC_ONLY
    else:
        status = STATUS_COMPLETED
    return CheckResult(check_id, cfg.get("check_version", 1), status, observations, skipped)
