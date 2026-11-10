"""Temple-guide domain glue: deterministic wish extraction + grounded context.

Why deterministic instead of a model-planned tool call: the product promises a
5–10 s answer, one curated dataset lookup is cheap and reproducible, and it
keeps traceability simple (every injected row is a curated row, never invented).

Nothing here writes to disk; memory writes go through the profile merge path.
"""

from __future__ import annotations

import json
import re
from html import escape
from contextvars import ContextVar
from typing import Any, Optional

from app.agent.domain import origins as origin_index
from app.agent.domain.visit_conditions import assess_conditions, booking_guidance, extract_conditions, is_condition_update

# 最近一次注入的资料（供评测/诊断读取，不进入图状态、不影响线上输出）
_LAST_PAYLOAD: ContextVar[Optional[dict[str, Any]]] = ContextVar("temple_last_payload", default=None)


def set_last_payload(payload: Optional[dict[str, Any]]) -> None:
    _LAST_PAYLOAD.set(payload)


def get_last_payload() -> Optional[dict[str, Any]]:
    return _LAST_PAYLOAD.get()


# 本轮注入的**全部**资料（寺庙 + 评价 + 行前），供引用校验与评测使用
_LAST_GROUNDING: ContextVar[Optional[dict[str, Any]]] = ContextVar("temple_last_grounding", default=None)


def set_last_grounding(payload: Optional[dict[str, Any]]) -> None:
    _LAST_GROUNDING.set(payload)


def get_last_grounding() -> Optional[dict[str, Any]]:
    return _LAST_GROUNDING.get()
from app.agent.domain import temples as domain

# Ordered: the first theme whose keyword appears wins (most specific first).
_THEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("求子", ("求子", "生子", "怀不上", "怀孕", "生个孩子", "想要孩子", "想要个孩子", "备孕", "不孕")),
    ("姻缘", ("姻缘", "脱单", "找对象", "求姻缘", "婚姻", "嫁", "娶", "桃花", "男朋友", "女朋友")),
    ("学业", ("学业", "考试", "考研", "高考", "中考", "升学", "offer", "上岸", "论文", "求职")),
    ("财运", ("财运", "求财", "发财", "赚钱", "财运亨通", "生意")),
    ("事业", ("事业", "升职", "工作顺利", "仕途", "加薪", "跳槽")),
    ("健康", ("健康", "身体健康", "去病", "康复", "治病")),
    ("平安", ("平安", "顺遂", "消灾", "祈福", "保佑", "顺利")),
)

# Sentences that mention a temple topic at all (used to decide whether to inject).
_TEMPLE_SIGNALS = (
    "寺庙", "寺院", "庙", "拜佛", "拜拜", "上香", "烧香", "祈福", "许愿", "还愿", "道观", "娘娘庙",
    "求子", "姻缘", "求财", "学业", "功德", "香火", "佛", "菩萨", "开光",
)

_ORIGIN_PATTERNS = (
    re.compile(r"从(?P<place>[一-鿿A-Za-z0-9·\s]{2,20}?)出发"),
    re.compile(r"从(?P<place>[一-鿿A-Za-z0-9·\s]{2,20}?)(?:去|到|往)"),
    re.compile(r"我在(?P<place>[一-鿿A-Za-z0-9·\s]{2,20}?)(?:[，,。！？\s]|$)"),
    re.compile(r"我住(?:在)?(?P<place>[一-鿿A-Za-z0-9·\s]{2,20}?)(?:[，,。！？\s]|$)"),
    re.compile(r"(?P<place>北京[一-鿿]{0,6}(?:区|县))"),
)

_COMPANION_PATTERNS = (
    ("家人", ("和家人", "带家人", "陪家人", "跟家人")),
    ("父母", ("和父母", "带父母", "陪父母", "爸妈", "父母")),
    ("孩子", ("带孩子", "带娃", "和孩子", "小孩")),
    ("伴侣", ("和对象", "和伴侣", "和老公", "和老婆", "男朋友", "女朋友")),
    ("朋友", ("和朋友", "和朋友一起", "闺蜜", "同学一起")),
    ("独自", ("自己去", "一个人去", "单独去")),
)

_TRAVEL_PATTERNS = (
    ("公共交通", ("地铁", "公交", "坐车", "不打车")),
    ("自驾", ("自驾", "开车", "有车")),
    ("打车", ("打车", "出租", "滴滴")),
    ("步行少", ("不方便走", "走不动", "腿脚", "轮椅", "无障碍", "少走路")),
    ("体力有限", ("体力不好", "爬不动", "不想爬山", "老年人")),
)


