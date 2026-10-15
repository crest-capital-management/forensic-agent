"""Extractors: the only place a model is called.

Every extractor returns the same thing: a dict {"findings": [...]} plus the
model label and token counts. What it returns is UNTRUSTED; text/run.py
validates each finding in code before anything is stored as usable.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from crest_forensic.text.tasks import SYSTEM_PROMPT, TextTask, build_user_message, tool_schema

LLM_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "llm.yaml"


@dataclass
class RawExtraction:
    response: dict            # {"findings": [...]} as returned, untouched
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def load_llm_config(path: str | Path = LLM_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class ClaudeExtractor:
    """Calls the Anthropic API with the pinned model and a forced structured-output tool."""

    def __init__(self, config: dict | None = None, client=None) -> None:
        self.config = config or load_llm_config()
        self.model_label = self.config["model"]
        if client is None:
            import anthropic
            from dotenv import load_dotenv

            load_dotenv()
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your environment or .env file.")
            client = anthropic.Anthropic()
        self._client = client

    def extract(self, task: TextTask, basis: str, fiscal_year: str, pages: dict[int, str]) -> RawExtraction:
        kwargs = dict(
            model=self.config["model"], max_tokens=self.config["max_tokens"], system=SYSTEM_PROMPT,
            tools=[{"name": "report_findings",
                    "description": "Report the passages found. Report nothing if no passage matches.",
                    "input_schema": tool_schema(list(task.finding_types))}],
            tool_choice={"type": "tool", "name": "report_findings"},
            messages=[{"role": "user", "content": build_user_message(task, basis, fiscal_year, pages)}],
        )
        try:
            message = self._client.messages.create(temperature=self.config.get("temperature", 0), **kwargs)
        except Exception as exc:  # some models reject an explicit temperature
            if "temperature" not in str(exc).lower():
                raise
            message = self._client.messages.create(**kwargs)

        block = next((b for b in message.content if getattr(b, "type", "") == "tool_use"), None)
        response = dict(block.input) if block is not None else {"findings": []}
        usage = getattr(message, "usage", None)
        return RawExtraction(response, self.config["model"],
                             getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))


class GeminiExtractor:
    """Calls the Google Gemini REST API with JSON-schema constrained output.

    Used for development while no Anthropic key is available. The response is
    UNTRUSTED exactly like Claude's: text/run.py validates every quote in code.
    """

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, config: dict | None = None, client=None) -> None:
        cfg = config or load_llm_config()
        self.config = cfg.get("gemini", {})
        self.model_label = self.config.get("model", "gemini-3.8-flash")
        self._key = None
        if client is None:
            import httpx
            from dotenv import load_dotenv

            load_dotenv()
            self._key = os.environ.get("GEMINI_API_KEY1") or os.environ.get("GEMINI_API_KEY")
            if not self._key:
                raise RuntimeError("GEMINI_API_KEY is not set. Add it to your environment or .env file.")
            client = httpx.Client(timeout=180)
        self._client = client

    @staticmethod
    def _gemini_schema(schema: dict) -> dict:
        """Gemini's schema dialect has no additionalProperties."""
        if isinstance(schema, dict):
            return {k: GeminiExtractor._gemini_schema(v) for k, v in schema.items() if k != "additionalProperties"}
        if isinstance(schema, list):
            return [GeminiExtractor._gemini_schema(v) for v in schema]
        return schema

    def extract(self, task: TextTask, basis: str, fiscal_year: str, pages: dict[int, str]) -> RawExtraction:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": build_user_message(task, basis, fiscal_year, pages)}]}],
            "generationConfig": {
                "temperature": self.config.get("temperature", 0),
                "maxOutputTokens": self.config.get("max_tokens", 8192),
                "responseMimeType": "application/json",
                "responseSchema": self._gemini_schema(tool_schema(list(task.finding_types))),
            },
        }
        # 5xx is usually momentary overload, but every refused try may still count against the free daily quota, so keep tries few
        # (llm.yaml gemini.max_attempts, default 2). 429 is a quota: never retried.
        attempts = max(1, int(self.config.get("max_attempts", 2)))
        for attempt in range(attempts):
            try:
                resp = self._client.post(self.URL.format(model=self.model_label), json=body,
                                         headers={"x-goog-api-key": self._key or ""})
            except Exception as exc:   # dropped connection / timeout: retry, then give up
                if "httpx" not in type(exc).__module__ or attempt == attempts - 1:
                    raise
                time.sleep(self.config.get("retry_wait_seconds", 10) * (attempt + 1))
                continue
            if resp.status_code not in (500, 502, 503, 504) or attempt == attempts - 1:
                break
            time.sleep(self.config.get("retry_wait_seconds", 10) * (attempt + 1))
        if resp.status_code == 429:
            raise RuntimeError("Gemini quota exhausted (HTTP 429): " + resp.text[:300].replace(chr(10), " "))
        resp.raise_for_status()
        data = resp.json()
        cand = (data.get("candidates") or [{}])[0]
        reason = cand.get("finishReason")
        # An empty or cut-off reply is an error, never "nothing found": a silent pass would look like a clean report.
        if reason not in (None, "STOP"):
            raise RuntimeError(f"Gemini did not finish cleanly (finishReason={reason}); raise max_tokens or retry.")
        try:
            text = "".join(p.get("text", "") for p in cand["content"]["parts"])
            response = json.loads(text)
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"Gemini returned no usable JSON (blocked or malformed): {data.get('promptFeedback', '')}") from exc
        if not isinstance(response, dict):
            raise RuntimeError("Gemini returned JSON that is not an object.")
        usage = data.get("usageMetadata", {})
        return RawExtraction(response, self.model_label,
                             usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))


class FunctionExtractor:
    """Wraps a function(task, basis, fiscal_year, pages) -> dict. Used in tests."""

    def __init__(self, fn: Callable[..., dict], model_label: str = "test-function-extractor") -> None:
        self.fn, self.model_label = fn, model_label

    def extract(self, task: TextTask, basis: str, fiscal_year: str, pages: dict[int, str]) -> RawExtraction:
        return RawExtraction(self.fn(task, basis, fiscal_year, pages), self.model_label)


class RecordedExtractor:
    """Replays findings saved in a JSON file, keyed 'J1-10:standalone:FY2026'.

    For running the pipeline without an API key, e.g. findings that Claude Code
    produced by reading the pages in a session. The model label says so, and the
    findings go through exactly the same code validation as a live call.
    """

    def __init__(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.model_label = data.get("extractor_label", "recorded")
        self._responses = data["responses"]

    def extract(self, task: TextTask, basis: str, fiscal_year: str, pages: dict[int, str]) -> RawExtraction:
        key = f"{task.check_id}:{basis}:{fiscal_year}"
        if key not in self._responses:
            raise KeyError(f"no recorded response for {key}")
        return RawExtraction(self._responses[key], self.model_label)
