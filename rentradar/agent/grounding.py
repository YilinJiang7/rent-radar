"""Grounding check: every number in the agent's answer must come from a tool result.

We extract numeric tokens from the final answer ("$2,450", "12 min", "3.5",
"02134") and look for each in the set of numbers that appeared anywhere in
the tool outputs of this conversation. Small integers (0-10) and numbers that
were in the user's own question are allowed, because they are usually
counts/ranks ("top 3") or echo the request ("under 2500").

This is the metric behind the proposal's success criterion
"0 made-up numbers in 20 agent tests" (eval/run_eval.py).
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Set

NUM_RE = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")
ID_RE = re.compile(r"\[[^\]]*\]")


def _norm(int_part: str, frac: str = None) -> str:
    s = int_part.replace(",", "")
    if frac and set(frac) != {"0"}:
        return f"{int(s)}.{frac.rstrip('0')}"
    return str(int(s))


def numbers_in_text(text: str) -> List[str]:
    text = ID_RE.sub(" ", text or "")  # citations like [L:6-Wait-St...] / [R:123] are ids, not claims
    return [_norm(m.group(1), m.group(2)) for m in NUM_RE.finditer(text)]


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
        f = float(obj)
        if f.is_integer():
            out.add(str(int(f)))
        else:
            # the value itself plus natural roundings (61.34 -> 61.3, 61)
            for nd in (2, 1):
                ip, _, fp = f"{round(f, nd):.{nd}f}".partition(".")
                out.add(_norm(ip, fp))
            out.add(str(int(round(f))))
    elif isinstance(obj, str):
        for n in numbers_in_text(obj):
            out.add(n)


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
