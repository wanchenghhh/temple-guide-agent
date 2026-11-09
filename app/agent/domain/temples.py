"""Temple domain data loader & search (schema v2).

Loads the curated Beijing temple knowledge base (app/agent/domain/temples.json)
and exposes read-only query helpers used by the temple-guide tools.

Schema v2 rules the caller must respect:
* ``status`` decides what the place *is*: 宗教活动场所 / 文博点 / 景区·民间信仰 /
  遗址 / 不开放 / 文化市场. Only the first kind is a place to burn incense.
* ``visitable`` = 能不能去参观; ``wish_recommendable`` = 能不能作为许愿推荐。
  The two are separate so "可推荐" never means two things at once.
* ``religious_registered`` = 是否登记宗教活动场所（True/False/None=待核），
  never asserted without a source.
* every wish carries ``evidence_type``: official > reference > folk. A ``folk``
  claim must be presented as 民间口碑, never as fact.
* 平安 and other generic wishes are NOT tags in the data. They are handled by
  :data:`GENERIC_WISHES` as a default branch that does not score temples.
* unrecognised themes return an empty list: candidates are never padded.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agent.domain import origins

_DATA_PATH = Path(__file__).resolve().parent / "temples.json"

# Canonical wish themes we understand (used for matching & the prompt contract).
WISH_THEMES = ("姻缘", "求子", "学业", "事业", "财运", "健康")

# Generic wishes never rank temples: they mean "I want to pray, generally".
GENERIC_WISHES = ("平安", "顺遂", "消灾", "祈福", "general")

EVIDENCE_STRENGTH = {"official": 3, "reference": 2, "folk": 1}

# 依据分两层：claim 是「人们来求什么」的民俗说法；basis 是「场所事实」（哪个殿、供什么）。
CLAIM_LABELS = {
    "reference": "文献有记载的说法",
    "folk": "民间口碑（无权威依据）",
}

# 场所类型：寺院/道观属于「宗教活动场所」，博物馆属于「文博点」，
# 景区（含民间信仰庙宇）单独一类——三者能不能上香完全不同。
STATUS_LABELS = {
    "religious_site": "宗教活动场所",
    "heritage": "文博点",
    "scenic": "景区/民间信仰",
    "relic": "遗址",
    "closed": "不开放",
    "market": "文化市场",
}

# 能上香的场所类型（用于排序与文案）
PRAYER_STATUSES = ("religious_site",)


def _load_raw() -> dict[str, Any]:
    with _DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def load_dataset() -> dict[str, Any]:
    return _load_raw()


def meta() -> dict[str, Any]:
    return load_dataset()["meta"]


def all_temples() -> list[dict[str, Any]]:
    return list(load_dataset()["temples"])


def get_temple(identifier: str) -> dict[str, Any] | None:
    """Look up by id, exact name, or alias (case-insensitive)."""
    key = (identifier or "").strip().lower()
    if not key:
        return None
    for t in all_temples():
        if t["id"].lower() == key:
            return t
        if t["name"].lower() == key:
            return t
        for a in t.get("aliases", []):
            if a.lower() == key:
                return t
    return None


def is_generic_wish(theme: str | None) -> bool:
    return (theme or "").strip() in GENERIC_WISHES


def themes_of(temple: dict[str, Any]) -> list[str]:
    return [w["theme"] for w in temple.get("wish_themes", [])]


def wish_evidence(temple: dict[str, Any], theme: str) -> dict[str, Any] | None:
    return next((w for w in temple.get("wish_themes", []) if w["theme"] == theme), None)


def wish_claim_label(wish: dict[str, Any]) -> str:
    return CLAIM_LABELS.get(str(wish.get("claim_evidence")), "民俗说法")


def has_place_facts(temple: dict[str, Any]) -> bool:
    return bool(temple.get("place_facts"))


def halls_for(temple: dict[str, Any], theme: str) -> list[dict[str, Any]]:
    return [h for h in temple.get("halls", []) if theme in h.get("themes", [])]


def search_temples(
    wish_theme: str | None = None,
    district: str | None = None,
    keyword: str | None = None,
    limit: int = 3,
    include_unrecommendable: bool = False,
    origin: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` temples matching wish theme / district / keyword.

    A concrete wish only matches temples that document it (殿宇/神像 or a cited
    source), strongest evidence first. A generic wish (平安 etc.) does not score
    at all: it groups by "can you actually pray here" and then orders by distance,
    so it can never pretend to be a ranking. Nothing is padded when there is no match.
    """
    theme = (wish_theme or "").strip()
    generic = is_generic_wish(theme)
    dist = (district or "").strip()
    kw = (keyword or "").strip().lower()

    scored: list[tuple[int, float, int, dict[str, Any]]] = []
    inf = float("inf")
    for order, t in enumerate(all_temples()):
        if not include_unrecommendable and not t.get("wish_recommendable", False):
            continue
        score = 0
        # 能上香的地方优先：文博点/景区可参观，但不是上香许愿的地方。
        # 这条对「平安」这类默认项同样生效——用户说要求平安，先给能上香的，
        # 再在同类里按距离排，否则最近的三座可能全是博物馆。
        if t.get("status") in PRAYER_STATUSES:
            score += 3
        elif t.get("status") == "scenic":
            score += 1
        if theme and not generic:
            ev = wish_evidence(t, theme)
            if ev is None:
                continue
            # 主诉求 > 次诉求；说法有文献支撑 > 纯民间口碑；能指向具体殿宇的加分
            score += 6 if ev.get("role") == "primary" else 3
            score += EVIDENCE_STRENGTH.get(str(ev.get("claim_evidence")), 0) * 2
            if ev.get("basis"):
                score += 2
            if halls_for(t, theme):
                score += 1
        if dist and dist in (t.get("district") or ""):
            score += 2
        if kw:
            hay = " ".join(
                [t.get("name", ""), t.get("overview", "")]
                + list(t.get("aliases", []))
                + list(t.get("deities", []))
            ).lower()
            if kw in hay:
                score += 2
        km = origins.distance_from(origin, t.get("lat"), t.get("lng"))
        km_key = inf if km is None else km

        if theme and not generic:
            scored.append((score, km_key, order, t))
        elif dist or kw:
            if score > 0:
                scored.append((score, km_key, order, t))
        else:
            # 默认项也带上「能不能上香」的分，再按距离排
            scored.append((score, km_key, order, t))

    # 依据强度优先；同分再比距离（没坐标的排后面）；最后按数据顺序稳定输出。
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [t for _, _, _, t in scored[: max(1, min(int(limit or 3), 5))]]