def detect_theme(message: str) -> Optional[str]:
    text = (message or "").strip()
    if not text:
        return None
    for theme, kws in _THEME_KEYWORDS:
        for keyword in kws:
            for match in re.finditer(re.escape(keyword), text):
                prefix = re.split(r"[，,。；;！!？?]", text[:match.start()])[-1]
                if re.search(r"(?:不是|并非|不想|不要|不用|不再|不)(?:来|去|要|求)?$", prefix):
                    continue
                return theme
    return None


# 地点得像地点：地名后缀，否则「我在小红书发个帖子」会把整句当地点
_PLACE_SUFFIX = re.compile(r"(区|县|市|镇|村|路|街|门|桥|园|场|站|机场|附近|边|路口|胡同|小区)$")


def _clean_place(candidate: str) -> Optional[str]:
    place = (candidate or "").strip(" ，,。！？、")
    if not (2 <= len(place) <= 12):
        return None
    match = origin_index.match_origin(place)
    if match:
        return match["name"]
    if _PLACE_SUFFIX.search(place):
        return place
    return None


def detect_origin(message: str) -> Optional[str]:
    text = message or ""
    for pattern in _ORIGIN_PATTERNS:
        m = pattern.search(text)
        if m:
            place = _clean_place(m.group("place") or "")
            if place:
                return place
    # 兜底：句子里直接出现了常见地标（"三里屯附近""我在中关村"），
    # 这样「三里屯附近，求事业」也能算距离。
    match = origin_index.match_origin(text)
    return match["name"] if match else None


def detect_companions(message: str) -> list[str]:
    text = message or ""
    return [label for label, kws in _COMPANION_PATTERNS if any(k in text for k in kws)][:3]


def detect_travel_preferences(message: str) -> list[str]:
    text = message or ""
    return [label for label, kws in _TRAVEL_PATTERNS if any(k in text for k in kws)][:3]


