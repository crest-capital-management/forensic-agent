"""Extraction helpers for the RapidAPI MoneyControl response shape.

Confirmed empirically (2026-09-28, TCS, snapshots 1-8 in the local DB — no
further live calls should be needed to re-derive this): every
/stocks/financials/* endpoint returns:

    {"status": "success", "meta": {...}, "data": [
        {"type": "MAN", "year": "2026", "month": "March", "item": [
            {"name": "Net Sales/Income from operations", "value": "59,553.00", "head_flag": 0},
            ...
        ]},
        ... one entry per period ...
    ]}

`year`+`month` together are the period's end date (not an Indian-FY label —
see financial_year_from_year_month). `value` is a formatted string; "--" or
"" means not disclosed for that period. /stocks/shareholding uses a
different, flatter shape (see mapping.py) and is handled separately.
"""
from __future__ import annotations

import re
from typing import Any

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def get_by_path(payload: Any, path: str) -> Any | None:
    """Resolve a dotted/bracket path like 'data.rows[0].value' against payload.

    Returns None if any segment is missing — never raises, so a bad/guessed
    path just looks like "field not available" rather than crashing ingestion.
    Kept as a fallback strategy for a future provider with a flatter shape.
    """
    current = payload
    for key, index in _PATH_TOKEN_RE.findall(path):
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        elif index != "":
            idx = int(index)
            if not isinstance(current, list) or idx >= len(current) or idx < 0:
                return None
            current = current[idx]
    return current


def extract_periods(payload: dict) -> list[dict] | None:
    """Return payload['data'] if it looks like the period/item list shape."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list) and all(isinstance(p, dict) and "item" in p for p in data):
        return data
    return None


def find_item_value(period_entry: dict, name_contains: str) -> Any | None:
    """Search one period's item list for a name match (case-insensitive substring).

    Returns None if not found OR if more than one item matches ambiguously
    (callers should tighten name_contains rather than risk picking the wrong
    line — e.g. "Total Debt" vs "Total Debt to Owners Fund").
    """
    needle = name_contains.strip().lower()
    matches = [it for it in period_entry.get("item", []) if needle == str(it.get("name", "")).strip().lower()]
    if len(matches) == 1:
        return matches[0].get("value")
    if len(matches) > 1:
        return None
    return None
