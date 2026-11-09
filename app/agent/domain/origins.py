"""常见出发地坐标表 + 距离计算。

只做两件事：
1. 把用户说的出发地（自由文本）匹配到「常见出发地」里的一条；
2. 用 haversine 算直线距离（公里）。

匹配不到就返回 ``None``，调用方必须诚实退回「按区县」——不猜坐标。
坐标来源见 ``origins.json`` 的 ``source`` 字段（维基百科 / 维基数据）。
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

_PATH = Path(__file__).resolve().parent / "origins.json"

# 北京大致范围，用来挡住明显的错误坐标（数据自检 + 测试用）
BEIJING_BBOX = (39.4, 41.1, 115.3, 117.6)  # lat_min, lat_max, lng_min, lng_max


def in_beijing_bbox(lat: float | None, lng: float | None) -> bool:
    if lat is None or lng is None:
        return False
    lat_min, lat_max, lng_min, lng_max = BEIJING_BBOX
    return lat_min <= float(lat) <= lat_max and lng_min <= float(lng) <= lng_max


@lru_cache(maxsize=1)
def load_origins() -> list[dict[str, Any]]:
    with _PATH.open(encoding="utf-8") as fh:
        return json.load(fh)["origins"]


def meta() -> dict[str, Any]:
    with _PATH.open(encoding="utf-8") as fh:
        return json.load(fh)["meta"]


def all_origins() -> list[dict[str, Any]]:
    return list(load_origins())


def match_origin(text: str) -> dict[str, Any] | None:
    """把「国贸」「我在五道口」「从西二旗出发」匹配到一条常见出发地。

    取最长命中，避免「西站」命中「北京西站」时被更短的词抢走。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    compact = raw.replace(" ", "")
    best: dict[str, Any] | None = None
    best_len = 0
    for item in load_origins():
        for name in [item["name"], *item.get("aliases", [])]:
            key = str(name).replace(" ", "")
            if key and key in compact and len(key) > best_len:
                best, best_len = item, len(key)
    return best


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点直线距离（公里）。用于「就近」排序，不是实际行车距离。"""
    r = 6371.0088
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = p2 - p1
    dlambda = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_from(origin: dict[str, Any] | None, lat: float | None, lng: float | None) -> float | None:
    """出发地到某点的直线距离；缺任何一方坐标就返回 None（调用方不得编数）。"""
    if not origin or lat is None or lng is None:
        return None
    km = haversine_km(origin["lat"], origin["lng"], lat, lng)
    return round(km, 1)
