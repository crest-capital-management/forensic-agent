"""Abstract source connector interface.

Any data provider (RapidAPI MoneyControl today, Morningstar later) implements
this interface. Nothing outside `connectors/` should know which provider is
in use — the ingestion layer only talks to `SourceConnector`.
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

StatementType = Literal["income", "balance_sheet", "cash_flow", "ratios"]
Basis = Literal["standalone", "consolidated"]


@dataclass
class RawSourceResponse:
    """Everything about one fetch, before any parsing/transformation.

    `payload` is the parsed JSON body when parsing succeeded. When it fails,
    `payload` is an empty dict and `parse_error`/`raw_text` explain why —
    callers must still persist this as a snapshot (raw-first, transform-second).
    """

    provider: str
    endpoint: str
    request_params: dict[str, Any]
    status_code: int
    payload: dict[str, Any]
    fetched_at: dt.datetime
    raw_text: str | None = None
    parse_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class SourceConnector(ABC):
    """Read-only adapter to one financial-data provider."""

    provider_name: str

    @abstractmethod
    def search_company(self, query: str) -> RawSourceResponse:
        """Resolve a company name/ticker to the provider's internal id."""

    @abstractmethod
    def fetch_financials(
        self, sc_id: str, statement_type: StatementType, basis: Basis
    ) -> RawSourceResponse:
        """Fetch one financial statement (income / balance_sheet / cash_flow / ratios)."""

    @abstractmethod
    def fetch_shareholding(self, sc_id: str) -> RawSourceResponse:
        """Fetch shareholding pattern / promoter pledging by quarter."""
