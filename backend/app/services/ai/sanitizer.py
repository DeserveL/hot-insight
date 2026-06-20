from __future__ import annotations

GENERIC_RISK_NOTE = "相关信息仍需以当事方、权威媒体或平台后续公开说明为准，注意区分事实、观点和未经证实的传播内容。"

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


def sanitize_public_risk_note(value: str) -> str:
    risk_note = value.strip()
    if not risk_note:
        return GENERIC_RISK_NOTE
    lowered = risk_note.lower()
    if any(term in lowered for term in TECHNICAL_RISK_TERMS):
        return GENERIC_RISK_NOTE
    return risk_note
