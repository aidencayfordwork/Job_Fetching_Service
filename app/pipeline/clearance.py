"""Active security-clearance detection (architecture.md §2C).

Only flags a job when it requires an ALREADY ACTIVE/current clearance.
Explicitly does NOT flag "ability to obtain", "eligible to obtain",
"public trust", "background check", or "citizenship required" language —
those are allowed per spec.
"""

from __future__ import annotations

import re

# Checked first: if any of these "already obtainable" phrases appear
# immediately around a clearance mention, it's not an active-clearance
# requirement even if the word "active" appears elsewhere in the JD.
_ALLOWED_NEARBY_RE = re.compile(
    r"(ability|eligib\w*|able)\s+to\s+(obtain|acquire)", re.IGNORECASE
)

_ACTIVE_CLEARANCE_RE = re.compile(
    r"""
    (?:active|current(?:ly)?|existing|hold(?:ing)?|possess(?:ing)?)
    \s+
    (?:a\s+|an\s+)?
    (?:
        (?:dod\s+)?security\s+clearance |
        secret\s+clearance |
        top\s+secret(?:\s*/?\s*sci)? |
        ts\s*/\s*sci |
        clearance
    )
    |
    must\s+(?:currently\s+)?(?:hold|possess)\s+(?:a\s+|an\s+)?(?:active\s+|current\s+)?
    (?:security\s+clearance|secret\s+clearance|top\s+secret|ts\s*/\s*sci|clearance)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def requires_active_clearance(text: str | None) -> bool:
    if not text:
        return False

    for match in _ACTIVE_CLEARANCE_RE.finditer(text):
        window = text[max(0, match.start() - 40) : match.end() + 10]
        if _ALLOWED_NEARBY_RE.search(window):
            continue
        return True

    return False