def mentioned_temples(message: str) -> list[dict[str, Any]]:
    """Mentioned temples in the message, longest match first (deduped).

    「红螺寺和妙峰山哪个好」必须同时拿到两座——
    只注入一座，模型就会用记忆回答另一座，那条答案是不可核的。
    """
    text = (message or "").replace(" ", "")
    hits: list[tuple[int, dict[str, Any]]] = []
    for t in domain.all_temples():
        best = 0
        for name in [t["name"], *t.get("aliases", [])]:
            key = name.replace(" ", "")
            if key and key in text:
                best = max(best, len(key))
        if best:
            hits.append((best, t))
    hits.sort(key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    for _, t in hits:
        if t not in out:
            out.append(t)
    return out


def mentioned_temple(message: str) -> Optional[dict[str, Any]]:
    """最长命中的那一座（兼容旧调用）。"""
    found = mentioned_temples(message)
    return found[0] if found else None


def is_temple_turn(message: str) -> bool:
    text = message or ""
    if not text.strip():
        return False
    if mentioned_temple(text) is not None:
        return True
    if detect_theme(text) is not None:
        return True
    return any(s in text for s in _TEMPLE_SIGNALS)


def _compact(t: dict[str, Any], origin: dict[str, Any] | None = None,
             conditions: dict[str, Any] | None = None) -> dict[str, Any]:
    km = origin_index.distance_from(origin, t.get("lat"), t.get("lng"))
    return {
        "condition_checks": assess_conditions(t, conditions)["checks"],
        "distance_km": km,
        "distance_note": (
            "" if origin is None else
            (f"距{origin['name']}直线约 {km} 公里（非行车距离）" if km is not None
             else "暂未取到可靠坐标，不能说距离")
        ),
        "name": t["name"],
        "district": t["district"],
        "status": t.get("status"),
        "status_label": domain.STATUS_LABELS.get(str(t.get("status")), t.get("status")),
        "religious_registered": t.get("religious_registered"),
        "visitable": t.get("visitable", False),
        "wish_recommendable": t.get("wish_recommendable", False),
        "open_note": t.get("open_note", ""),
        "recommend_note": t.get("recommend_note", ""),
        "sect": t.get("sect", ""),
        "deities": t.get("deities", []),
        "wish_themes": [
            {
                "theme": w["theme"],
                "role": w.get("role"),
                "claim": w.get("claim", ""),
                "claim_evidence": w.get("claim_evidence"),
                "claim_label": domain.wish_claim_label(w),
                "basis": w.get("basis", ""),
                "basis_source": w.get("basis_source", ""),
            }
            for w in t.get("wish_themes", [])
        ],
        "halls": [
            {"name": h["name"], "deity": h.get("deity", ""), "themes": h.get("themes", [])}
            for h in t.get("halls", [])
        ],
        "atmosphere": t.get("atmosphere", ""),
        "transport": t.get("transport", ""),
        "accessibility": t.get("accessibility", ""),
        "open_status": t.get("open_status", "unverified"),
        "closure_rule": t.get("closure_rule", []),
        "visit_note": t.get("visit_note", ""),
        "place_facts": [
            {"text": f.get("text", ""), "source": f.get("source", "")}
            for f in t.get("place_facts", [])
        ],
        "sources": t.get("sources", []),
        "sources_status": t.get("sources_status", "unverified"),
        "finder_hint": t.get("finder_hint", []),
        "checked_at": t.get("checked_at", ""),
    }


TEMPLE_DATA_RULE = (
    "【寺庙资料】以下是资料库中的策划条目，不是你编的内容，也不是祈愿承诺。"
    "只使用这里出现的字段；字段为空或没收录的寺庙，就说「暂未查到」，不要补造。"
    "依据分两层：place_facts 是场所事实（可核），wish_themes[].claim 是「人们来求什么」的民俗说法。"
    "claim_evidence=reference 可以说「资料里记载有这个说法」；folk 必须说成「民间口碑/网上流传的说法」，"
    "不能当事实；不要把「殿宇有记载」偷换成「在这儿求就灵」。"
    "sources_status=unverified 时不要暗示自己有引用，直接说「我这边没查到官方出处」，"
    "并给出 finder_hint 里的渠道让用户自己去问。"
    "距离一律用 distance_note 里的直线距离，并说明「非行车距离」；distance_km 为空时不许编距离。"
    "status=heritage（文博点）或 scenic（景区/民间信仰）要说明「这里不是上香许愿的宗教活动场所」，"
    "religious_registered=false 时更要说清（例如妙峰山没有僧道进驻，只是景区）；"
    "religious_registered=null 表示待核，不要断言。"
    "open_status 与 closure_rule（如周一闭馆、需预约）必须先说，避免用户白跑。"
    "开放时间、门票、预约等易变信息统一提示以官方为准、临行复核。"
    "不要输出任何「灵验分」「排行榜」「成功率」。"
)


def mentioned_district(message: str) -> str | None:
    return next((district for district in sorted({t["district"] for t in domain.all_temples()})
                 if district and district in message), None)


def location_scope(message: str) -> dict[str, bool]:
    text = re.sub(r"[，,。！!\s]", "", message or "")
    anywhere = bool(re.search(r"(?:哪个区|哪些区|哪儿|哪里|区域|地区|地点).{0,4}(?:都行|都可以|不限|无所谓)|(?:不限|不限制|不限定)(?:区域|地区|地点|距离)|全北京", text))
    ignore_origin = anywhere or bool(re.search(r"(?:不用|不必|不要|不需要|无需|不考虑|别管|不用管).{0,8}(?:出发|距离|位置)|不管.{0,8}出发|直接.{0,6}推荐", text))
    return {"anywhere": anywhere, "ignore_origin": ignore_origin}


def _resolve_followup(message: str, session: dict[str, Any]) -> tuple[str, str]:
    """Resolve only explicit references to candidates from this thread."""
    if mentioned_temples(message) or not session:
        return message, ""
    # Do not turn a new writing/code task into a temple follow-up.
    if any(word in message for word in ("写邮件", "写封", "代码", "翻译", "合同", "文案", "第二个孩子")):
        return message, ""
    candidates = session.get("candidates") or []
    ordinal = re.search(r"第([一二三123])(?:个|座|家)", message)
    if ordinal:
        index = "一二三".find(ordinal[1]) if ordinal[1] in "一二三" else int(ordinal[1]) - 1
        if index >= len(candidates):
            return message, "你想了解哪座寺庙？可以直接告诉我名字。"
        temple = domain.get_temple(candidates[index])
        if temple:
            return f"{temple['name']}，{message}", ""
    new_search = any(word in message for word in ("推荐", "换", "重新", "别的", "其他", "近一点", "近点"))
    if session.get("focus") and is_condition_update(message) and not new_search:
        focus = domain.get_temple(session["focus"])
        if focus:
            return f"{focus['name']}，{message}", ""
    if re.search(r"那里|那边|这座|那座|它|(?:这个|那个)(?!周|月|星期|礼拜)", message):
        focus = domain.get_temple(session.get("focus") or "")
        if focus:
            return f"{focus['name']}，{message}", ""
        return message, "你指的是哪座寺庙？可以告诉我名字，或说上一轮的第几个。"
    return message, ""


def build_temple_context(message: str, profile: dict[str, Any] | None = None,
                         session: dict[str, Any] | None = None,
                         interpretation: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Build the grounded payload + prompt block for this turn.

    Returns ``None`` when the turn is not temple-related, so the generic agent
    keeps working unchanged. The payload is returned separately because the
    citation verifier needs to know exactly which rows were injected.
    """
    original = (message or "").strip()
    session = dict(session or {})
    interpretation = interpretation or {}
    scope = location_scope(original)
    if interpretation.get("unrestricted"):
        scope = {"anywhere": True, "ignore_origin": True}
    explicit_district = mentioned_district(original)
    text, clarification = _resolve_followup(original, session)
    if interpretation.get("clarification"):
        clarification = interpretation["clarification"]
    condition_update = is_condition_update(original)
    if not is_temple_turn(original) and any(word in original for word in ("写邮件", "写封", "代码", "翻译", "合同", "文案")):
        return None
    continuation = bool(session or (profile or {}).get("wish")) and (
        condition_update or scope["ignore_origin"] or interpretation.get("related")
        or bool(detect_origin(text)) or bool(clarification)
        or any(t['district'] in text for t in domain.all_temples() if t.get('district'))
        or any(word in text for word in ("近一点", "近点", "附近", "就近", "不爬山", "带父母", "带老人", "安静一点", "哪里都行", "都可以", "不怕远", "专程"))
    )
    if not is_temple_turn(text) and not continuation and not explicit_district:
        return None

    profile = {**(profile or {}), **{k: session[k] for k in ("wish", "origin") if session.get(k)}}
    asked = detect_theme(text)
    theme = asked or str(profile.get("wish") or "").strip() or None
    generic = domain.is_generic_wish(theme)
    conditions = extract_conditions(original, session.get("conditions"))
    if not clarification:
        clarification = conditions.get("date_clarification") or ""
    district = explicit_district or (None if detect_origin(text) or scope["anywhere"] else session.get("district"))
    provided_origin = detect_origin(text)
    origin_text = provided_origin or ("" if scope["ignore_origin"] or session.get("ignore_origin") else str(profile.get("origin") or "").strip())
    if scope["ignore_origin"]:
        origin_text = ""
    ignore_origin = scope["ignore_origin"] or (bool(session.get("ignore_origin")) and not provided_origin)
    matched_origin = origin_index.match_origin(origin_text)

    named_list = mentioned_temples(text)[:3]
    named = named_list[0] if named_list else None
    nearby = any(word in text for word in ("附近", "就近", "越近", "近一点", "近点", "离我近"))
    nearby = nearby or (bool(session.get("nearby")) and not any(word in text for word in ("不怕远", "远一点", "专程")))
    if scope["ignore_origin"]:
        nearby = False
    location_optional = scope["ignore_origin"] or (bool(session.get("location_optional")) and not nearby) or any(
        word in text for word in ("哪里都行", "都可以", "不怕远", "专程", "不限距离")
    )
    if not clarification and not named_list and not origin_text and not district and not location_optional and nearby:
        clarification = "可以帮你找适合祈福的地方。你想在北京哪个区域找，或从哪里出发？" if generic else "你想在北京哪里附近找？告诉我大致出发地就可以。"
    rows: list[dict[str, Any]] = []
    if named_list:
        rows = [_compact(t, matched_origin, conditions) for t in named_list]
        mode = "detail" if len(named_list) == 1 else "compare"
    else:
        matches = domain.search_temples(wish_theme=theme, district=district, limit=3,
                                       origin=matched_origin, nearest_first=nearby, conditions=conditions)
        rows = [_compact(t, matched_origin, conditions) for t in matches]
        mode = "recommend"

    if generic and mode == "recommend":
        for row in rows:
            row["wish_themes"] = []
            row["halls"] = []
    if conditions.get("visit_date") or any(word in text for word in ("预约", "买票", "购票", "门票", "放票")):
        for row in rows:
            row["booking_guidance"] = booking_guidance(domain.get_temple(row["name"]), conditions.get("visit_date") or "")
            row["booking_guidance"]["show_availability_note"] = any(word in text for word in ("余票", "还有票", "剩余名额", "能约到"))
    if clarification:
        rows = []

    payload = {
        "clarification": clarification,
        "scope_note": (
            f"先按{district or '北京'}范围推荐，暂不按出发距离比较。" if not origin_text else ""
        ),
        "query": {
            "conditions": conditions,
            "ignore_origin": ignore_origin,
            "message_theme": theme,
            "generic_wish": generic,
            "district": district,
            "named_temple": named["name"] if named else None,
            "named_temples": [t["name"] for t in named_list],
            "theme_from_message": bool(asked),
            "origin_text": origin_text or None,
            "origin_matched": matched_origin["name"] if matched_origin else None,
        },
        "mode": mode,
        "count": len(rows),
        "meta_note": domain.meta().get("note", ""),
        "items": rows,
        "known_user": {
            k: profile.get(k)
            for k in ("name", "city", "origin", "wish", "companions", "travel_preferences")
            if profile.get(k)
        },
    }
    if generic:
        payload["generic_note"] = (
            f"想为自己或家人祈求{theme}，可以结合参访条件和环境偏好来选择。"
        )
    if origin_text and not matched_origin:
        payload["origin_missing"] = (
            f"出发地「{origin_text}」不在常见地标表里：不要猜坐标或距离，"
            "按区县给候选，并直接说明「你说的地方我这边没有坐标，只能按区县排」。"
        )
    if not rows and not clarification:
        payload["missing"] = (
            "当前资料库未找到同时符合这些条件的候选。请说明受限条件，并询问用户是否愿意调整，避免自动放宽。"
            if any(conditions.get(key) for key in ("no_climbing", "visit_date")) else
            "没有匹配的候选：请如实说明暂未收录，不要凑数，也不要编造寺庙。"
        )

    if not rows and not clarification and district:
        local_places = [t for t in domain.all_temples() if t.get("district") == district and t.get("visitable")]
        payload["scope_summary"] = {
            "district": district,
            "recorded_places": [{"name": t["name"], "type": t.get("status_label"),
                                 "note": t.get("recommend_note", "")} for t in local_places[:3]],
        }
        names = "、".join(t["name"] for t in local_places[:3])
        detail = f"目前收录了{names}等参观场所。" if names else "该区目前收录较少。"
        payload["empty_result_reply"] = (
            f"{district}在当前资料库中，暂未找到同时符合本次祈福和出行条件的候选。{detail}"
            "你可以继续了解这些场所的参观信息，或放宽区域后再比较祈福地点。"
        )

    block = (
        "\n\n" + TEMPLE_DATA_RULE + "\n<temple_data>\n"
        + escape(json.dumps(payload, ensure_ascii=False), quote=False)
        + "\n</temple_data>"
    )
    next_session = {
        "wish": theme or "", "origin": origin_text, "nearby": nearby, "district": district,
        "location_optional": location_optional, "ignore_origin": ignore_origin,
        "conditions": conditions, "visit_date": conditions.get("visit_date") or "",
        "candidates": [t["id"] for t in named_list] if named_list else [t["id"] for t in matches],
        "focus": named["id"] if named and len(named_list) == 1 else "",
    }
    if clarification:
        next_session["candidates"] = list(session.get("candidates") or [])
        next_session["focus"] = session.get("focus") or ""
    return {"payload": payload, "block": block, "session": next_session,
            "resolved_message": text}


def temple_context(message: str, profile: dict[str, Any] | None = None) -> str:
    """Prompt block only (kept for callers that do not verify citations)."""
    built = build_temple_context(message, profile)
    return built["block"] if built else ""


def remember_temple_fields(user_id: str, message: str) -> list[str]:
    """Persist wish / origin / companions / travel preferences said by the user.

    The user chose "remember me across conversations"; the memory card shows and
    edits these fields, and forget removes them. Only explicit statements are
    stored — inference is not written as fact.
    """
    from app import db

    patch: dict[str, Any] = {}
    theme = detect_theme(message)
    if theme:
        patch["wish"] = theme
    origin = detect_origin(message)
    if origin:
        patch["origin"] = origin
    companions = detect_companions(message)
    if companions:
        patch["companions"] = companions
    travel = detect_travel_preferences(message)
    if travel:
        patch["travel_preferences"] = travel
    if not patch:
        return []
    try:
        db.merge_and_save(user_id, patch)
    except Exception:  # noqa: BLE001 - memory write must never break a reply
        return []
    return sorted(patch)
