import pytest
from sqlalchemy import select

from crest_forensic.db.models import AppUser, CheckResultRow, ConfigVersion, Flag, Run
from crest_forensic.guardrails.language import banned_terms_in
from crest_forensic.review import service as svc
from crest_forensic.typology import match as typ


@pytest.fixture()
def users(session):
    svc.ensure_default_users(session)
    return {u.role: u for u in session.execute(select(AppUser)).scalars()}


def _run(session, company):
    cfg = ConfigVersion(version=1, content={}, content_hash="h")
    session.add(cfg)
    session.flush()
    run = Run(company_id=company.company_id, basis="consolidated", years=["FY2026"], config_version_id=cfg.id,
              config_approved=True, code_version="t", run_signature="s", manifest={})
    session.add(run)
    session.flush()
    return run


def _flag(session, run, check_id, materiality="material", fy="FY2026"):
    f = Flag(run_id=run.id, check_id=check_id, check_version=1, financial_year=fy, what_observed=f"{check_id} observed",
             location={}, technique="t", severity="high", severity_rule_id="R", materiality={"label": materiality},
             evidence_confidence="high", figures={}, citation={"inputs": [{"x": 1}]}, content_hash=f"{check_id}{fy}{materiality}")
    session.add(f)
    session.flush()
    return f


def _computed(session, run, check_id, n=2):
    session.add(CheckResultRow(run_id=run.id, check_id=check_id, check_version=1, status="COMPLETED", detail={"observations": n}))


def _case(session, users, company):
    return svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "routine screen")


def _accept(session, users, case, flag):
    svc.review_flag(session, users["analyst"], case.id, flag.id, "accept", "real")


def test_library_has_references_on_both_sides_and_no_banned_wording_in_the_tools_own_text():
    lib = typ.load_schemes()
    assert lib["scoring"]["min_present"] == 3
    for s in lib["schemes"]:
        assert s["citations"]["acfe"] and s["citations"]["fais"]
        assert banned_terms_in(s["scheme_name"], s["plain_pattern"], s["class_label"]) == []
        for ind in s["indicators"]:
            assert bool(ind.get("tool_check")) != bool(ind.get("record_tag"))      # exactly one source per indicator


def test_one_strong_flag_never_makes_a_match(session, users, company):
    run = _run(session, company)
    case = _case(session, users, company)
    _accept(session, users, case, _flag(session, run, "J1-03"))
    out = typ.run_matching(session, users["analyst"], case.id)
    assert out["matches"] == [] and out["ranked_now"] == 0
    assert max(p["present"] for p in out["preview"]) == 1


def test_three_accepted_flags_rank_the_scheme_with_missing_and_contradicting_facts(session, users, company):
    run = _run(session, company)
    case = _case(session, users, company)
    for check in ("J1-03", "J1-04", "J1-10"):
        _accept(session, users, case, _flag(session, run, check))
    _computed(session, run, "J1-11")                              # ran, nothing flagged: this cuts against FSF-02
    session.flush()
    out = typ.run_matching(session, users["analyst"], case.id)
    ids = [m["scheme_id"] for m in out["matches"]]
    assert ids == ["FSF-02"]                                      # FSF-01 has only 2 present indicators (J1-03, J1-10): not ranked
    m = out["matches"][0]
    assert m["label"] == "hypothesis" and m["coverage"] == 0.5     # 3 of 6
    assert {p["check_id"] for p in m["present"]} == {"J1-03", "J1-04", "J1-10"}
    assert any("J1-11 was computed" in a for a in m["against"])    # a fact that cuts against it is kept
    assert {x["indicator"] for x in m["missing"]} >= {"Restated or re-presented balance sheet figures"}   # missing indicators are listed
    assert m["citations"]["acfe"] and m["citations"]["fais"] and m["innocent_explanations"] and m["evidence_to_confirm"]


def test_unreviewed_rejected_and_not_material_flags_do_not_count(session, users, company):
    run = _run(session, company)
    case = _case(session, users, company)
    _flag(session, run, "J1-03")                                                          # unreviewed
    f = _flag(session, run, "J1-04")
    svc.review_flag(session, users["analyst"], case.id, f.id, "reject", "explained")      # rejected
    _accept(session, users, case, _flag(session, run, "J1-10", materiality="not_material"))
    flags, info = typ.counted_flags(session, session.get(type(case), case.id))
    assert flags == [] and info["left_out"] == {"unreviewed": 1, "rejected": 1, "not_material": 1}


