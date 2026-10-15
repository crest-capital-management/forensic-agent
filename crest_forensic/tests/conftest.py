from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crest_forensic.db.models import Base, Company


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def company(session) -> Company:
    c = Company(name="Test Co", sc_id="TESTCO", sector="IT Services")
    session.add(c)
    session.flush()
    return c
