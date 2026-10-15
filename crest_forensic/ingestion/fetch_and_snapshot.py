from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Snapshot
from crest_forensic.ingestion.quality import (
    PARSE_ERROR,
    SEVERITY_ERROR,
    log_quality_event,
)


def compute_payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def save_snapshot(
    session: Session, company_id: int, response: RawSourceResponse
) -> Snapshot:
    """Persist one fetch as a new, immutable snapshot row.

    Never updates or deletes an existing snapshot — every call to this
    function inserts a new row, even for an identical payload.
    """
    if response.parse_error:
        payload_to_store = {
            "_parse_error": response.parse_error,
            "_raw_text": response.raw_text,
            "_status_code": response.status_code,
        }
    else:
        payload_to_store = response.payload

    snapshot = Snapshot(
        company_id=company_id,
        source_provider=response.provider,
        source_endpoint=response.endpoint,
        request_params=response.request_params,
        fetched_at=response.fetched_at,
        raw_payload=payload_to_store,
        payload_hash=compute_payload_hash(payload_to_store),
        provisional=True,
    )
    session.add(snapshot)
    session.flush()  # assign snapshot_id before we log an event against it

    if response.parse_error:
        log_quality_event(
            session,
            snapshot_id=snapshot.snapshot_id,
            company_id=company_id,
            field_name=None,
            issue_type=PARSE_ERROR,
            severity=SEVERITY_ERROR,
            note=f"Failed to parse response from {response.endpoint}: {response.parse_error}",
        )

    return snapshot
