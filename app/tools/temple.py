"""Temple-guide tools (schema v2): curated data, verified sources, honest gaps.

All three tools are ``read`` risk: they never write and never call the network.

Output contract (shared)::

    {"trust": "curated_reference", "disclaimer": str, "data": {...}}

Every row separates two kinds of evidence:
* ``place_facts`` — what the place *is* (checkable: 官方/文献 + URL);
* ``wish.claim`` — what people *pray for* there (民俗用法, ``claim_evidence``), never
  upgraded to documented fact just because the hall is documented.

``finder_hint`` lists channels to ask (微信公众号…) and is **not** a source:
those URLs cannot be verified programmatically.

The upper layer must:
* present a ``folk`` claim as 民间口碑, never as fact;
* say so when ``sources_status == "unverified"`` instead of implying a citation;
* never recommend a row with ``recommendable: false`` for a wish.
"""

from __future__ import annotations

from typing import Any

from app.agent.domain import origins as origin_index
from app.agent.domain import temples as domain
from app.agent.tool_registry import tool

TRUST = "curated_reference"
EVIDENCE_LABEL = {
    "official": "官方/文博机构资料",
    "reference": "百科/文献资料",
    "folk": "民间口碑（无权威依据）",
}


def _wrap(data: dict[str, Any]) -> dict[str, Any]:
    return {"trust": TRUST, "disclaimer": domain.meta().get("note", ""), "data": data}


def _field(value: Any, placeholder: str = "暂未查到") -> Any:
    """Empty curated field must be reported honestly, never padded."""
    if value in (None, "", [], {}):
        return placeholder
    return value


