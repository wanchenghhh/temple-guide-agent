"""推荐/详情卡片的视图模型（后端 → 前端）。

设计原则与数据层一致：卡片只是把**已经注入过、已经核过**的资料换个长相，
不新增任何事实。所以：

* 候选上限 3，和检索层一致；
* 不可推荐（遗址 / 不开放 / 文化市场）的条目直接不出现；
* 每个心愿都带「说法类型」，folk 必须在卡片上标出来；
* 来源只放真链接；没有就写未核实，不留空壳；
* 距离只给直线距离，并带「非行车」标注；没有坐标就不给数字。
"""

from __future__ import annotations

from typing import Any

EVIDENCE_SHORT = {
    "reference": "文献记载",
    "folk": "民间口碑",
    "official": "官方",
    "media": "媒体",
}
MAX_ITEMS = 3


def _sources(item: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for src in item.get("sources", []) or []:
        url = str(src.get("url") or "")
        if not url.startswith("http"):
            continue
        out.append({"url": url, "publisher": str(src.get("publisher") or "")})
    return out[:3]


def _item(item: dict[str, Any]) -> dict[str, Any]:
    wishes = []
    for wish in (item.get("wish_themes") or [])[:3]:
        wishes.append({
            "theme": wish.get("theme", ""),
            "claim": wish.get("claim", ""),
            "claim_label": wish.get("claim_label", ""),
            "evidence": EVIDENCE_SHORT.get(str(wish.get("claim_evidence")), "民俗说法"),
            "basis": wish.get("basis", ""),
        })
    distance = item.get("distance_km")
    return {
        "name": item.get("name", ""),
        "district": item.get("district", ""),
        "place_type": item.get("status_label", ""),
        "prayable": item.get("status") == "religious_site",
        "recommend_note": item.get("recommend_note", ""),
        "distance_km": distance if isinstance(distance, (int, float)) else None,
        "distance_note": item.get("distance_note", ""),
        "wishes": wishes,
        "open_note": item.get("open_note", ""),
        "closure": list(item.get("closure_rule") or [])[:3],
        "sources": _sources(item),
        "sources_status": item.get("sources_status", "unverified"),
    }


def _reviews(reviews: dict[str, Any] | None, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """把公开分享挂到卡片上：只给标题/站点/日期/链接/截断摘要。"""
    if not reviews:
        return None
    names = {i["name"] for i in items}
    if reviews.get("temple") and reviews["temple"] not in names:
        return None            # 分享不是这几座寺的，宁可不展示
    rows = []
    for raw in (reviews.get("items") or [])[:3]:
        if not str(raw.get("url") or "").startswith("http"):
            continue
        rows.append({
            "title": str(raw.get("title") or "")[:120],
            "site": str(raw.get("site") or ""),
            "published": str(raw.get("published") or ""),
            "url": str(raw["url"]),
            "snippet": str(raw.get("snippet") or "")[:160],
            "ugc": str(raw.get("kind") or "") == "ugc",
        })
    return {
        "temple": reviews.get("temple", ""),
        "theme": reviews.get("theme", ""),
        "items": rows,
        "empty_note": "" if rows else "没有找到相关的公开分享",
    }


def build_card(payload: dict[str, Any] | None,
               reviews: dict[str, Any] | None = None,
               travel: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """把注入的资料变成卡片；没有可展示的内容就返回 None（不造空卡）。"""
    if not payload:
        return None
    mode = payload.get("mode") or "recommend"
    items = [_item(i) for i in (payload.get("items") or [])[:MAX_ITEMS]]
    if not items:
        return None
    query = payload.get("query") or {}
    kind = {"detail": "temple_detail", "compare": "temple_compare"}.get(mode, "temple_recommend")
    wish = query.get("message_theme") or ""
    # 详情卡只在用户这次自己说了心愿时才标心愿；
    # 否则会拿记忆里的旧心愿给一座寺贴标签（问「雍和宫求什么」标成「姻缘」就很怪）。
    if kind == "temple_detail" and not query.get("theme_from_message"):
        wish = ""
    return {
        "kind": kind,
        "wish": wish,
        "generic_wish": bool(query.get("generic_wish")),
        "origin_name": query.get("origin_matched") or "",
        "origin_note": payload.get("origin_note", ""),
        "generic_note": payload.get("generic_note", ""),
        "items": items,
        "missing": payload.get("missing", ""),
        "has_unverified_sources": any(i["sources_status"] != "verified" for i in items),
        "reviews": _reviews(reviews, items),
        "travel": travel,
    }
