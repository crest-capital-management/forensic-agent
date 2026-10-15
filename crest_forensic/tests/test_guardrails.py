"""Guardrail tests: a tampered or badly worded flag must be dropped (Build Plan section 14)."""
import dataclasses

import pytest
from sqlalchemy import select

import crest_forensic.screen as screen_module
from crest_forensic.checks.base import InputStore
from crest_forensic.checks.profit_cash import run_j1_01
from crest_forensic.db.models import Company, Flag, GuardrailEvent
from crest_forensic.guardrails.language import LEADS_NOT_PROOF, PUBLIC_DATA_LIMIT, banned_terms_in
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.ingestion.resolve import load_policy
from crest_forensic.screen import load_check_config
from crest_forensic.tests.helpers import make_snapshot, screen, seed


@pytest.fixture()
def observation(session, company):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "profit_after_tax", {"FY2025": 100})
    seed(session, company, snap, "cash_flow_from_operations", {"FY2025": 50})
    seed(session, company, snap, "revenue_from_operations", {"FY2025": 1000})
    store = InputStore(session, company.company_id, "standalone", load_policy())
    result = run_j1_01(store, ["FY2025"], load_check_config()["checks"]["J1-01"])
    return result.observations[0]


def guardrails_hit(session, company, obs, basis="standalone"):
    return {g for g, _ in validate_observation(session, obs, company.company_id, basis)}


def test_clean_observation_passes(session, company, observation):
    assert guardrails_hit(session, company, observation) == set()


def test_a_figure_that_differs_from_the_saved_value_is_dropped(session, company, observation):
    tampered = dataclasses.replace(observation, inputs=[
        dataclasses.replace(i, value=i.value * 2) if i.name == "cfo" else i for i in observation.inputs])
    assert "citation" in guardrails_hit(session, company, tampered)


def test_a_metric_that_does_not_recompute_is_dropped(session, company, observation):
    wrong = dataclasses.replace(observation, metric_value=0.99)
    assert guardrails_hit(session, company, wrong) == {"recalculation"}


def test_citing_a_row_that_does_not_exist_is_dropped(session, company, observation):
    ghost = dataclasses.replace(observation, inputs=[
        dataclasses.replace(i, line_item_id=999999) if i.name == "pat" else i for i in observation.inputs])
    assert "citation" in guardrails_hit(session, company, ghost)


def test_citing_the_wrong_year_is_dropped(session, company, observation):
    wrong_year = dataclasses.replace(observation, inputs=[
        dataclasses.replace(i, fy="FY2024") if i.name == "pat" else i for i in observation.inputs])
    assert "citation" in guardrails_hit(session, company, wrong_year)


def test_basis_mismatch_is_dropped(session, company, observation):
    assert "citation" in guardrails_hit(session, company, observation, basis="consolidated")


def test_citing_another_companys_row_is_dropped(session, company, observation):
    other = Company(name="Other Co", sc_id="OTHER")
    session.add(other)
    session.flush()
    seed(session, other, make_snapshot(session, other), "profit_after_tax", {"FY2025": 100})
    from crest_forensic.db.models import LineItem
    foreign = session.execute(select(LineItem).where(LineItem.company_id == other.company_id)).scalar_one()
    stolen = dataclasses.replace(observation, inputs=[
        dataclasses.replace(i, line_item_id=foreign.value_id, snapshot_id=foreign.snapshot_id)
        if i.name == "pat" else i for i in observation.inputs])
    assert "citation" in guardrails_hit(session, company, stolen)


@pytest.mark.parametrize("text", [
    "This shows fraud occurred", "The company committed an offence", "Evidence of criminal conduct",
    "management was guilty", "Fraudulent reporting",
])
def test_banned_language_is_dropped(session, company, observation, text):
    bad = dataclasses.replace(observation, what_observed=text)
    assert "banned_language" in guardrails_hit(session, company, bad)


def test_our_own_standard_disclaimers_contain_no_banned_wording():
    assert banned_terms_in(LEADS_NOT_PROOF, PUBLIC_DATA_LIMIT) == []


def test_a_flag_failing_a_guardrail_is_dropped_and_logged_not_created(session, company, tmp_path, monkeypatch):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "profit_after_tax", {"FY2025": 100})
    seed(session, company, snap, "cash_flow_from_operations", {"FY2025": 50})
    monkeypatch.setattr(screen_module, "validate_observation",
                        lambda *a, **k: [("citation", "forced failure for the test")])

    run = screen(session, company, tmp_path, ["FY2025"])

    assert run.flags_created == 0 and run.flags_dropped == 1
    assert session.execute(select(Flag).where(Flag.run_id == run.id)).scalars().all() == []
    (event,) = session.execute(select(GuardrailEvent).where(GuardrailEvent.run_id == run.id)).scalars().all()
    assert event.guardrail == "citation" and event.check_id == "J1-01"
