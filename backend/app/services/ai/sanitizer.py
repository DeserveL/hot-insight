from __future__ import annotations

import re

GENERIC_RISK_NOTE = "相关信息仍需以当事方、权威媒体或平台后续公开说明为准，注意区分事实、观点和未经证实的传播内容。"
GENERIC_SUMMARY = "相关信息仍在更新，目前能够确认的内容有限，需结合后续公开说明继续判断。"
GENERIC_TAKEAWAY = "相关信息仍需以后续公开说明为准"
GENERIC_COMMENTARY = "相关讨论仍在发酵，宜先区分已确认信息和未经证实的说法。"

TECHNICAL_RISK_TERMS = (
    "搜索工具",
    "实时搜索工具",
    "联网工具",
    "联网能力",
    "当前环境",
    "api",
    "模型",
    "web_search",
    "web_search_options",
    "提示词",
    "json key",
    "json字段",
    "json 字段",
    "字段名",
    "上下文变量",
    "weibo_context",
    "official_context",
    "mobile_context",
    "realtime_posts",
    "combined_context",
    "source_excerpt",
    "context_hash",
)

PUBLIC_CONTEXT_REPLACEMENTS = (
    ("微博官方详情页内容", "相关公开内容"),
    ("微博官方详情内容", "相关公开内容"),
    ("微博官方详情页", "相关公开内容"),
    ("微博官方详情", "相关公开内容"),
    ("官方详情页内容", "相关公开内容"),
    ("官方详情页", "相关公开内容"),
    ("热搜详情页材料", "相关公开内容"),
    ("热搜详情页内容", "相关公开内容"),
    ("微博移动端热搜词页", "公开讨论"),
    ("微博移动端讨论材料", "公开讨论"),
    ("微博移动端讨论", "公开讨论"),
    ("移动端讨论材料", "公开讨论"),
    ("移动端讨论", "公开讨论"),
    ("移动端搜索内容", "公开讨论"),
    ("移动端搜索", "公开讨论"),
    ("移动端材料", "公开讨论"),
    ("以上实时内容", "上述公开内容"),
    ("热搜实时内容", "相关讨论"),
    ("实时帖子", "相关讨论"),
    ("实时博文", "相关讨论"),
    ("实时内容", "公开内容"),
)

PUBLIC_CONTEXT_FORBIDDEN_TERMS = tuple(term for term, _ in PUBLIC_CONTEXT_REPLACEMENTS)


def sanitize_public_risk_note(value: str) -> str:
    risk_note = value.strip()
    if not risk_note:
        return GENERIC_RISK_NOTE
    lowered = risk_note.lower()
    if any(term in lowered for term in TECHNICAL_RISK_TERMS):
        return GENERIC_RISK_NOTE
    return risk_note


def sanitize_generated_ai_text(value: str, *, fallback: str) -> str:
    text = _compact_text(value)
    if not text:
        return fallback
    text = _replace_public_context_terms(text)
    if _contains_forbidden_public_term(text):
        return fallback
    return text


def sanitize_generated_ai_facts(values: list[str]) -> list[str]:
    facts: list[str] = []
    for value in values:
        fact = sanitize_generated_ai_text(value, fallback="")
        if fact:
            facts.append(fact)
    return facts


def sanitize_generated_ai_risk_note(value: str) -> str:
    risk_note = sanitize_public_risk_note(value)
    return sanitize_generated_ai_text(risk_note, fallback=GENERIC_RISK_NOTE)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _replace_public_context_terms(value: str) -> str:
    text = value
    for old, new in PUBLIC_CONTEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _contains_forbidden_public_term(value: str) -> bool:
    lowered = value.lower()
    if any(term in lowered for term in TECHNICAL_RISK_TERMS):
        return True
    return any(term in value for term in PUBLIC_CONTEXT_FORBIDDEN_TERMS)