def _wish_rows(temple: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for w in temple.get("wish_themes", []):
        rows.append(
            {
                "theme": w["theme"],
                "role": w.get("role"),
                "claim": w.get("claim", ""),
                "claim_evidence": w.get("claim_evidence"),
                "claim_label": domain.wish_claim_label(w),
                "basis": w.get("basis", ""),
                "basis_source": w.get("basis_source", ""),
            }
        )
    return rows


def _distance(origin: dict[str, Any] | None, temple: dict[str, Any]) -> dict[str, Any]:
    """直线距离，取不到就明说（不猜坐标）。"""
    if origin is None:
        return {"distance_km": None, "distance_note": "未提供可识别的出发地"}
    km = origin_index.distance_from(origin, temple.get("lat"), temple.get("lng"))
    if km is None:
        return {"distance_km": None,
                "distance_note": f"{temple['name']}暂未取到可靠坐标，不能说距离"}
    return {"distance_km": km,
            "distance_note": f"距{origin['name']}直线约 {km} 公里（非行车距离）"}


def _brief(temple: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": temple["id"],
        "name": temple["name"],
        "district": temple["district"],
        "status": temple["status"],
        "status_label": domain.STATUS_LABELS.get(temple["status"], temple["status"]),
        "wish_recommendable": temple.get("wish_recommendable", False),
        "visitable": temple.get("visitable", False),
        "religious_registered": temple.get("religious_registered"),
        "open_status": temple.get("open_status", "unverified"),
        "open_note": temple.get("open_note", ""),
        "closure_rule": temple.get("closure_rule", []),
        "recommend_note": temple.get("recommend_note", ""),
        "sect": temple.get("sect", ""),
        "wish_themes": _wish_rows(temple),
        "generic_wish_ok": temple.get("generic_wish_ok", False),
        "one_line": temple.get("overview", ""),
        "sources": temple.get("sources", []),
        "sources_status": temple.get("sources_status", "unverified"),
        "finder_hint": temple.get("finder_hint", []),
        "checked_at": temple.get("checked_at", ""),
    }


@tool(
    "temple_search",
    description="按心愿、区域或关键词检索北京寺庙候选。 Search curated Beijing temples by wish theme, district or keyword.",
    when_to_use="用户有一个具体心愿（姻缘/求子/学业/事业/财运/健康）、区域，或想找某类寺庙时使用。 Use when the user asks which temple suits a wish or area.",
    when_not_to_use="用户只说平安等泛化诉求时不要当排序用；指定了具体寺庙改用 temple_detail。 Do not pad candidates.",
    timeout=10,
)
def temple_search(
    wish_theme: str | None = None,
    district: str | None = None,
    keyword: str | None = None,
    origin: str | None = None,
    limit: int = 3,
    user_id: str = "",
) -> dict:
    theme = (wish_theme or "").strip()
    generic = domain.is_generic_wish(theme)
    matched_origin = origin_index.match_origin(origin or "")
    matches = domain.search_temples(
        wish_theme=theme, district=district, keyword=keyword, limit=limit,
        origin=matched_origin,
    )
    items = []
    for t in matches:
        row = _brief(t)
        row.update(_distance(matched_origin, t))
        items.append(row)
    if not items:
        note = "没有匹配的候选，请如实说明，不要凑数。"
    elif generic:
        note = (
            f"用户希望「{theme}」，请承接祈福需要，"
            "按可参访情况、距离与氛围说明推荐理由，不要暗示哪座更灵。"
        )
    else:
        note = "结果按「是否可上香 → 说法是否有文献支撑 → 能否指向具体殿宇」排序；理由里必须说清哪部分是场所事实、哪部分是民俗说法。"
    return _wrap(
        {
            "query": {"wish_theme": wish_theme, "district": district,
                      "keyword": keyword, "origin": origin},
            "origin": ({"name": matched_origin["name"], "lat": matched_origin["lat"],
                        "lng": matched_origin["lng"]} if matched_origin else None),
            "origin_note": ("" if matched_origin else
                            "出发地不在常见地标表里：不要猜坐标，按区县给候选并说明原因"),
            "generic_wish": generic,
            "count": len(items),
            "items": items,
            "note": note,
        }
    )


@tool(
    "temple_detail",
    description="读取一座寺庙的结构化详情与依据。 Read one temple's structured detail with evidence.",
    when_to_use="用户想了解某座寺庙的历史、供奉、殿宇、许愿说法、氛围、交通与开放信息时使用。 Use to explain a named temple.",
    when_not_to_use="不替代官方公告；文博点不是上香场所，必须说明。 Do not treat opening hours as final.",
    timeout=10,
)
def temple_detail(temple: str, origin: str | None = None, user_id: str = "") -> dict:
    t = domain.get_temple(temple)
    if t is None:
        return _wrap(
            {
                "found": False,
                "query": temple,
                "note": "资料库中没有这座寺庙，请说明暂未收录，并建议用户到官方渠道核实，不要编造。",
            }
        )
    detail = _brief(t)
    detail.update(_distance(origin_index.match_origin(origin or ""), t))
    detail.update(
        {
            "found": True,
            "address_hint": _field(t.get("address_hint")),
            "overview": _field(t.get("overview")),
            "deities": _field(t.get("deities")),
            "halls": [
                {
                    "name": h["name"],
                    "deity": h.get("deity", ""),
                    "themes": h.get("themes", []),
                    "evidence_label": EVIDENCE_LABEL.get(str(h.get("evidence_type")), "未核实"),
                    "source_url": h.get("source_url", ""),
                }
                for h in t.get("halls", [])
            ],
            "atmosphere": _field(t.get("atmosphere")),
            "place_facts": [
                {
                    "text": f["text"],
                    "source": f.get("source", ""),
                    "evidence_type": f.get("evidence_type", ""),
                    "checked_at": f.get("checked_at", ""),
                }
                for f in t.get("place_facts", [])
            ],
            "transport": _field(t.get("transport")),
            "accessibility": _field(t.get("accessibility")),
            "open_status": t.get("open_status", "unverified"),
            "closure_rule": t.get("closure_rule", []),
            "visit_note": _field(t.get("visit_note")),
            "missing_fields": [
                k
                for k in (
                    "address_hint", "overview", "deities", "atmosphere",
                    "transport", "accessibility", "visit_note",
                )
                if not t.get(k)
            ]
            + ([] if t.get("halls") else ["halls"])
            + ([] if t.get("place_facts") else ["place_facts"])
            + ([] if t.get("sources") else ["sources"]),
        }
    )
    return _wrap(detail)


@tool(
    "temple_trip_plan",
    description="给出去某座寺庙的路线、耗时、天气（v1 示例数据）。 Draft a route and weather note for a temple visit (v1 sample data).",
    when_to_use="用户询问怎么去、多久到、当天天气等行前信息时使用。 Use for pre-visit logistics.",
    when_not_to_use="v1 为示例数据，不得当作实时路况或预报；不可推荐的场所不要生成出行计划。 Not live data.",
    timeout=10,
)
def temple_trip_plan(
    temple: str,
    origin: str | None = None,
    travel_mode: str = "公共交通",
    visit_date: str | None = None,
    user_id: str = "",
) -> dict:
    t = domain.get_temple(temple)
    if t is None:
        return _wrap(
            {
                "found": False,
                "query": temple,
                "note": "资料库中没有这座寺庙，无法生成路线；请说明并建议用户用地图 App 查询。",
            }
        )
    blocked = t.get("recommend_note", "") if not t.get("wish_recommendable") else ""

    # 有 key 就用实时数据；没有/失败就明确标示例数据（不冒充实时）
    from app.agent.domain import origins as origin_index
    from app.tools import travel

    point = origin_index.match_origin(origin or "")
    live_route = None
    live_weather = None
    if travel.enabled():
        dest = None
        if t.get("lat") is not None and t.get("lng") is not None:
            dest = (t["lng"], t["lat"])
        origin_point = (point["lng"], point["lat"]) if point else None
        if origin_point is None and (origin or "").strip():
            geo = travel.geocode(origin or "")
            if geo.get("status") == "ok":
                origin_point = (geo["lng"], geo["lat"])
        if origin_point and dest:
            got = travel.route(origin_point, dest,
                               mode="driving" if travel_mode.startswith("自驾") else "transit")
            live_route = got if got.get("status") == "ok" else None
        if dest:
            got = travel.weather(*dest)
            if got.get("status") == "ok":
                live_weather = travel.pick_forecast(got.get("forecasts") or [], visit_date or "")

    return _wrap(
        {
            "found": True,
            "temple": t["name"],
            "wish_recommendable": t.get("wish_recommendable", False),
            "visitable": t.get("visitable", False),
            "blocked_reason": blocked,
            "origin": _field(origin, "未提供（应先问城市或区域，不要猜坐标）"),
            "travel_mode": travel_mode,
            "visit_date": _field(visit_date, "未指定"),
            "route_summary": t.get("transport") or "暂未查到",
            **_distance(origin_index.match_origin(origin or ""), t),
            "accessibility": t.get("accessibility") or "暂未查到",
            "open_status": t.get("open_status", "unverified"),
            "closure_rule": t.get("closure_rule", []),
            "live_route": live_route,
            "live_weather": live_weather,
            "map_link": ("地图链接见路线来源" if live_route else
                         "暂未接入实时地图，请说明并建议用户在地图 App 中搜索寺庙名称"),
            "weather": (live_weather or "暂未接入实时天气，请说明并提醒用户临行复核"),
            "live_data": bool(live_route or live_weather),
            "sources": t.get("sources", []),
            "note": "以上路线与天气为 v1 示例，非实时数据；必须提醒用户临行复核。",
        }
    )
