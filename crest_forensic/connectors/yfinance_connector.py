"""SECOND source: Yahoo Finance via the `yfinance` library.

Unofficial and not licensed for this use (see Developer Review 3.3) — so,
like the RapidAPI connector, everything it returns is stored provisional.
Used mainly because it carries real operating cash flow, which the RapidAPI
provider does not. Free, no API key.

Yahoo does not say whether a figure is standalone or consolidated, so this
connector never claims a basis; ingestion infers it from the data (see
ingestion/yahoo.py).
"""
from __future__ import annotations

import calendar
import datetime as dt
import math
from typing import Any

from crest_forensic.connectors.base import (
    Basis,
    RawSourceResponse,
    SourceConnector,
    StatementType,
)

_STATEMENT_ATTR = {
    "income": "financials",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cashflow",
}


def frame_to_payload(frame, ticker: str, statement_type: str, currency: str | None) -> dict[str, Any]:
    """Convert a yfinance DataFrame into the same period/item JSON shape the
    RapidAPI connector produces, so one normalizer handles both sources."""
    periods = []
    for col in frame.columns:
        items = []
        for name, value in frame[col].items():
            is_missing = value is None or (isinstance(value, float) and math.isnan(value))
            items.append(
                {"name": str(name), "value": "--" if is_missing else float(value), "head_flag": 0}
            )
        periods.append(
            {
                "type": "YF",
                "year": str(col.year),
                "month": calendar.month_name[col.month],
                "item": items,
            }
        )
    return {
        "status": "success",
        "meta": {
            "source": "yfinance",
            "ticker": ticker,
            "statement": statement_type,
            "currency": currency,
            "basis": "not stated by source",
            "periods": len(periods),
        },
        "data": periods,
    }


class YFinanceConnector(SourceConnector):
    provider_name = "yfinance"

    def __init__(self) -> None:
        self._currency_cache: dict[str, str | None] = {}

    def _financial_currency(self, ticker_obj, ticker: str) -> str | None:
        if ticker not in self._currency_cache:
            try:
                self._currency_cache[ticker] = ticker_obj.info.get("financialCurrency")
            except Exception:
                self._currency_cache[ticker] = None
        return self._currency_cache[ticker]

    def fetch_statement(self, ticker: str, statement_type: str) -> RawSourceResponse:
        import yfinance as yf

        endpoint = f"yfinance:{statement_type}"
        params = {"ticker": ticker, "statement": statement_type}
        fetched_at = dt.datetime.now(dt.timezone.utc)
        try:
            ticker_obj = yf.Ticker(ticker)
            frame = getattr(ticker_obj, _STATEMENT_ATTR[statement_type])
            currency = self._financial_currency(ticker_obj, ticker)
        except Exception as exc:
            return RawSourceResponse(
                provider=self.provider_name, endpoint=endpoint, request_params=params,
                status_code=0, payload={}, fetched_at=fetched_at,
                parse_error=f"{type(exc).__name__}: {exc}",
            )

        if frame is None or frame.empty:
            return RawSourceResponse(
                provider=self.provider_name, endpoint=endpoint, request_params=params,
                status_code=404, payload={}, fetched_at=fetched_at,
                parse_error=f"yfinance returned no {statement_type} data for {ticker}",
            )

        return RawSourceResponse(
            provider=self.provider_name,
            endpoint=endpoint,
            request_params=params,
            status_code=200,
            payload=frame_to_payload(frame, ticker, statement_type, currency),
            fetched_at=fetched_at,
        )

    # --- SourceConnector interface -----------------------------------------
    def search_company(self, query: str) -> RawSourceResponse:
        raise NotImplementedError("yfinance connector does not support company search")

    def fetch_financials(self, sc_id: str, statement_type: StatementType, basis: Basis) -> RawSourceResponse:
        """`sc_id` is the Yahoo ticker (e.g. TCS.NS). `basis` is ignored: Yahoo
        does not let you choose standalone vs consolidated."""
        if statement_type not in _STATEMENT_ATTR:
            raise ValueError(f"yfinance connector does not support statement '{statement_type}'")
        return self.fetch_statement(sc_id, statement_type)

    def fetch_shareholding(self, sc_id: str) -> RawSourceResponse:
        raise NotImplementedError("yfinance connector does not support shareholding")


def fetch_prices(ticker: str, years: int = 5) -> RawSourceResponse:
    """Daily OHLCV (split/bonus adjusted by Yahoo) as one raw response.

    Same unofficial, provisional status as the statements. One request per
    ticker; callers store it as a snapshot and never call twice for the same day.
    """
    import yfinance as yf

    endpoint = "yfinance:prices"
    params = {"ticker": ticker, "years": years, "auto_adjust": True}
    fetched_at = dt.datetime.now(dt.timezone.utc)
    try:
        frame = yf.Ticker(ticker).history(period=f"{years}y", interval="1d", auto_adjust=True)
    except Exception as exc:
        return RawSourceResponse(
            provider="yfinance", endpoint=endpoint, request_params=params, status_code=0,
            payload={}, fetched_at=fetched_at, parse_error=f"{type(exc).__name__}: {exc}",
        )
    if frame is None or frame.empty:
        return RawSourceResponse(
            provider="yfinance", endpoint=endpoint, request_params=params, status_code=404,
            payload={}, fetched_at=fetched_at, parse_error=f"yfinance returned no prices for {ticker}",
        )
    rows = [
        {
            "date": idx.date().isoformat(),
            "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]),
            "close": float(r["Close"]), "volume": int(r["Volume"]),
        }
        for idx, r in frame.iterrows()
    ]
    return RawSourceResponse(
        provider="yfinance", endpoint=endpoint, request_params=params, status_code=200,
        payload={"status": "success", "meta": {"source": "yfinance", "ticker": ticker,
                 "adjusted": "splits and bonus (Yahoo auto_adjust)", "rows": len(rows)},
                 "data": rows},
        fetched_at=fetched_at,
    )