def test_public_record_items_count_by_tag_and_a_named_individual_needs_a_partner(session, users, company):
    run = _run(session, company)
    case = _case(session, users, company)
    _accept(session, users, case, _flag(session, run, "J1-14"))
    _accept(session, users, case, _flag(session, run, "J1-11"))
    base = {"kind": "announcement", "source_name": "Exchange announcement", "summary": "The company announced a change.", "tags": ["enforcement_or_media_record"]}
    typ.add_record(session, users["analyst"], company.company_id, {**base, "title": "Order about the group", "names_individual": True})
    out = typ.run_matching(session, users["analyst"], case.id)
    m = next(m for m in out["matches"] if m["scheme_id"] == "COR-01")           # 2 flags + 1 record = 3 present
    assert m["named_individual"] is True and m["partner"]["status"] == "pending"
    with pytest.raises(svc.RuleError):                                           # the lead alone is not enough
        typ.partner_review(session, users["forensic_lead"], m["id"], "accepted", "ok")
    typ.review_match(session, users["forensic_lead"], m["id"], "accepted", "worth pursuing", True)
    row = session.get(typ.TypologyMatch, m["id"])
    assert not typ.usable_for_work_product(row)
    typ.partner_review(session, users["partner"], m["id"], "accepted", "retain")
    assert typ.usable_for_work_product(row)


def test_review_rules(session, users, company):
    run = _run(session, company)
    case = _case(session, users, company)
    for check in ("J1-03", "J1-04", "J1-10"):
        _accept(session, users, case, _flag(session, run, check))
    out = typ.run_matching(session, users["analyst"], case.id)
    mid = out["matches"][0]["id"]
    with pytest.raises(svc.RuleError):
        typ.review_match(session, users["analyst"], mid, "accepted", "x", True)                  # only the forensic lead
    with pytest.raises(svc.RuleError):
        typ.review_match(session, users["forensic_lead"], mid, "accepted", " ", True)            # a reason is required
    with pytest.raises(svc.RuleError):
        typ.review_match(session, users["forensic_lead"], mid, "accepted", "fine", False)        # references must be confirmed as checked
    assert typ.review_match(session, users["forensic_lead"], mid, "accepted", "fine", True)["review"]["status"] == "accepted"
    with pytest.raises(svc.RuleError):
        typ.review_match(session, users["forensic_lead"], mid, "rejected", "this proves fraud", True)    # banned wording in a note


def test_unchanged_inputs_do_not_create_a_new_batch_and_changes_do(session, users, company):
    run = _run(session, company)
    case = _case(session, users, company)
    for check in ("J1-03", "J1-04", "J1-10"):
        _accept(session, users, case, _flag(session, run, check))
    first = typ.run_matching(session, users["analyst"], case.id)
    again = typ.run_matching(session, users["analyst"], case.id)
    assert again["unchanged"] is True and again["saved_batch"] == first["saved_batch"] == 1
    _accept(session, users, case, _flag(session, run, "J1-15"))
    assert typ.overview(session, case.id)["stale"] is True
    assert typ.run_matching(session, users["analyst"], case.id)["saved_batch"] == 2


def test_public_record_wording_and_tags_are_checked(session, users, company):
    ok = {"kind": "news", "title": "Report on the group", "source_name": "Business daily", "summary": "The paper reports a change.", "tags": ["enforcement_order"]}
    with pytest.raises(svc.RuleError):
        typ.add_record(session, users["analyst"], company.company_id, {**ok, "summary": "The promoters committed fraud."})
    with pytest.raises(svc.RuleError):
        typ.add_record(session, users["analyst"], company.company_id, {**ok, "tags": ["made_up_tag"]})
    with pytest.raises(svc.RuleError):
        typ.add_record(session, users["adviser"], company.company_id, ok)                        # adviser may not add
    assert typ.add_record(session, users["analyst"], company.company_id, ok)["tags"] == ["enforcement_order"]


def test_only_matches_the_lead_accepted_reach_the_memo_annex_and_the_tools_own_text_is_clean(session, users, company):
    from crest_forensic.db.models import Case
    from crest_forensic.review import memo as memo_mod

    run = _run(session, company)
    case = _case(session, users, company)
    for check in ("J1-03", "J1-04", "J1-10"):
        _accept(session, users, case, _flag(session, run, check))
    out = typ.run_matching(session, users["analyst"], case.id)
    case_row = session.get(Case, case.id)
    assert memo_mod.scheme_hypotheses(session, case_row)["matches"] == []                  # pending: not usable yet
    typ.review_match(session, users["forensic_lead"], out["matches"][0]["id"], "accepted", "worth pursuing", True)
    hyp = memo_mod.scheme_hypotheses(session, case_row)
    assert [m["scheme_id"] for m in hyp["matches"]] == ["FSF-02"] and hyp["matches"][0]["label"] == "hypothesis"
    own_text = {k: v for k, v in hyp.items() if k != "references"}
    assert banned_terms_in(*memo_mod._all_strings(own_text)) == []
    assert any("Fraud" in r for refs in hyp["references"].values() for r in refs)          # source names are kept apart from the tool's wording
