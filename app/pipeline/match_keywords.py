"""Match job title/JD text against the curated keyword taxonomy.

This is deliberately NOT a general-purpose NLP keyword extractor. It only
ever returns terms from config/keyword_taxonomy.yaml — a fixed vocabulary
of languages, frameworks, domains, etc. — so the downstream Job
Application Service can compute a profile-match score via simple set
overlap against a candidate's own keyword list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "keyword_taxonomy.yaml"


@dataclass(frozen=True)
class _CompiledTerm:
    canonical: str
    pattern: re.Pattern[str]


def _compile_term(canonical: str, aliases: list[str], case_sensitive: bool) -> _CompiledTerm:
    variants = {canonical, *aliases}
    branches = (rf"(?<![A-Za-z0-9]){re.escape(v.strip())}(?![A-Za-z0-9])" for v in variants)
    flags = 0 if case_sensitive else re.IGNORECASE
    return _CompiledTerm(canonical=canonical, pattern=re.compile("|".join(branches), flags))


@lru_cache(maxsize=1)
def _load_compiled_terms() -> tuple[_CompiledTerm, ...]:
    data = yaml.safe_load(_TAXONOMY_PATH.read_text())
    case_sensitive_terms = set(data.pop("case_sensitive_terms", []))

    compiled: list[_CompiledTerm] = []
    for category_terms in data.values():
        for canonical, aliases in category_terms.items():
            compiled.append(
                _compile_term(canonical, aliases, case_sensitive=canonical in case_sensitive_terms)
            )
    return tuple(compiled)


def match_keywords(*texts: str | None) -> list[str]:
    """Return the sorted list of canonical taxonomy terms found in `texts`."""
    haystack = "\n".join(t for t in texts if t)
    if not haystack:
        return []

    matched = {term.canonical for term in _load_compiled_terms() if term.pattern.search(haystack)}
    return sorted(matched)
