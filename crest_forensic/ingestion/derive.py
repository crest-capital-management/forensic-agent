"""Derived values — computed FROM other line items, never read from a source.

Currently just one: an indirect-method estimate of cash_flow_from_operations,
because the RapidAPI MoneyControl provider has no working source for CFO at
all (confirmed 2026-09-29 — its "cash-flow" endpoint's own `meta.statement`
says "cash-flow" but every line item in it is actually an annual P&L
statement; there is no operating/investing/financing breakdown anywhere in
this API).

This is a real, standard accounting reconstruction (the same method used to
build a cash flow statement FROM an income statement + balance sheet when
one isn't published), not a guess — but it is an APPROXIMATION of the real,
audited CFO, since it ignores items this provider doesn't give us (tax
paid vs. accrued timing, other working-capital items beyond receivables/
inventory/current-liabilities, non-cash items besides depreciation, etc).
Every row this produces is tagged `derivation_method` and logged as
DERIVED_VALUE — it must never be treated as a sourced figure.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import LineItem, Snapshot
from crest_forensic.ingestion.quality import (
    DERIVATION_SKIPPED,
    DERIVED_VALUE,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    log_quality_event,
)

METHOD_INDIRECT_V1 = "indirect_method_v1"
_INPUT_PROVIDER = "rapidapi_moneycontrol"

_REQUIRED_FLOW = ["profit_after_tax", "depreciation_amortisation"]
_REQUIRED_STOCK = ["trade_receivables", "inventories", "current_liabilities"]


def _prior_fy(fy_label: str) -> str | None:
    if not fy_label.startswith("FY") or not fy_label[2:].isdigit():
        return None
    return f"FY{int(fy_label[2:]) - 1}"


def derive_cfo_indirect(session: Session, company_id: int, basis: str) -> list[LineItem]:
    """CFO ≈ PAT + Depreciation − ΔReceivables − ΔInventories + ΔCurrentLiabilities.

    Only uses directly-sourced inputs (derivation_method IS NULL) so a
    derived value is never built on top of another derived value. Skips —
    and logs — any year missing a required input rather than guessing.
    """
    # Inputs come from ONE provider only (never a mix of two sources' definitions).
    rows = session.execute(
        select(LineItem)
        .join(Snapshot, Snapshot.snapshot_id == LineItem.snapshot_id)
        .where(LineItem.company_id == company_id)
        .where(LineItem.basis == basis)
        .where(LineItem.period_type == "annual")
        .where(LineItem.standard_field.in_(_REQUIRED_FLOW + _REQUIRED_STOCK))
        .where(LineItem.derivation_method.is_(None))
        .where(Snapshot.source_provider == _INPUT_PROVIDER)
        .order_by(LineItem.snapshot_id)
    ).scalars().all()

    by_field_year: dict[str, dict[str, LineItem]] = {}
    for r in rows:
        if r.normalized_value is not None:
            by_field_year.setdefault(r.standard_field, {})[r.financial_year] = r

    years = sorted(by_field_year.get("profit_after_tax", {}).keys())
    created: list[LineItem] = []

    for fy in years:
        prior_fy = _prior_fy(fy)
        missing = [
            f
            for f in _REQUIRED_FLOW
            if fy not in by_field_year.get(f, {})
        ] + [
            f"{f}@{yr}"
            for f in _REQUIRED_STOCK
            for yr in ([fy, prior_fy] if prior_fy else [fy])
            if yr not in by_field_year.get(f, {})
        ]
        if prior_fy is None:
            missing.append(f"unparseable prior year for {fy}")

        if missing:
            log_quality_event(
                session,
                company_id=company_id,
                field_name="cash_flow_from_operations",
                issue_type=DERIVATION_SKIPPED,
                severity=SEVERITY_WARNING,
                note=(
                    f"Could not derive CFO for {fy} ({basis}): missing {', '.join(missing)}."
                ),
            )
            continue

        pat = by_field_year["profit_after_tax"][fy]
        dep = by_field_year["depreciation_amortisation"][fy]
        recv_now = by_field_year["trade_receivables"][fy]
        recv_prior = by_field_year["trade_receivables"][prior_fy]
        inv_now = by_field_year["inventories"][fy]
        inv_prior = by_field_year["inventories"][prior_fy]
        cl_now = by_field_year["current_liabilities"][fy]
        cl_prior = by_field_year["current_liabilities"][prior_fy]

        delta_recv = recv_now.normalized_value - recv_prior.normalized_value
        delta_inv = inv_now.normalized_value - inv_prior.normalized_value
        delta_cl = cl_now.normalized_value - cl_prior.normalized_value
        cfo = pat.normalized_value + dep.normalized_value - delta_recv - delta_inv + delta_cl

        line_item = LineItem(
            company_id=company_id,
            snapshot_id=recv_now.snapshot_id,  # anchor: the balance_sheet snapshot for this year
            standard_field="cash_flow_from_operations",
            raw_value=f"derived={cfo:.2f}",
            normalized_value=cfo,
            unit="INR_absolute",
            currency="INR",
            financial_year=fy,
            period_end_date=None,
            period_type="annual",
            basis=basis,
            semantics="flow",
            statement_type="cash_flow",
            source_field_name="derived:indirect_method",
            source_ref=(
                f"derived from profit_after_tax(snapshot={pat.snapshot_id}), "
                f"depreciation_amortisation(snapshot={dep.snapshot_id}), "
                f"trade_receivables/inventories/current_liabilities "
                f"(snapshot={recv_now.snapshot_id}, {fy} vs {prior_fy})"
            ),
            mapping_version=1,
            derivation_method=METHOD_INDIRECT_V1,
        )
        session.add(line_item)
        created.append(line_item)

        log_quality_event(
            session,
            snapshot_id=recv_now.snapshot_id,
            company_id=company_id,
            field_name="cash_flow_from_operations",
            issue_type=DERIVED_VALUE,
            severity=SEVERITY_INFO,
            note=(
                f"{fy} ({basis}): cash_flow_from_operations is a DERIVED estimate "
                f"(indirect method), not sourced — this provider has no real CFO data. "
                f"PAT={pat.normalized_value:.0f} + Depreciation={dep.normalized_value:.0f} "
                f"- ΔReceivables={delta_recv:.0f} - ΔInventories={delta_inv:.0f} "
                f"+ ΔCurrentLiabilities={delta_cl:.0f} = {cfo:.0f}."
            ),
        )

    return created
