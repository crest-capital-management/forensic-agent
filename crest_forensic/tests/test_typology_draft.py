from crest_forensic.screen import load_check_config
from crest_forensic.typology.build_outline import load


def test_library_is_in_use_names_real_checks_and_carries_references():
    data = load()
    assert data["status"] == "in_use" and data["approved_by"]
    known = set(load_check_config()["checks"])
    ids = [s["id"] for s in data["schemes"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 5
    for s in data["schemes"]:
        assert s["citations"]["acfe"] and s["citations"]["fais"]
        assert s["contradicting"] and s["innocent_explanations"] and s["evidence_to_confirm"]
        for i in s["indicators"]:
            assert i["tool_check"] in known if i.get("tool_check") else i.get("record_tag")
        assert len(s["indicators"]) >= data["scoring"]["min_present"]
    # every scheme can reach the minimum once public-record items are added
    assert all(len(s["indicators"]) >= data["scoring"]["min_present"] for s in data["schemes"])
