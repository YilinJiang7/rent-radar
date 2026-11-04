"""Address normalisation and matching.

The hard join in this project is "RentCast listing address" <-> "city record
address" (RentSmart, Property Assessment). Sources disagree on suffixes
("Street" vs "St"), units ("Apt 3", "# 727"), ranges ("12-14 Main St") and
zip formatting ("2134" vs "02134"). We reduce every address to

    AddressKey(street="WAIT ST", zip="02120", lo=6, hi=6)

and say two addresses match when street + zip are equal and the house numbers
overlap (ranges included).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SUFFIX = {
    "STREET": "ST", "STR": "ST", "AVENUE": "AVE", "AV": "AVE", "ROAD": "RD",
    "PLACE": "PL", "TERRACE": "TER", "TERR": "TER", "COURT": "CT", "SQUARE": "SQ",
    "BOULEVARD": "BLVD", "DRIVE": "DR", "LANE": "LN", "PARKWAY": "PKWY",
    "HIGHWAY": "HWY", "CIRCLE": "CIR", "PLAZA": "PLZ", "WHARF": "WHF",
    "ALLEY": "ALY", "EXTENSION": "EXT", "GARDENS": "GDNS", "HEIGHTS": "HTS",
    "POINT": "PT", "CRESCENT": "CRES", "PK": "PARK", "PRK": "PARK",
}
DIRECTION = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
UNIT_RE = re.compile(
    r"\b(APT|APARTMENT|UNIT|STE|SUITE|FL|FLOOR|RM|ROOM|BSMT|PH)\b\.?\s*[\w-]*|#\s*[\w-]+",
    re.I,
)
NUM_RE = re.compile(r"^\s*(\d+)([A-Z]?)(?:\s*-\s*(\d+)[A-Z]?)?\s+(.*)$", re.I)
ZIP_RE = re.compile(r"\b(\d{4,5})(?:-\d{4})?\s*$")


@dataclass(frozen=True)
class AddressKey:
    street: str
    zip: str
    lo: int
    hi: int

    @property
    def street_zip(self) -> str:
        return f"{self.street}|{self.zip}"

    def overlaps(self, other: "AddressKey") -> bool:
        return (
            self.street_zip == other.street_zip
            and self.lo <= other.hi
            and other.lo <= self.hi
        )


def norm_zip(z) -> str:
    if z is None:
        return ""
    s = re.sub(r"\D", "", str(z).split("-")[0].split(".")[0])
    return s.zfill(5) if s else ""


def norm_pid(pid) -> str:
    """Boston parcel ids are 10 digits; CSVs sometimes drop zeros or add '.0'."""
    if pid is None:
        return ""
    s = re.sub(r"\D", "", str(pid).split(".")[0])
    return s.zfill(10) if s else ""


def norm_street(name: str) -> str:
    s = name.upper()
    s = re.sub(r"[.,']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split(" ")
    out = []
    for i, w in enumerate(words):
        if w in DIRECTION and (i == 0 or i == len(words) - 1):
            out.append(DIRECTION[w])
        elif i == len(words) - 1 and w in SUFFIX:
            out.append(SUFFIX[w])
        else:
            out.append(w)
    return " ".join(out)


def parse(line1: str, zip_code=None) -> Optional[AddressKey]:
    """Parse '12-14 Main Street, Apt 3' (+ zip) into an AddressKey.

    The street line may also carry a trailing ', Boston, MA 02134' or ', 02134'
    (RentSmart format); a zip found there is used when zip_code is missing.
    """
    if not line1:
        return None
    text = str(line1).strip()
    parts = [p.strip() for p in text.split(",")]
    street_part = parts[0]
    z = norm_zip(zip_code)
    if not z:
        for p in reversed(parts[1:]):
            m = ZIP_RE.search(p)
            if m:
                z = norm_zip(m.group(1))
                break
    street_part = UNIT_RE.sub(" ", street_part)
    m = NUM_RE.match(street_part)
    if not m:
        return None
    lo = int(m.group(1))
    hi = int(m.group(3)) if m.group(3) else lo
    if hi < lo:
        lo, hi = hi, lo
    street = norm_street(m.group(4))
    if not street or not z:
        return None
    return AddressKey(street=street, zip=z, lo=lo, hi=hi)


def from_parts(st_num, st_name, zip_code, st_num2=None) -> Optional[AddressKey]:
    """Property-assessment style: ST_NUM, ST_NAME (+ optional ST_NUM2)."""
    if st_num is None or st_name is None:
        return None
    num = str(st_num).strip()
    if st_num2 not in (None, "", "nan") and str(st_num2).strip():
        num = f"{num}-{str(st_num2).strip()}"
    return parse(f"{num} {st_name}", zip_code)
