"""Readers that turn raw downloads into clean row dicts.

Each reader is a pure function: path(s) in, list of dicts out. They never touch
the database, which keeps them easy to unit-test with small fixtures.
"""
from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence


class SchemaError(ValueError):
    """Raised when a raw file lacks a required column; message lists what we saw."""


def open_text(path: Path):
    path = Path(path)
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8-sig", newline="")
    return open(path, encoding="utf-8-sig", newline="")


def read_csv(path: Path) -> Iterator[Dict[str, str]]:
    csv.field_size_limit(10_000_000)
    with open_text(path) as fh:
        yield from csv.DictReader(fh)


def resolve(columns: Sequence[str], aliases: Dict[str, List[str]], required: Sequence[str], source: str) -> Dict[str, Optional[str]]:
    """Map logical names -> actual column names, case/space-insensitive.

    Open-data portals rename columns between releases (e.g. `zip_code` vs
    `ZIP_CODE` vs `zip`), so every reader declares aliases instead of hard
    coding one spelling.
    """
    canon = {c.strip().lower().replace(" ", "_"): c for c in columns}
    out: Dict[str, Optional[str]] = {}
    for logical, names in aliases.items():
        out[logical] = None
        for n in [logical] + names:
            key = n.lower().replace(" ", "_")
            if key in canon:
                out[logical] = canon[key]
                break
    missing = [r for r in required if out.get(r) is None]
    if missing:
        raise SchemaError(
            f"{source}: missing required column(s) {missing}. Columns found: {list(columns)}. "
            f"Add the right spelling to the alias list in rentradar/ingest/."
        )
    return out


def to_float(v) -> Optional[float]:
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def to_int(v) -> Optional[int]:
    f = to_float(v)
    return int(f) if f is not None else None
