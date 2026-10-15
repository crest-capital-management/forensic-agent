"""TEMPORARY connector: RapidAPI "India Stock Market MoneyControl Live API".

This is a stand-in for Morningstar/Ace Equity while those integrations are
pending. All data returned by this connector is provisional (see
Snapshot.provisional) — RapidAPI's licence and reliability have not been
vetted for production use (see Build Plan section 17 and Developer Review
section 3.3).
"""
from __future__ import annotations

import datetime as dt
import json
import os

import httpx

from crest_forensic.connectors.base import (
    Basis,
    RawSourceResponse,
    SourceConnector,
    StatementType,
)

_HOST = "india-stock-market-moneycontrol-live-api.p.rapidapi.com"
_BASE_URL = f"https://{_HOST}/api/moneycontrol"

_STATEMENT_ENDPOINTS: dict[StatementType, str] = {
    "income": "/stocks/financials/income",
    "balance_sheet": "/stocks/financials/balance-sheet",
    "cash_flow": "/stocks/financials/cash-flow",
    "ratios": "/stocks/financials/ratios",
}


class RapidApiMoneyControlConnector(SourceConnector):
    provider_name = "rapidapi_moneycontrol"

    def __init__(self, api_key: str | None = None, timeout: float = 20.0) -> None:
        self._api_key = api_key or os.environ.get("RAPIDAPI_KEY")
        if not self._api_key:
            raise RuntimeError(
                "RAPIDAPI_KEY is not set. Add it to your environment or .env file."
            )
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-key": self._api_key,
            "x-rapidapi-host": _HOST,
        }

    def _get(self, path: str, params: dict[str, str]) -> RawSourceResponse:
        url = f"{_BASE_URL}{path}"
        fetched_at = dt.datetime.now(dt.timezone.utc)
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url, params=params, headers=self._headers())

        payload: dict = {}
        parse_error: str | None = None
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            parse_error = f"JSONDecodeError: {exc}"

        return RawSourceResponse(
            provider=self.provider_name,
            endpoint=path,
            request_params=params,
            status_code=resp.status_code,
            payload=payload if isinstance(payload, dict) else {"data": payload},
            fetched_at=fetched_at,
            raw_text=None if not parse_error else resp.text,
            parse_error=parse_error,
        )

    def search_company(self, query: str) -> RawSourceResponse:
        return self._get("/stocks/search", {"query": query})

    def fetch_financials(
        self, sc_id: str, statement_type: StatementType, basis: Basis
    ) -> RawSourceResponse:
        path = _STATEMENT_ENDPOINTS[statement_type]
        params = {"sc_id": sc_id}
        if statement_type != "ratios":
            params["type"] = basis
        return self._get(path, params)

    def fetch_shareholding(self, sc_id: str) -> RawSourceResponse:
        return self._get("/stocks/shareholding", {"sc_id": sc_id})
