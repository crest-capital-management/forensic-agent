from crest_forensic.text.extractors import GeminiExtractor
from crest_forensic.text.tasks import TASKS


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Client:
    def __init__(self, data):
        self.data, self.sent = data, None

    def post(self, url, json, headers):
        self.sent = (url, json)
        return _Resp(self.data)


def _ext(data):
    return GeminiExtractor(config={"gemini": {"model": "gemini-test"}}, client=_Client(data))


def test_parses_findings_and_usage():
    data = {"candidates": [{"content": {"parts": [{"text": '{"findings": [{"finding_type": "x", "exact_quote": "q", "page": 3, "confidence": "high"}]}'}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2}}
    ext = _ext(data)
    out = ext.extract(TASKS["J1-10"], "standalone", "FY2026", {3: "text"})
    assert out.response["findings"][0]["page"] == 3
    assert (out.model, out.input_tokens, out.output_tokens) == ("gemini-test", 10, 2)
    assert "additionalProperties" not in str(ext._client.sent[1]["generationConfig"]["responseSchema"])


def test_blocked_truncated_or_malformed_raises():
    import pytest
    for data in ({"promptFeedback": {"blockReason": "SAFETY"}},
                 {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
                 {"candidates": [{"content": {}, "finishReason": "MAX_TOKENS"}]}):
        with pytest.raises(RuntimeError):
            _ext(data).extract(TASKS["J1-10"], "standalone", "FY2026", {1: "t"})
