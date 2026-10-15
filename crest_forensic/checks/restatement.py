"""J1-09 restatement, and J1-08 (not yet defined).

J1-09 compares the SAME figure as saved in two different snapshots taken on
different dates. Cross-source differences (MoneyControl vs Yahoo) are not
restatements — they are handled by the source-conflict rule — so only
snapshots from the same provider and the same source field are compared.
"""
from __future__ import annotations

from sqlalchemy import select

from crest_forensic.checks import formulas
from crest_forensic.checks.base import (
    STATUS_NEEDS_DEFINITION, CheckResult, Input, InputStore, Observation, Skip, finish,
    materiality, thresholds_applied,
)
from crest_forensic.db.models import LineItem, Snapshot


def _as_input(name: str, li: LineItem, snap: Snapshot, provider: str) -> Input:
    return Input(
        name=name, standard_field=li.standard_field, fy=li.financial_year, basis=li.basis,
        value=li.normalized_value, line_item_id=li.value_id, snapshot_id=li.snapshot_id,
        provider=provider, resolution="SINGLE_SOURCE", derived=False,
        snapshot_fetched_at=snap.fetched_at.isoformat(),
    )


def run_j1_09(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    rows = store.session.execute(
        select(LineItem, Snapshot)
        .join(Snapshot, Snapshot.snapshot_id == LineItem.snapshot_id)
        .where(LineItem.company_id == store.company_id, LineItem.basis == store.basis)
        .where(LineItem.period_type == "annual", LineItem.derivation_method.is_(None))
        .where(LineItem.normalized_value.is_not(None), LineItem.financial_year.in_(years))
        .order_by(Snapshot.fetched_at, LineItem.snapshot_id)
    ).all()

    groups: dict[tuple, list[tuple[LineItem, Snapshot]]] = {}
    for li, snap in rows:
        groups.setdefault((snap.source_provider, li.source_ref, li.standard_field, li.financial_year), []).append((li, snap))

    comparable = {k: v for k, v in groups.items() if len({s.snapshot_id for _, s in v}) >= 2}
    if not comparable:
        result = finish("J1-09", cfg, [], [Skip("*", "NOT_ENOUGH_DATA",
                        "only one saved snapshot exists for every figure; restatement needs at least two "
                        "snapshots of the same source taken on different dates")])
        return result

    severity = (cfg.get("any_difference_severity") or {}).get("value")
    obs = []
    for (provider, _ref, std_field, fy), versions in sorted(comparable.items()):
        for (old_li, old_snap), (new_li, new_snap) in zip(versions, versions[1:]):
            if old_li.normalized_value == new_li.normalized_value:
                continue
            change = formulas.restatement_change_pct(old_li.normalized_value, new_li.normalized_value)
            if change is None:
                continue
            mat, mat_inputs = materiality(store, fy, new_li.normalized_value - old_li.normalized_value, cfg)
            obs.append(Observation(
                check_id="J1-09", fy=fy, metric_name="percent change between saved versions", metric_value=change,
                severity=severity, severity_rule_id=cfg["rule_id"], formula_id="J1-09.v1",
                technique="Restatement: same figure compared across two saved snapshots",
                what_observed=(
                    f"The saved value of {std_field} for {fy} differs between the snapshot of "
                    f"{old_snap.fetched_at.date()} and the snapshot of {new_snap.fetched_at.date()} ({change:+.2f}%)."),
                inputs=[_as_input("old", old_li, old_snap, provider), _as_input("new", new_li, new_snap, provider)] + mat_inputs,
                thresholds_applied=thresholds_applied(cfg), materiality=mat,
                figures={"field": std_field, "old_value": old_li.normalized_value,
                         "new_value": new_li.normalized_value, "change_pct": round(change, 4)},
            ))
    return finish("J1-09", cfg, obs, [])


def run_j1_08(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    result = CheckResult("J1-08", cfg.get("check_version", 1), STATUS_NEEDS_DEFINITION)
    result.notes.append(
        "Cost capitalisation is described in the plan only as 'rise in assets share versus expenses', "
        "with no formula or limit. Not run until the forensic lead defines it.")
    return result
