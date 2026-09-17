from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.models import TopicCandidate


EVENT_PROFILE_PUBLIC = "breaking_public"
EVENT_PROFILE_OFFICIAL = "official_announcement"
EVENT_PROFILE_VERIFICATION = "verification"
EVENT_PROFILE_ENTERTAINMENT = "entertainment_culture"
EVENT_PROFILE_SPORTS = "sports_event"
EVENT_PROFILE_GENERAL = "general_social"

SEARCH_MODE_OFF = "off"
SEARCH_MODE_OPTIONAL = "optional"
SEARCH_MODE_REQUIRED = "required"
SEARCH_MODE_AUTO_HIGH = "auto_high"


@dataclass(frozen=True)
class EventSkill:
    profile: str
    keywords: tuple[str, ...]
    analysis_focus: str
    source_priority: str
    reader_value: str


EVENT_SKILLS: dict[str, EventSkill] = {
    EVENT_PROFILE_PUBLIC: EventSkill(
        profile=EVENT_PROFILE_PUBLIC,
        keywords=(
            "地震", "余震", "火灾", "爆炸", "坍塌", "事故", "坠机", "空难", "失联",
            "暴雨", "洪水", "台风", "疫情", "病毒", "中毒", "燃气", "泄漏", "救援",
            "伤亡", "遇难", "疏散", "停课", "停运",
        ),
        analysis_focus=(
            "先交代发生了什么、发生时间和地点，再梳理已知影响、处置进展和读者需要采取的安全措施。"
            "不要停留在情绪讨论，遇到官方应急信息要直接提炼可执行要点。"
        ),
        source_priority="应急管理部门、气象或地震部门、属地官方发布、现场媒体、平台核实信息",
        reader_value="读者需要立刻知道事件规模、影响范围、官方处置和安全建议。",
    ),
    EVENT_PROFILE_OFFICIAL: EventSkill(
        profile=EVENT_PROFILE_OFFICIAL,
        keywords=(
            "官宣", "官方", "声明", "通报", "回应", "道歉", "发布会", "说明", "确认", "否认",
        ),
        analysis_focus=(
            "明确谁发布了信息、发布时间、发布内容和适用范围，再说明外界关注点和后续节点。"
            "区分当事方原文、媒体转述和网友解读，不把转述当作原文。"
        ),
        source_priority="当事方或机构原始发布、平台认证账号、权威媒体、现场报道",
        reader_value="读者需要知道官方信息的准确边界，而不是只看到讨论声量。",
    ),
    EVENT_PROFILE_VERIFICATION: EventSkill(
        profile=EVENT_PROFILE_VERIFICATION,
        keywords=("辟谣", "打假", "澄清", "否认", "传闻", "谣言", "不实", "疑似", "被曝", "举报"),
        analysis_focus=(
            "先写原始说法是什么，再写谁进行了回应或核实、回应了什么，最后标明当前状态。"
            "明确区分已确认、未回应和仅存在说法，不把辟谣对象写成事实。"
        ),
        source_priority="当事方回应、平台辟谣、权威媒体核实、原始爆料来源",
        reader_value="读者需要快速判断传闻当前是属实、被否认还是仍待确认。",
    ),
    EVENT_PROFILE_ENTERTAINMENT: EventSkill(
        profile=EVENT_PROFILE_ENTERTAINMENT,
        keywords=(
            "电视剧", "电影", "综艺", "歌手", "演员", "导演", "演唱会", "番位",
            "分手", "结婚", "离婚", "恋情", "粉丝", "明星", "剧组", "官宣恋情",
        ),
        analysis_focus=(
            "围绕作品、公开活动、当事方公开表态和讨论焦点展开，不写站队、CP 解读或私生活揣测。"
            "如果只有讨论没有确认，把讨论焦点写成讨论，不写成事实。"
        ),
        source_priority="当事方认证账号、作品或活动官方账号、权威娱乐媒体、平台公开内容",
        reader_value="读者想看清事件主线和公开信息，不需要情绪化站队。",
    ),
    EVENT_PROFILE_SPORTS: EventSkill(
        profile=EVENT_PROFILE_SPORTS,
        keywords=(
            "世界杯", "联赛", "比分", "对阵", "夺冠", "进球", "绝杀", "奥运",
            "NBA", "CBA", "冠军", "半决赛", "决赛", "球员", "球队",
        ),
        analysis_focus=(
            "先给比赛或赛程结果、关键过程和后续影响，再讨论争议判罚或舆论焦点。"
            "涉及判罚和伤病时以官方公告、赛后再说明为准。"
        ),
        source_priority="赛事官方、俱乐部或协会公告、持权转播方、现场权威报道",
        reader_value="读者需要知道赛果、关键节点和后续赛程或影响。",
    ),
    EVENT_PROFILE_GENERAL: EventSkill(
        profile=EVENT_PROFILE_GENERAL,
        keywords=(),
        analysis_focus=(
            "梳理事件主线、公开信息和公众关注点。若缺少可靠材料，直接说明哪些内容未能确认。"
        ),
        source_priority="当事方或机构发布、权威媒体、平台公开内容、可靠现场信息",
        reader_value="读者需要快速理解事件为什么被关注以及当前确认到什么程度。",
    ),
}

