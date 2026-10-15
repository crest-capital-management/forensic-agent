import httpx
import pytest
import respx

from crest_forensic.connectors.rapidapi_moneycontrol import RapidApiMoneyControlConnector

_BASE = "https://india-stock-market-moneycontrol-live-api.p.rapidapi.com/api/moneycontrol"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    with pytest.raises(RuntimeError):
        RapidApiMoneyControlConnector(api_key=None)


@respx.mock
def test_fetch_financials_sends_expected_headers_and_params():
    route = respx.get(f"{_BASE}/stocks/financials/income").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {}})
    )
    connector = RapidApiMoneyControlConnector(api_key="test-key")
    response = connector.fetch_financials("TCS", "income", "standalone")

    assert route.called
    sent = route.calls.last.request
    assert sent.headers["x-rapidapi-key"] == "test-key"
    assert sent.headers["x-rapidapi-host"] == "india-stock-market-moneycontrol-live-api.p.rapidapi.com"
    assert "sc_id=TCS" in str(sent.url)
    assert "type=standalone" in str(sent.url)
    assert response.status_code == 200
    assert response.payload == {"status": "success", "data": {}}


@respx.mock
def test_ratios_endpoint_has_no_type_param():
    respx.get(f"{_BASE}/stocks/financials/ratios").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {}})
    )
    connector = RapidApiMoneyControlConnector(api_key="test-key")
    response = connector.fetch_financials("TCS", "ratios", "standalone")
    assert "type" not in response.request_params


@respx.mock
def test_non_json_response_is_captured_as_parse_error():
    respx.get(f"{_BASE}/stocks/financials/income").mock(
        return_value=httpx.Response(502, text="<html>Bad Gateway</html>")
    )
    connector = RapidApiMoneyControlConnector(api_key="test-key")
    response = connector.fetch_financials("TCS", "income", "standalone")

    assert response.status_code == 502
    assert response.parse_error is not None
    assert response.raw_text == "<html>Bad Gateway</html>"
