"""Model adapters for the agent: one neutral conversation format, three back ends.

Neutral messages:
  {"role": "user", "text": str}
  {"role": "assistant", "text": str, "tool_calls": [{"id", "name", "args"}], "raw": back-end specific}
  {"role": "tool", "results": [{"id", "name", "result": dict}]}
Each adapter turns that into its provider's format and returns an AgentTurn. What a model says is
UNTRUSTED: agent/loop.py checks it in code before anyone sees it.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable


class QuotaExhausted(RuntimeError):
    pass


@dataclass
class AgentTurn:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    raw: object = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ClaudeAgentModel:
    def __init__(self, config: dict, client=None) -> None:
        self.config = config
        self.model_label = config["model"]
        if client is None:
            import anthropic
            from dotenv import load_dotenv

            load_dotenv()
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set.")
            client = anthropic.Anthropic()
        self._client = client

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> AgentTurn:
        msgs = []
        for m in messages:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                blocks = ([{"type": "text", "text": m["text"]}] if m.get("text") else []) + [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m.get("tool_calls", [])]
                msgs.append({"role": "assistant", "content": blocks})
            else:
                msgs.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": json.dumps(r["result"], default=str)}
                    for r in m["results"]]})
        resp = self._client.messages.create(
            model=self.config["model"], max_tokens=self.config.get("max_tokens", 4096), system=system, messages=msgs,
            tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools])
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        calls = [{"id": b.id, "name": b.name, "args": dict(b.input)} for b in resp.content if getattr(b, "type", "") == "tool_use"]
        usage = getattr(resp, "usage", None)
        return AgentTurn(text, calls, None, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))


class GeminiAgentModel:
    """Development model. Echoes the model's own parts back unchanged on the next call, as Gemini 3 requires."""

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, config: dict, client=None) -> None:
        self.config = config
        self.model_label = config.get("model", "gemini-3.6-flash")
        self._key = None
        if client is None:
            import httpx
            from dotenv import load_dotenv

            load_dotenv()
            self._key = os.environ.get("GEMINI_API_KEY1") or os.environ.get("GEMINI_API_KEY")
            if not self._key:
                raise RuntimeError("GEMINI_API_KEY is not set.")
            client = httpx.Client(timeout=180)
        self._client = client

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> AgentTurn:
        contents = []
        for m in messages:
            if m["role"] == "user":
                contents.append({"role": "user", "parts": [{"text": m["text"]}]})
            elif m["role"] == "assistant":
                contents.append({"role": "model", "parts": m.get("raw") or [{"text": m["text"]}]})
            else:
                contents.append({"role": "user", "parts": [
                    {"functionResponse": {"name": r["name"], "response": {"result": r["result"]}}} for r in m["results"]]})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "tools": [{"functionDeclarations": [{"name": t["name"], "description": t["description"],
                                                     "parameters": t["parameters"]} for t in tools]}],
                "generationConfig": {"temperature": self.config.get("temperature", 0),
                                     "maxOutputTokens": self.config.get("max_tokens", 16384)}}
        attempts = max(1, int(self.config.get("max_attempts", 2)))      # refused tries may count against the free quota: keep few
        for attempt in range(attempts):
            try:
                resp = self._client.post(self.URL.format(model=self.model_label), json=body,
                                         headers={"x-goog-api-key": self._key or ""})
            except Exception as exc:   # dropped connection: retry
                if "httpx" not in type(exc).__module__ or attempt == attempts - 1:
                    raise
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code not in (500, 502, 503, 504) or attempt == attempts - 1:
                break
            time.sleep(self.config.get("retry_wait_seconds", 8) * (attempt + 1))
        if resp.status_code == 429:
            raise QuotaExhausted("The Gemini free quota is used up for now (HTTP 429). Try again later.")
        resp.raise_for_status()
        data = resp.json()
        cand = (data.get("candidates") or [{}])[0]
        if cand.get("finishReason") not in (None, "STOP"):
            raise RuntimeError(f"Gemini did not finish cleanly (finishReason={cand.get('finishReason')}).")
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
        calls = [{"id": f"call{i}", "name": p["functionCall"]["name"], "args": dict(p["functionCall"].get("args") or {})}
                 for i, p in enumerate(parts) if "functionCall" in p]
        usage = data.get("usageMetadata", {})
        return AgentTurn(text, calls, parts, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))


class ScriptedAgentModel:
    """Tests: replays a list of AgentTurn (or callables returning one). Records what it was sent."""

    model_label = "scripted-test-model"

    def __init__(self, turns: list) -> None:
        self.turns, self.sent, self.tools_given = list(turns), [], []

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> AgentTurn:
        self.sent.append(json.loads(json.dumps(messages, default=str)))
        self.tools_given.append(len(tools))
        turn = self.turns.pop(0)
        return turn(messages) if isinstance(turn, Callable) else turn


def make_model(llm_config: dict):
    """provider auto = Claude if its key is set, else Gemini."""
    from dotenv import load_dotenv

    load_dotenv()
    agent_cfg = llm_config.get("agent", {})
    provider = agent_cfg.get("provider", "auto")
    if provider == "auto":
        provider = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "gemini"
    if provider == "claude":
        return ClaudeAgentModel({**llm_config, "max_tokens": agent_cfg.get("max_tokens", 4096)})
    return GeminiAgentModel({**llm_config.get("gemini", {}), "max_tokens": 16384})
