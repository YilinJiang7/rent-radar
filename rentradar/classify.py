"""Optional LLM pass: label RentSmart descriptions with renter signals.

    python -m rentradar.classify            # needs GEMINI_API_KEY and a built DB
    python -m rentradar.build               # re-build to apply the labels

RentSmart has many rows but far fewer *distinct* descriptions, so we label
each distinct description once (batches of 40, JSON output) and cache the
result in data/signal_labels_llm.json. The build uses an LLM label only where
the keyword rules said "other"; rule labels stay the transparent default.
eval/signal_agreement.py compares both against hand labels.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import httpx

from . import config, db, signals

CACHE = config.DATA_DIR / "signal_labels_llm.json"
PROMPT = """Classify each Boston 311 / inspection record description into exactly one renter signal.
Signals (key: meaning):
{signals}
Return a JSON object mapping each input number to a signal key. Inputs:
{items}"""


def load_cache() -> Dict[str, str]:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def classify_batch(descs: List[str], api_key: str, model: str) -> Dict[str, str]:
    sig_text = "\n".join(f"- {k}: {v}" for k, v in signals.SIGNALS.items())
    items = "\n".join(f"{i}. {d}" for i, d in enumerate(descs))
    body = {
        "contents": [{"role": "user", "parts": [{"text": PROMPT.format(signals=sig_text, items=items)}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = httpx.post(url, json=body, headers={"x-goog-api-key": api_key}, timeout=120)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    out = json.loads(text)
    res = {}
    for i, d in enumerate(descs):
        lab = out.get(str(i))
        res[d] = lab if lab in signals.SIGNALS else "other"
    return res


def main(argv=None):
    try:
        from dotenv import load_dotenv
        load_dotenv(config.ROOT / ".env")
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000, help="max distinct descriptions to label")
    ap.add_argument("--batch", type=int, default=40)
    a = ap.parse_args(argv)
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not set (see README: 'Gemini API key').")
    conn = db.connect()
    rows = conn.execute(
        "SELECT description, COUNT(*) n FROM city_records WHERE description != '' GROUP BY description ORDER BY n DESC"
    ).fetchall()
    cache = load_cache()
    todo = [r["description"] for r in rows if r["description"] not in cache][: a.limit]
    print(f"{len(rows)} distinct descriptions, {len(cache)} cached, labelling {len(todo)}")
    for i in range(0, len(todo), a.batch):
        chunk = todo[i:i + a.batch]
        cache.update(classify_batch(chunk, key, config.GEMINI_MODEL))
        CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
        print(f"  {min(i + a.batch, len(todo))}/{len(todo)}")
    print(f"saved {CACHE}. Re-run `python -m rentradar.build` to apply.")


if __name__ == "__main__":
    main()
