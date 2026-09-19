"""Match job title/JD text against the curated keyword taxonomy.

This is deliberately NOT a general-purpose NLP keyword extractor. It only
ever returns terms from config/keyword_taxonomy.yaml — a fixed vocabulary
of languages, frameworks, domains, etc. — so the downstream Job
Application Service can compute a profile-match score via simple set
overlap against a candidate's own keyword list.

`classify_stack.py` reuses `match_terms_by_category()` from this module
instead of maintaining a second technology dictionary.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "keyword_taxonomy.yaml"


@dataclass(frozen=True)
class _CompiledTerm:
    canonical: str
    category: str
    pattern: re.Pattern[str]


def _compile_term(canonical: str, category: str, aliases: list[str], case_sensitive: bool) -> _CompiledTerm:
    # Case-sensitivity applies only to the short ambiguous canonical token
    # itself ("Go", "R", "C"); its aliases ("golang", "r language") are
    # unambiguous and must match in any casing, e.g. "Golang".
    def _branch(variant: str, sensitive: bool) -> str:
        # "+"/"#" in the lookahead stop "C" matching inside "C++" / "C#".
        body = rf"(?<![A-Za-z0-9]){re.escape(variant.strip())}(?![A-Za-z0-9+#])"
        return body if sensitive else f"(?i:{body})"

    branches = [_branch(canonical, case_sensitive)]
    branches.extend(_branch(alias, False) for alias in aliases if alias != canonical)
    return _CompiledTerm(canonical=canonical, category=category, pattern=re.compile("|".join(branches)))


@lru_cache(maxsize=1)
def _load_compiled_terms() -> tuple[_CompiledTerm, ...]:
    data = yaml.safe_load(_TAXONOMY_PATH.read_text())
    case_sensitive_terms = set(data.pop("case_sensitive_terms", []))

    compiled: list[_CompiledTerm] = []
    for category, category_terms in data.items():
        for canonical, aliases in category_terms.items():
            compiled.append(
                _compile_term(
                    canonical, category, aliases, case_sensitive=canonical in case_sensitive_terms
                )
            )
    return tuple(compiled)


def match_terms_by_category(*texts: str | None) -> dict[str, list[str]]:
    """Return {category: [canonical terms found]} for every taxonomy category."""
    haystack = "\n".join(t for t in texts if t)
    if not haystack:
        return {}

    found: dict[str, set[str]] = defaultdict(set)
    for term in _load_compiled_terms():
        if term.pattern.search(haystack):
            found[term.category].add(term.canonical)

    return {category: sorted(terms) for category, terms in found.items()}


def match_keywords(*texts: str | None) -> list[str]:
    """Return the sorted list of canonical taxonomy terms found in `texts`,
    across every category (used for jobs.matched_keywords)."""
    by_category = match_terms_by_category(*texts)
    flattened = {term for terms in by_category.values() for term in terms}
    return sorted(flattened)


@lru_cache(maxsize=1)
def taxonomy_terms() -> dict[str, tuple[str, tuple[str, ...]]]:
    """{canonical: (category, aliases)} for every taxonomy term."""
    data = yaml.safe_load(_TAXONOMY_PATH.read_text())
    data.pop("case_sensitive_terms", None)
    return {
        canonical: (category, tuple(aliases))
        for category, category_terms in data.items()
        for canonical, aliases in category_terms.items()
    }


def term_patterns() -> dict[str, re.Pattern[str]]:
    """{canonical: compiled pattern}, with the same matching rules as match_keywords()."""
    return {term.canonical: term.pattern for term in _load_compiled_terms()}
