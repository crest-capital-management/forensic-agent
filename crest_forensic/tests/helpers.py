"""Seeding helpers for Phase 2 tests."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from crest_forensic.db.models import LineItem, Snapshot
from crest_forensic.screen import DEFAULT_CONFIG_PATH, run_screen

_T0 = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)


def make_snapshot(session, company, provider="rapidapi_moneycontrol", minutes=0) -> Snapshot:
    snap = Snapshot(
        company_id=company.company_id, source_provider=provider, source_endpoint="test",
        request_params={}, fetched_at=_T0 + dt.timedelta(minutes=minutes),
        raw_payload={}, payload_hash=f"{provider}-{minutes}", provisional=True,
    )
    session.add(snap)
    session.flush()
    return snap


def seed(session, company, snap, field, values: dict, basis="standalone", derivation=None):
    """values: {fy: absolute value}. One LineItem per year, all citing `snap`."""
    for fy, v in values.items():
        session.add(LineItem(
            company_id=company.company_id, snapshot_id=snap.snapshot_id, standard_field=field,
            raw_value=str(v), normalized_value=float(v), unit="INR_absolute", currency="INR",
            financial_year=fy, period_type="annual", basis=basis,
            semantics="flow", statement_type="income", source_field_name=field,
            source_ref=f"test:{field}", mapping_version=1, derivation_method=derivation,
        ))
    session.flush()


def config_path(tmp_path: Path, approved: bool = True, mutate=None) -> Path:
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    if approved:
        cfg["approval"] = {"approved_by": "forensic_lead_test", "approved_at": "2026-10-01"}
    if mutate:
        mutate(cfg)
    path = tmp_path / "check_config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def screen(session, company, tmp_path, years, basis="standalone", approved=True, mutate=None, allow_draft=False):
    return run_screen(
        session, company.company_id, basis, years, allow_draft_config=allow_draft,
        config_path=config_path(tmp_path, approved, mutate),
    )
