"""Role-family classification against the target role list from
architecture.md §2B. Also doubles as the "is this a software engineering
job at all" signal for filters.py: `role_category is None` means no
target role family matched.

Title-only matching, deliberately - an earlier version fell back to
scanning the whole JD body when the title didn't match, and that caused
two separate real false positives found via live testing:
1. A recruiter's JD mentioning "hire great Software Engineers" (who they
   recruit for) and a product manager's JD mentioning "our Generative AI
   roadmap" (the product they manage) matched the generic engineering
   patterns and got kept as engineering roles.
2. Even after adding a non-engineering-title gate for (1): a company's
   generic "About us" boilerplate ("Our expertise spans Operations,
   Training, Engineering, ... Machine Learning and Software
   Engineering...") appeared at the top of every one of that company's
   postings regardless of actual role, and got several Power BI/Cloud
   Architect/data-analyst postings misclassified as "Machine Learning".

Both were JD-body matching picking up mentions of a technology/role
*adjacent* to the posting rather than *of* it. Title-only avoids this
class of bug entirely: a real engineering posting's title says so.
"""

from __future__ import annotations

import re

from app.connectors.base import JobDraft

# Checked first, title only - a clear non-engineering function disqualifies
# the job outright, regardless of what the JD body happens to mention.
_NON_ENGINEERING_TITLE_RE = re.compile(
    r"""(?<![A-Za-z0-9])(
        recruiter | recruiting | talent\s+acquisition |
        account\s+(?:manager|executive) | sales | business\s+development |
        marketing | community\s+manager |
        customer\s+(?:success|support) | technical\s+support\s+representative |
        \bhr\b | human\s+resources | people\s+partner | people\s+operations |
        compensation\s+partner |
        legal\s+counsel | paralegal |
        accountant | accounting | bookkeeper | controller |
        localization\s+(?:manager|operations) |
        program\s+manager | project\s+manager | product\s+manager |
        editor | copywriter | content\s+writer |
        (?:ux|ui|graphic)\s+designer |
        office\s+manager | executive\s+assistant
    )(?![A-Za-z0-9])""",
    re.IGNORECASE | re.VERBOSE,
)

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
    matches, or if the title clearly names a non-engineering function -
    filters.py excludes on that). Title-only - see module docstring."""
    title = job.job_title or ""

    if _NON_ENGINEERING_TITLE_RE.search(title):
        job.role_category = None
        return job

    for category, pattern in _ROLE_RULES:
        if pattern.search(title):
            job.role_category = category
            return job

    job.role_category = None
    return job
