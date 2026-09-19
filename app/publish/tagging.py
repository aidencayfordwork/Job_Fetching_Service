"""Choose BidFlow tag codes for a job (JOB_PLATFORM_DB_PROMPT §9).

- ★ role tags (1-2) come only from the title / role classification - never
  from description text, so a company that "works in AI" doesn't make every
  one of its jobs an `ai` job.
- Technology tags come from the requirement parts of the description only:
  nice-to-have / bonus / "about us" / benefits sections and "...is a plus"
  sentences are removed first, then terms are ranked by how often they appear.
- Real skills the catalog doesn't know yet are sent as unknown terms so
  BidFlow's admins can add them (existing rows then pick them up).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.pipeline.match_keywords import taxonomy_terms, term_patterns
from app.publish.catalog import TagCatalog, tag_key

MAX_ROLE_TAGS = 2
MAX_TECH_TAGS = 13
MAX_UNKNOWN_TAGS = 5

# Catalog spellings too ambiguous to match in free text; the codes they belong
# to are either role tags (decided from the title) or covered by the phrase
# rules below.
_AMBIGUOUS_SPELLINGS = {
    "go", "ts", "js", "node", "cloud", "mobile", "ios", "evaluation", "streaming",
    "statistics", "experimentation", "frontend", "front end", "front-end",
    "fullstack", "full stack", "full-stack", "devops", "backend", "back end",
    "back-end", "swift",
}
# Role-type codes that are decided from the title, never from text.
_ROLE_ONLY_CODES = {"fullstack", "frontend", "mobile", "ios", "devops", "cloud"}

_I = re.IGNORECASE
_PHRASE_RULES: dict[str, re.Pattern[str]] = {
    "node.js": re.compile(r"\bnode\.?js\b|\bnode js\b", _I),
    "api design": re.compile(
        r"\bapi design\b|\brest(?:ful)? apis?\b|\bapi development\b"
        r"|\b(?:build|design|develop)\w*\s+(?:[\w-]+\s+){0,3}apis?\b", _I),
    "data modeling": re.compile(r"\bdata model(?:l)?ing\b|\bdata models?\b", _I),
    "model training": re.compile(r"\b(?:model|llm) training\b|\btrain(?:ing)?\s+(?:[\w-]+\s+){0,2}models\b", _I),
    "model monitoring": re.compile(r"\bmodel monitoring\b|\bmonitor(?:ing)?\s+(?:[\w-]+\s+){0,2}models\b", _I),
    "feature engineering": re.compile(r"\bfeature engineering\b|\bfeature stores?\b", _I),
    "streaming": re.compile(
        r"\bstream processing\b|\b(?:data|event|real[- ]time) streaming\b"
        r"|\bstreaming (?:data|pipelines?|platforms?|systems?)\b", _I),
    "statistics": re.compile(r"\bstatistics\b|\bstatistical (?:modeling|analysis|methods)\b", _I),
    "experimentation": re.compile(r"\bexperimentation\b|\ba/b test(?:ing|s)?\b", _I),
    "evaluation": re.compile(r"\b(?:model|llm|ai) evaluations?\b|\bevals\b", _I),
    # Case-sensitive, and "Go" must follow a word or list separator ("in Go",
    # "Python, Go", "(Go)") - a sentence starting "Go above and beyond" isn't Go.
    "swift": re.compile(r"\bSwift(?:UI)?\b"),
    "go": re.compile(r"(?i:\bgolang\b)|(?<=[A-Za-z0-9,/(] )Go\b(?!-)|(?<=[,/(])Go\b(?!-)"),
}
# These codes use only their phrase rule, never the taxonomy or catalog spellings.
_EXCLUSIVE_RULES = {"swift", "go"}
# My taxonomy terms that correspond to a catalog tag under a different name.
_TAXONOMY_BRIDGES = {"REST API": "api design"}
# Only concrete skills are worth proposing to BidFlow's admins as new tags.
_UNKNOWN_TAG_CATEGORIES = {
    "languages", "frontend", "backend_frameworks", "mobile", "ai_ml",
    "data_engineering", "databases", "cloud_infra", "devops_sre",
}
_GENERIC_TERMS = {
    "C", "R",
    "Data Warehouse", "Data Pipeline", "Observability", "Incident Response",
    "Site Reliability Engineering", "Serverless", "Deep Learning", "Neural Networks",
}

_EXCLUDED_SECTION_RE = re.compile(
    r"nice[\s-]to[\s-]have|bonus|preferred|\bplus\b|extra credit|benefits|perks|what we offer"
    r"|compensation|\bsalary\b|pay (?:range|transparency)|equal (?:employment )?opportunity|\beeo\b"
    r"|our values|why (?:join|work)|life at|diversity|accommodation|privacy|how to apply"
    r"|interview process|^about (?!the (?:role|team|job|position|opportunity|work)|you\b|this role)",
    re.IGNORECASE,
)
_OPTIONAL_SENTENCE_RE = re.compile(
    r"nice[\s-]to[\s-]have|\bis a plus\b|\bare a plus\b|\ba plus\b|\bbonus\b|\bpreferred\b"
    r"|\bideally\b|\bnot required\b|\bextra credit\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")


@dataclass(frozen=True)
class TagChoice:
    tags: list[str]  # catalog codes, role tags first
    unknown: list[str]  # real skills with no catalog tag yet

    @property
    def all(self) -> list[str]:
        return self.tags + self.unknown


def _is_heading(line: str) -> bool:
    if not line or line.startswith("- ") or len(line) > 80 or len(line.split()) > 10:
        return False
    if line.endswith(":"):
        return True
    # "Python, Go, Rust" is a plain-text skills list, not a heading.
    return len(line.split()) <= 6 and "," not in line and line[0].isupper() and line[-1] not in ".!?;"


def requirements_text(jd_text: str) -> str:
    """The description minus optional, company-marketing and benefits content."""
    kept: list[str] = []
    excluded = False
    for raw_line in jd_text.split("\n"):
        line = raw_line.strip()
        if _is_heading(line):
            excluded = bool(_EXCLUDED_SECTION_RE.search(line.rstrip(":").lstrip("#").strip()))
        if excluded or not line:
            continue
        sentences = [s for s in _SENTENCE_SPLIT_RE.split(line) if not _OPTIONAL_SENTENCE_RE.search(s)]
        if sentences:
            kept.append(" ".join(sentences))
    return "\n".join(kept)


_TITLE_ROLE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("mlops", re.compile(r"\bml\s*ops\b|machine learning (?:platform|infrastructure|ops)", re.I)),
    ("genai", re.compile(r"gen\s*ai|generative|\bllms?\b|large language|prompt engineer|\bagents?\b", re.I)),
    ("ai", re.compile(r"\bai\b|artificial intelligence", re.I)),
    ("ml", re.compile(r"machine learning|\bml\b|deep learning", re.I)),
    ("data engineering", re.compile(r"data engineer", re.I)),
    ("data platform", re.compile(r"data platform", re.I)),
    ("data science", re.compile(r"data scien", re.I)),
    ("android", re.compile(r"\bandroid\b", re.I)),
    ("backend", re.compile(
        r"back[\s-]?end|server[\s-]side|\bapi engineer|distributed systems"
        r"|\b(?:python|java|go|golang|\.net|c#|ruby|rails|node(?:\.js)?|scala|rust|elixir)\s+"
        r"(?:software\s+)?(?:engineer|developer)", re.I)),
]

_CATEGORY_ROLE_CODES = {
    "Full Stack": ["fullstack"],
    "Frontend": ["frontend"],
    "DevOps / SRE": ["devops"],
    "Platform / Infrastructure": ["devops"],
    "Cloud": ["cloud"],
    "Distributed Systems": ["backend", "distributed systems"],
    "Python": ["backend"],
    "Java": ["backend"],
    "C# / .NET": ["backend"],
}

_BACKEND_SIGNALS = {
    "python", "go", "java", "kotlin", "postgresql", "sql", "kafka", "microservices",
    "api design", "distributed systems", "node.js", "fastapi", "event-driven",
}
_FRONTEND_SIGNALS = {"react", "typescript", "javascript"}


def _role_codes(title: str, role_category: str | None, tech_codes: set[str]) -> list[str]:
    codes: list[str] = []
    for code, pattern in _TITLE_ROLE_RULES:
        if pattern.search(title) and not (code == "ai" and "genai" in codes) and not (
            code == "ml" and "mlops" in codes
        ):
            codes.append(code)
    codes.extend(_CATEGORY_ROLE_CODES.get(role_category or "", []))
    if role_category == "Mobile / Android / iOS":
        codes.append("mobile")
        if re.search(r"\bios\b", title, re.I):
            codes.append("ios")

    # A generic "Software Engineer" title says nothing about the area; decide
    # from what the requirements actually ask for.
    if not codes and role_category == "Backend":
        backend = len(tech_codes & _BACKEND_SIGNALS)
        frontend = len(tech_codes & _FRONTEND_SIGNALS)
        if backend >= 2 and frontend >= 2:
            codes.append("fullstack")
        elif backend >= 2:
            codes.append("backend")
    return list(dict.fromkeys(codes))


def _tech_patterns(catalog: TagCatalog) -> dict[str, list[re.Pattern[str]]]:
    """code -> patterns that count as evidence for it."""
    by_code: dict[str, list[re.Pattern[str]]] = {}
    for canonical, pattern in term_patterns().items():
        tag = catalog.resolve(_TAXONOMY_BRIDGES.get(canonical, canonical))
        if tag is None:
            _, aliases = taxonomy_terms()[canonical]
            tag = next((t for t in map(catalog.resolve, aliases) if t), None)
        if tag is not None:
            by_code.setdefault(tag.code, []).append(pattern)

    for spelling, code in catalog.lookup_terms().items():
        if spelling in _AMBIGUOUS_SPELLINGS or code in _PHRASE_RULES or len(spelling) < 3:
            continue
        body = rf"(?<![A-Za-z0-9]){re.escape(spelling)}(?![A-Za-z0-9])"
        by_code.setdefault(code, []).append(re.compile(body, re.IGNORECASE))

    for code, pattern in _PHRASE_RULES.items():
        if code in catalog.tags:
            by_code[code] = [pattern] if code in _EXCLUSIVE_RULES else [*by_code.get(code, []), pattern]
    return by_code


def _count(patterns: list[re.Pattern[str]], text: str) -> int:
    return sum(len(p.findall(text)) for p in patterns)


def choose_tags(title: str, role_category: str | None, jd_text: str, catalog: TagCatalog) -> TagChoice:
    req = requirements_text(jd_text)

    scores: dict[str, int] = {}
    for code, patterns in _tech_patterns(catalog).items():
        tag = catalog.tags[code]
        if tag.important or code in _ROLE_ONLY_CODES:
            continue
        score = _count(patterns, req) + 3 * _count(patterns, title)
        if score:
            scores[code] = score
    tech = sorted(scores, key=lambda c: (-scores[c], c))[:MAX_TECH_TAGS]

    role = [c for c in _role_codes(title, role_category, set(scores)) if c in catalog.tags]
    stars = [c for c in role if catalog.tags[c].important][:MAX_ROLE_TAGS]
    role_normal = [c for c in role if not catalog.tags[c].important]
    tags = list(dict.fromkeys([*stars, *role_normal, *(c for c in tech if c not in role_normal)]))

    unknown_scores: dict[str, int] = {}
    for canonical, pattern in term_patterns().items():
        category, aliases = taxonomy_terms()[canonical]
        if (
            category not in _UNKNOWN_TAG_CATEGORIES
            or canonical in _GENERIC_TERMS
            or canonical in _TAXONOMY_BRIDGES
            or catalog.resolve(canonical)
            or any(catalog.resolve(a) for a in aliases)
        ):
            continue
        score = len(pattern.findall(req)) + 3 * len(pattern.findall(title))
        if score:
            unknown_scores[tag_key(canonical)] = score
    unknown = sorted(unknown_scores, key=lambda c: (-unknown_scores[c], c))[:MAX_UNKNOWN_TAGS]

    return TagChoice(tags=tags, unknown=unknown)