PROFILE_MATCH_ORDER = (
    EVENT_PROFILE_PUBLIC,
    EVENT_PROFILE_VERIFICATION,
    EVENT_PROFILE_OFFICIAL,
    EVENT_PROFILE_SPORTS,
    EVENT_PROFILE_ENTERTAINMENT,
)


def classify_event_profile(topic: TopicCandidate, weibo_context: str = "") -> str:
    title = str(topic.title or "").strip()
    context = str(weibo_context or "")[:800]
    for profile in PROFILE_MATCH_ORDER:
        skill = EVENT_SKILLS[profile]
        for keyword in skill.keywords:
            if keyword in title or keyword in context:
                return profile
    return EVENT_PROFILE_GENERAL


def event_skill(profile: str) -> EventSkill:
    return EVENT_SKILLS.get(profile, EVENT_SKILLS[EVENT_PROFILE_GENERAL])


def is_high_value_topic(topic: TopicCandidate, profile: str) -> bool:
    return topic.tag in {"爆", "沸"} or profile in {
        EVENT_PROFILE_PUBLIC,
        EVENT_PROFILE_OFFICIAL,
        EVENT_PROFILE_VERIFICATION,
    }


def resolve_search_mode(
    external_search: str,
    topic: TopicCandidate,
    profile: str,
) -> str:
    if external_search == SEARCH_MODE_OFF:
        return SEARCH_MODE_OFF
    if external_search in {SEARCH_MODE_OPTIONAL, SEARCH_MODE_REQUIRED}:
        return external_search
    if external_search == "auto":
        return (
            SEARCH_MODE_AUTO_HIGH
            if is_high_value_topic(topic, profile)
            else SEARCH_MODE_OFF
        )
    return SEARCH_MODE_OFF


def search_enabled(search_mode: str) -> bool:
    return search_mode in {SEARCH_MODE_OPTIONAL, SEARCH_MODE_REQUIRED, SEARCH_MODE_AUTO_HIGH}


def required_search(search_mode: str) -> bool:
    return search_mode in {SEARCH_MODE_REQUIRED, SEARCH_MODE_AUTO_HIGH}


def build_skill_prompt(skill: EventSkill) -> str:
    return (
        "本条热点的分析重点："
        f"{skill.analysis_focus}\n"
        f"信息优先级：{skill.source_priority}\n"
        f"读者价值：{skill.reader_value}"
    )


def build_search_prompt(topic: TopicCandidate, enabled: bool) -> str:
    if not enabled:
        return "本条洞察未启用外部搜索，请以输入公开材料为准；无法确认的内容写未能确认，不要添加泛化风险提示。"
    return (
        f"当前事件时间：{topic.fetched_at}\n"
        "外部搜索策略：先搜索精确热搜词，再搜索“热搜词 + 官方/通报/回应/辟谣”，"
        "必要时搜索事件主体 + 权威媒体。优先采用近 7 天内且与当前热搜词直接相关的来源；"
        "超过 7 天的旧来源只能作为背景补充，不得当作当前事实依据，"
        "也不要用历史相似事件覆盖本次热搜现场。"
        f"本次热搜词：{topic.title}"
    )
