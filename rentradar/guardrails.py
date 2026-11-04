"""Fair Housing guardrail.

The US Fair Housing Act (and Massachusetts G.L. c.151B, which adds more
protected classes, e.g. source of income, age, marital status) forbids
steering by protected characteristics. Rent Radar never stores or scores
demographics; this module catches requests that ask it to, and answers with a
redirect to the objective layers we *do* have.

Keyword rules are deliberately conservative: a false positive costs one
polite redirect, a false negative could mean the agent steering people.
"""
from __future__ import annotations

import re
from typing import Optional

PROTECTED = [
    r"\b(white|black|asian|hispanic|latin[oax]|arab|jewish|muslim|christian|hindu|immigrant|foreigner|chinese|indian|korean|african)s?\b.{0,30}\b(neighbou?rhood|area|people|families|residents|tenants|neighbou?rs|community|block|street)",
    r"\b(neighbou?rhood|area|people|residents|tenants|neighbou?rs|community|block)s?\b.{0,30}\b(white|black|asian|hispanic|latin[oax]|arab|jewish|muslim|christian|immigrant|foreigner)s?\b",
    r"\b(no|without|avoid|fewer|less|not many|away from)\s+(kids|children|families|immigrants|foreigners|section 8|voucher|disabled|minorit(y|ies)|old people|elderly)\b",
    r"\b(race|racial|ethnic(ity)?|religio(n|us)|national origin|demographic)s?\b",
    r"\b(good|bad|safe|sketchy|dangerous)\s+(people|crowd|element)\b",
]
PROTECTED_RE = [re.compile(p, re.I) for p in PROTECTED]

REDIRECT = (
    "I can't rank or describe places by who lives there (race, religion, national origin, family "
    "status, disability, source of income and other protected traits) -- that is housing "
    "steering under the Fair Housing Act and Massachusetts law. I can rank by things that are "
    "about the building and street: city complaints and violations at the address, the owner's "
    "record, crash history, traffic noise, commute and price. Tell me which of those matter to you."
)

SAFETY_NOTE = (
    "Note: \"safe\" here means street-crash history and building safety records only. Rent Radar "
    "does not use crime data or any information about residents."
)


def check(query: str) -> Optional[str]:
    """Return a refusal/redirect message if the query asks for steering, else None."""
    for rx in PROTECTED_RE:
        if rx.search(query or ""):
            return REDIRECT
    return None


def mentions_safety(query: str) -> bool:
    return bool(re.search(r"\b(safe|safety|unsafe|dangerous)\b", query or "", re.I))
