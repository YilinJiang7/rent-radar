"""Grounding check: every number in the agent's answer must come from a tool result.

We extract numeric tokens from the final answer ("$2,450", "12 min", "15min",
"3br", "$2.4k", "61.3") and look for each in the set of numbers that appeared
anywhere in the tool outputs of this conversation, plus the user's question.
Citations like [L:...] / [R:...] are ids, not claims, and are skipped.

Allowed without a source: 0-10 (ranks like "top 3", small counts in prose)
and 100 (the score scale). Known limitation: the check is per conversation,
not per listing -- a real number attached to the wrong listing still passes.
Rounding uses half-up, the way people round (72.5 -> 73).

This is the metric behind the proposal's success criterion
"0 made-up numbers in 20 agent tests" (eval/run_eval.py).
"""
from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, List, Set

# digits not glued to other digits/decimal points; may be followed by letters (15min, 3br, 2.4k)
NUM_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(k\b)?(?![\d])", re.I)
ID_RE = re.compile(r"\[[^\]]*\]")


def _canon(d: Decimal) -> str:
    d = d.normalize()
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def numbers_in_text(text: str) -> List[str]:
    text = ID_RE.sub(" ", text or "")
    out = []
    for m in NUM_RE.finditer(text):
        v = Decimal(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
        if m.group(3):  # "$2.4k" -> 2400
            v = v * 1000
        out.append(_canon(v))
    return out


def _add_number(x: float, out: Set[str]) -> None:
    d = Decimal(repr(float(x)))
    out.add(_canon(d))
    for q in ("1", "0.1", "0.01"):
        out.add(_canon(d.quantize(Decimal(q), rounding=ROUND_HALF_UP)))


def _walk(obj: Any, out: Set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        _add_number(obj, out)
    elif isinstance(obj, str):
        out.update(numbers_in_text(obj))


def allowed_numbers(tool_outputs: Iterable[Any], user_text: str = "") -> Set[str]:
    out: Set[str] = {str(i) for i in range(0, 11)} | {"100"}  # small counts + the 0-100 score scale
    for t in tool_outputs:
        _walk(t, out)
    out.update(numbers_in_text(user_text))
    return out


def check(answer: str, tool_outputs: Iterable[Any], user_text: str = "") -> dict:
    allowed = allowed_numbers(list(tool_outputs), user_text)
    found = numbers_in_text(answer)
    bad = sorted({n for n in found if n not in allowed}, key=lambda s: float(s))
    return {"numbers_checked": len(found), "ungrounded": bad, "ok": not bad}


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)
