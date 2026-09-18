"""Shared normalization helpers used by connector `normalize()` methods.

Pure functions only — no I/O, no business rules about what counts as a
match. Each connector calls into these instead of reimplementing HTML
cleanup / salary-text parsing on its own.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Some sources (e.g. RemoteOK) append an anti-spam instruction to every
# description ("Please mention the word X when applying..."). It's noise
# for classification/keyword-matching, so strip it out.
_SPAM_MARKER_RE = re.compile(
    r"Please mention the word.*?(?=$)", re.IGNORECASE | re.DOTALL
)


def clean_html(raw: str | None) -> str:
    """Best-effort HTML -> plain text. Handles both normal and
    double-HTML-escaped source content (some Greenhouse boards return
    `&lt;div&gt;` instead of `<div>`)."""
    if not raw:
        return ""

    text = html.unescape(raw)
    # A second unescape is a no-op unless the content was double-escaped.
    text = html.unescape(text)
    text = _SPAM_MARKER_RE.sub("", text)
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n").replace("</li>", "\n").replace("</div>", "\n")
    text = _TAG_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


@dataclass(frozen=True, slots=True)
class SalaryGuess:
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    salary_period: str | None = None
    original_salary_text: str | None = None


_SALARY_RANGE_RE = re.compile(
    r"""
    (?P<currency>[$€£])\s*
    (?P<min>\d{2,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?
    \s*(?:-|–|to)\s*
    (?P<currency2>[$€£])?\s*
    (?P<max>\d{2,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?
    (?:\s*/?\s*(?:per\s+)?(?P<period>year|yr|annum|hour|hr|month))?
    """,
    re.VERBOSE | re.IGNORECASE,
)

_CURRENCY_CODES = {"$": "USD", "€": "EUR", "£": "GBP"}


def _to_number(raw: str, had_k_suffix_context: str) -> float:
    value = float(raw.replace(",", ""))
    # Heuristic: "$120k" style figures are already handled by the k-suffix
    # capture outside this helper; this just parses the bare number.
    return value


def parse_salary(text: str | None) -> SalaryGuess:
    """Best-effort extraction of a salary range from free-form JD text.

    Returns an all-None SalaryGuess if nothing confidently matches — never
    invents a number.
    """
    if not text:
        return SalaryGuess()

    match = _SALARY_RANGE_RE.search(text)
    if not match:
        return SalaryGuess()

    raw_min = match.group("min")
    raw_max = match.group("max")
    span = match.group(0)

    min_val = float(raw_min.replace(",", ""))
    max_val = float(raw_max.replace(",", ""))

    # "k" shorthand (e.g. $120k-$150k) -> thousands.
    if re.search(r"\d[kK]\b", span):
        if min_val < 10_000:
            min_val *= 1_000
        if max_val < 10_000:
            max_val *= 1_000

    if min_val > max_val:
        min_val, max_val = max_val, min_val

    currency = _CURRENCY_CODES.get(match.group("currency"), None)
    period_raw = (match.group("period") or "").lower()
    period_map = {
        "year": "year",
        "yr": "year",
        "annum": "year",
        "hour": "hour",
        "hr": "hour",
        "month": "month",
    }
    period = period_map.get(period_raw)

    return SalaryGuess(
        salary_min=min_val,
        salary_max=max_val,
        currency=currency,
        salary_period=period,
        original_salary_text=span.strip(),
    )
