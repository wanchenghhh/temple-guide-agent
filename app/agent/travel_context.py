"""行前准备上下文：把高德路线与和风天气安全地交给模型。

只有在「问行前信息」时才请求（``is_travel_turn``）：

* 有出发地 → 路线；出发地不认识就先用高德地理编码，编不出坐标就不给距离；
* 有寺庙坐标 → 天气（按用户说的日期挑，超出预报范围如实说查不到）；
* 接口失败/额度用尽 → 注入「查不到」，不让模型自由发挥；
* 所有数字都带数据时间与来源，回答里必须说「以出行时实际路况/天气为准」。
"""

from __future__ import annotations

import json
from html import escape
from typing import Any, Optional

from app.agent import temple_context as tc
from app.agent.domain import origins as origin_index
from app.tools import travel
from app.agent.domain.visit_dates import parse_visit_date

TRAVEL_WORDS = (
    "怎么去", "怎么走", "多久", "多远", "路线", "地铁", "公交", "打车", "自驾",
    "开车", "停车", "天气", "下雨", "冷不冷", "热不热", "气温", "几点到", "路程",
)
TRAVEL_RULE = (
    "【行前数据】下面是地图与天气接口返回的实时信息，带数据时间。"
    "路线距离与耗时只能说成「接口给的预计」，并提醒以出行时实际路况为准；"
    "天气只能说预报，提醒出发前一天再看。数据里的数字可以直接引用；"
    "没有提供的那一项（比如没给出发地）就说查不到，不要自己估算。"
)


def is_travel_turn(message: str) -> bool:
    text = (message or "").strip()
    if not text or tc.mentioned_temple(text) is None:
        return False
    return any(word in text for word in TRAVEL_WORDS)


def _mode(message: str) -> str:
    text = message or ""
    if any(word in text for word in ("开车", "自驾", "驾车", "停车")):
        return "driving"
    if any(word in text for word in ("走路", "步行", "走过去")):
        return "walking"
    return "transit"


def _visit_date(message: str) -> str:
    return parse_visit_date(message)['date']


def _origin_point(origin_text: str) -> tuple[Optional[dict[str, Any]], Optional[tuple[float, float]]]:
    """先查常见地标表，再退回高德地理编码。"""
    known = origin_index.match_origin(origin_text)
    if known is not None:
        return ({"name": known["name"], "source": "常见出发地坐标表",
                 "lng": known["lng"], "lat": known["lat"]},
                (known["lng"], known["lat"]))
    if not origin_text:
        return None, None
    geo = travel.geocode(origin_text)
    if geo.get("status") != "ok":
        return ({"name": origin_text, "source": "地理编码失败",
                 "note": geo.get("reason") or geo.get("status")}, None)
    return ({"name": geo.get("formatted") or origin_text, "source": geo.get("source", ""),
             "lng": geo["lng"], "lat": geo["lat"]},
            (geo["lng"], geo["lat"]))


def build_travel_payload(message: str, profile: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not is_travel_turn(message) or not travel.enabled():
        return None
    temple = tc.mentioned_temple(message)
    if temple is None:
        return None
    profile = profile or {}
    origin_text = tc.detect_origin(message) or str(profile.get("origin") or "").strip()
    parsed_date = parse_visit_date(message)
    if parsed_date['clarification']:
        return None
    visit_date = parsed_date['date'] if parsed_date['mentioned'] else str(profile.get('visit_date') or '')

    payload: dict[str, Any] = {"temple": temple["name"], "origin_text": origin_text,
                               "visit_date": visit_date, "route": None, "weather": None,
                               "notes": []}

    dest = None
    if temple.get("lat") is not None and temple.get("lng") is not None:
        dest = (temple["lng"], temple["lat"])
        payload["temple_point"] = {"lng": temple["lng"], "lat": temple["lat"], "source": "资料库坐标"}
    else:
        geo = travel.geocode(temple["name"])
        if geo.get("status") == "ok":
            dest = (geo["lng"], geo["lat"])
            payload["temple_point"] = {"lng": geo["lng"], "lat": geo["lat"],
                                       "source": geo.get("source", "")}
        else:
            payload["notes"].append("这座寺庙没有坐标，路线与天气都查不到")

    origin_info, origin_point = _origin_point(origin_text)
    payload["origin"] = origin_info
    if origin_text and origin_point is None:
        payload["notes"].append("出发地无法定位，算不出路线；可以只给天气")

    if origin_point and dest:
        mode = _mode(message)
        route = travel.route(origin_point, dest, mode=mode)
        payload["route"] = route if route.get("status") == "ok" else None
        if route.get("status") != "ok":
            payload["notes"].append(f"路线查询失败：{route.get('reason') or route.get('status')}")

    if dest:
        weather = travel.weather(*dest)
        if weather.get("status") == "ok":
            chosen = travel.pick_forecast(weather.get("forecasts") or [], visit_date)
            payload["weather"] = {"forecasts": weather.get("forecasts") or [],
                                  "chosen": chosen,
                                  "source": weather.get("source", ""),
                                  "checked_at": weather.get("checked_at", "")}
            if chosen is None:
                payload["notes"].append("用户说的日期超出预报范围，如实说明查不到")
        else:
            payload["notes"].append(f"天气查询失败：{weather.get('reason') or weather.get('status')}")

    # 有「查不到」的说明也要返回：模型据此如实告诉用户，而不是自己编
    if not payload.get("route") and not payload.get("weather") and not payload.get("notes"):
        return None
    return payload


def render_travel_block(payload: dict[str, Any]) -> str:
    body = {
        "temple": payload.get("temple"),
        "origin": payload.get("origin"),
        "visit_date": payload.get("visit_date") or None,
        "route": payload.get("route"),
        "weather": payload.get("weather"),
        "notes": payload.get("notes"),
    }
    return ("\n\n" + TRAVEL_RULE + "\n<travel_data>\n"
            + escape(json.dumps(body, ensure_ascii=False), quote=False)
            + "\n</travel_data>")


def travel_card(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """卡片上展示的路线/天气（只挑几个字段，避免堆原始 JSON）。"""
    if not payload:
        return None
    route = payload.get("route") or {}
    weather = payload.get("weather") or {}
    chosen = weather.get("chosen") or {}
    return {
        "temple": payload.get("temple", ""),
        "origin": (payload.get("origin") or {}).get("name", ""),
        "route": ({
            "mode": route.get("mode_label", ""),
            "distance_km": route.get("distance_km"),
            "duration_min": route.get("duration_min"),
            "checked_at": route.get("checked_at", ""),
            "source": route.get("source", ""),
        } if route else None),
        "weather": ({
            "date": chosen.get("date", ""),
            "text": chosen.get("text", ""),
            "temp_min": chosen.get("temp_min"),
            "temp_max": chosen.get("temp_max"),
            "wind": chosen.get("wind", ""),
            "checked_at": weather.get("checked_at", ""),
            "source": weather.get("source", ""),
        } if chosen else None),
        "notes": list(payload.get("notes") or []),
    }
