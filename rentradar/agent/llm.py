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

    def generate(self, system: str, contents: List[dict], tools: List[dict], force_text: bool = False) -> dict:
        """Return the model `content` dict: {"role": "model", "parts": [...]}"""


RETRYABLE = {429, 500, 502, 503, 504}


class GeminiModel:
    """Gemini over REST, with retry/backoff on overload (429/5xx) and backup models.

    GEMINI_MODEL is tried first; GEMINI_FALLBACK_MODELS (comma-separated) are used
    when it stays overloaded. Only if all fail does the agent drop to offline mode.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: float = 60.0,
                 fallbacks: Optional[List[str]] = None, client: Optional[httpx.Client] = None,
                 retries: int = 2, sleep=None):
        import time
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        primary = model or config.GEMINI_MODEL
        if fallbacks is None:
            fallbacks = [m.strip() for m in config.GEMINI_FALLBACK_MODELS.split(",") if m.strip()]
        self.models = [primary] + [m for m in fallbacks if m != primary]
        self.idx = 0
        self.client = client or httpx.Client(timeout=timeout)
        self.retries = retries
        self.sleep = sleep or time.sleep
        self.usage = {"prompt_tokens": 0, "output_tokens": 0, "calls": 0, "retries": 0, "model_switches": 0}

    @property
    def model(self) -> str:
        return self.models[self.idx]

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def generate(self, system: str, contents: List[dict], tools: List[dict], force_text: bool = False) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.2},
        }
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
            if force_text:  # keep declarations (history has calls) but forbid new ones
                body["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
        last = None
        while True:
            for attempt in range(self.retries + 1):
                try:
                    r = self.client.post(API_URL.format(model=self.model), json=body,
                                         headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
                except httpx.HTTPError as e:  # network hiccup: treat like an overload
                    last = f"network error: {e}"
                    r = None
                if r is not None and r.status_code == 200:
                    break
                if r is not None and r.status_code not in RETRYABLE:
                    raise LLMError(f"Gemini HTTP {r.status_code} ({self.model}): {r.text[:300]}")
                if r is not None:
                    last = f"Gemini HTTP {r.status_code} ({self.model}): {r.text[:200]}"
                if attempt < self.retries:
                    self.usage["retries"] += 1
                    wait = 1.5 * (2 ** attempt)
                    if r is not None and r.headers.get("retry-after", "").isdigit():
                        wait = min(10.0, float(r.headers["retry-after"]))
                    self.sleep(wait)
            else:
                # still overloaded: move to the next model, if any
                if self.idx + 1 < len(self.models):
                    self.idx += 1
                    self.usage["model_switches"] += 1
                    continue
                raise LLMError(last or "Gemini unavailable")
            break
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

    def generate(self, system: str, contents: List[dict], tools: List[dict], force_text: bool = False) -> dict:
        self.forced = getattr(self, "forced", []) + [force_text]
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
