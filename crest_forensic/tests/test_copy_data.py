import datetime as dt

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from crest_forensic.db.copy_data import as_utc, check_value, copy_database
from crest_forensic.db.models import Base, Company, Flag, Run, ConfigVersion, Snapshot
from crest_forensic.db.url import normalize_url


def _url(tmp_path, name):
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _seed(url, long_name=False):
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        co = Company(name=("x" * 300) if long_name else "Test Co", nse_symbol="TST")
        s.add(co)
        s.flush()
        snap = Snapshot(company_id=co.company_id, source_provider="p", source_endpoint="e", request_params={"a": 1}, raw_payload={"k": [1, 2]}, payload_hash="h")
        s.add(snap)
        cfg = ConfigVersion(version=1, content={"x": 1}, content_hash="h")
        s.add(cfg)
        s.flush()
        run = Run(company_id=co.company_id, basis="consolidated", years=["FY2025"], config_version_id=cfg.id, config_approved=True,
                  code_version="c", run_signature="sig", manifest={})
        s.add(run)
        s.flush()
        s.add(Flag(run_id=run.id, check_id="J1-03", check_version=1, financial_year="FY2025", what_observed="o", location={}, technique="t",
                   severity="high", severity_rule_id="R", materiality={}, evidence_confidence="high", figures={"n": 1.5}, citation={}, content_hash="c"))
        s.commit()
    return engine


def test_normalize_url_accepts_the_usual_postgres_spellings():
    assert normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_url("postgresql+psycopg://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_url("sqlite:///./x.db") == "sqlite:///./x.db"


def test_naive_timestamps_become_utc_and_aware_ones_are_kept():
    naive = dt.datetime(2026, 10, 15, 6, 0)
    assert as_utc(naive).tzinfo == dt.timezone.utc and as_utc(naive).hour == 6
    ist = dt.datetime(2026, 10, 15, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
    assert as_utc(ist) == ist and as_utc("text") == "text"


def test_check_value_finds_what_postgres_would_refuse():
    col = Company.__table__.c.name                                  # String(255), required
    assert check_value("companies", col, "ok") is None
    assert "does not fit 255" in check_value("companies", col, "x" * 300)
    assert "NUL" in check_value("companies", col, "a\x00b")
    assert check_value("companies", Company.__table__.c.company_id, "7") is not None      # a number kept as text


def test_a_full_copy_is_complete_verified_and_keeps_the_data(tmp_path):
    src, dst = _url(tmp_path, "a.db"), _url(tmp_path, "b.db")
    _seed(src)
    rep = copy_database(src, dst)
    assert rep.copied and rep.verified and rep.ok() and sum(rep.counts.values()) == 5
    with Session(create_engine(dst)) as s:
        assert s.scalar(select(Company.name)) == "Test Co"
        assert s.scalar(select(Flag.figures)) == {"n": 1.5} and s.scalar(select(Snapshot.raw_payload)) == {"k": [1, 2]}


def test_a_row_that_would_not_fit_stops_everything_before_any_copy(tmp_path):
    src, dst = _url(tmp_path, "a.db"), _url(tmp_path, "b.db")
    _seed(src, long_name=True)
    rep = copy_database(src, dst)
    assert not rep.ok() and not rep.copied and "does not fit 255" in rep.problems[0]
    assert not (tmp_path / "b.db").exists()                          # nothing was created in the target


def test_check_only_copies_nothing_and_a_non_empty_target_is_refused(tmp_path):
    src, dst = _url(tmp_path, "a.db"), _url(tmp_path, "b.db")
    _seed(src)
    assert copy_database(src, dst, check_only=True).ok() and not (tmp_path / "b.db").exists()
    assert copy_database(src, dst).verified
    again = copy_database(src, dst)
    assert not again.copied and any("already holds rows" in p for p in again.problems)
