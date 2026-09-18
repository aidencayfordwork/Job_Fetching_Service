"""Role-family classification against the target role list from
architecture.md §2B. Also doubles as the "is this a software engineering
job at all" signal for filters.py: `role_category is None` means no
target role family matched.

Title matches are checked first, in priority order (most specific role
family before generic ones, so e.g. "Senior ML Platform Engineer" lands
on Machine Learning rather than the generic Platform/Infrastructure
bucket). JD text is only consulted when the title itself gives no match.
"""

from __future__ import annotations

import re

from app.connectors.base import JobDraft

# Ordered: earlier entries win when multiple would otherwise match the
# same title. Each pattern is a compiled, case-insensitive, word-boundary
# regex checked against the title first, then (if no title match at all)
# against the JD.
_ROLE_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "AI / Generative AI",
        re.compile(r"generative\s*ai|genai|\bllm\b|large\s+language\s+model|prompt\s+engineer|\bgpt\b", re.IGNORECASE),
    ),
    ("Machine Learning", re.compile(r"machine\s+learning|\bml\b|deep\s+learning", re.IGNORECASE)),
    ("MLOps", re.compile(r"\bmlops\b", re.IGNORECASE)),
    (
        "Security Engineering",
        re.compile(r"security\s+engineer|application\s+security|\bappsec\b|penetration\s+test", re.IGNORECASE),
    ),
    ("Mobile / Android / iOS", re.compile(r"\bios\s+engineer|android\s+engineer|mobile\s+engineer|mobile\s+developer", re.IGNORECASE)),
    ("DevOps / SRE", re.compile(r"devops|site\s+reliability|\bsre\b", re.IGNORECASE)),
    ("Data Engineering", re.compile(r"data\s+engineer", re.IGNORECASE)),
    ("Platform / Infrastructure", re.compile(r"platform\s+engineer|infrastructure\s+engineer", re.IGNORECASE)),
    ("Cloud", re.compile(r"cloud\s+engineer", re.IGNORECASE)),
    ("Distributed Systems", re.compile(r"distributed\s+systems", re.IGNORECASE)),
    ("Frontend", re.compile(r"front[\s-]?end\s+(?:engineer|developer)", re.IGNORECASE)),
    ("Full Stack", re.compile(r"full[\s-]?stack", re.IGNORECASE)),
    ("Backend", re.compile(r"back[\s-]?end\s+(?:engineer|developer)", re.IGNORECASE)),
    ("Python", re.compile(r"\bpython\s+(?:engineer|developer)", re.IGNORECASE)),
    # "\s+" between "java" and the role word means this never matches
    # inside "JavaScript" (which has no space there).
    ("Java", re.compile(r"\bjava\s+(?:engineer|developer)", re.IGNORECASE)),
    ("C# / .NET", re.compile(r"\.net\s+(?:engineer|developer)|c#\s+(?:engineer|developer)", re.IGNORECASE)),
    # Generic fallback: any "software/backend/systems engineer"-shaped
    # title with no more specific signal is still in scope.
    ("Backend", re.compile(r"software\s+engineer|systems?\s+engineer", re.IGNORECASE)),
]


def classify_role(job: JobDraft) -> JobDraft:
    """Set `job.role_category` in place (None if no target role family
    matches - filters.py excludes on that)."""
    title = job.job_title or ""

    for category, pattern in _ROLE_RULES:
        if pattern.search(title):
            job.role_category = category
            return job

    jd = job.cleaned_job_description or ""
    for category, pattern in _ROLE_RULES:
        if pattern.search(jd):
            job.role_category = category
            return job

    job.role_category = None
    return job
