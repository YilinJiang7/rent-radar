"""Minimal Gemini client (REST, function calling) + a scripted fake for tests.

We call the REST endpoint directly with httpx instead of an SDK so the
request/response shapes are visible in one file:

POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
header  x-goog-api-key: $GEMINI_API_KEY
body    {systemInstruction, contents[], tools[{functionDeclarations}], generationConfig}

The model's reply is echoed back into `contents` unchanged (it may carry
thought signatures that newer models require), followed by a user turn with
one `functionResponse` part per function call.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Protocol

import httpx

from .. import config

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    pass


class ChatModel(Protocol):
    name: str

    def generate(self, system: str, contents: List[dict], tools: List[dict]) -> dict:
        """Return the model `content` dict: {"role": "model", "parts": [...]}"""


class GeminiModel:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: float = 60.0):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.model = model or config.GEMINI_MODEL
        self.name = f"gemini:{self.model}"
        self.client = httpx.Client(timeout=timeout)
        self.usage = {"prompt_tokens": 0, "output_tokens": 0, "calls": 0}

    def generate(self, system: str, contents: List[dict], tools: List[dict]) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": [{"functionDeclarations": tools}] if tools else [],
            "generationConfig": {"temperature": 0.2},
        }
        r = self.client.post(API_URL.format(model=self.model), json=body,
                             headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        if r.status_code != 200:
            raise LLMError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        um = data.get("usageMetadata") or {}
        self.usage["prompt_tokens"] += um.get("promptTokenCount", 0)
        self.usage["output_tokens"] += um.get("candidatesTokenCount", 0)
        self.usage["calls"] += 1
        cands = data.get("candidates") or []
        if not cands or "content" not in cands[0]:
            raise LLMError(f"Gemini returned no content: {str(data)[:300]}")
        content = cands[0]["content"]
        content.setdefault("role", "model")
        return content


class ScriptedModel:
    """Deterministic stand-in for tests: replays a list of model turns.

    Each turn is either {"call": name, "args": {...}} / a list of those, or
    {"text": "..."}; a callable gets (contents) and returns such a turn.
    """

    def __init__(self, turns: List[Any]):
        self.turns = list(turns)
        self.name = "scripted"
        self.seen: List[List[dict]] = []
        self.usage = {"calls": 0}

    def generate(self, system: str, contents: List[dict], tools: List[dict]) -> dict:
        self.seen.append([dict(c) for c in contents])
        self.usage["calls"] += 1
        if not self.turns:
            return {"role": "model", "parts": [{"text": "(no more scripted turns)"}]}
        t = self.turns.pop(0)
        if callable(t):
            t = t(contents)
        calls = t if isinstance(t, list) else [t]
        parts = []
        for c in calls:
            if "call" in c:
                parts.append({"functionCall": {"name": c["call"], "args": c.get("args", {})}})
            else:
                parts.append({"text": c["text"]})
        return {"role": "model", "parts": parts}


def default_model() -> Optional[ChatModel]:
    try:
        return GeminiModel()
    except LLMError:
        return None
