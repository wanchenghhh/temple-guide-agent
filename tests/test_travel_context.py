"""行前数据（高德路线 / 和风天气）：只在问行前时请求，失败就如实说查不到。

不联网：所有 HTTP 都通过注入了 fetch 的接口层，或直接替换 travel 的函数。
"""

import json

import pytest

from app.agent import travel_context as tcx
from app.tools import travel


ROUTE_OK = {"status": "ok", "mode": "transit", "mode_label": "公交/地铁",
            "distance_km": 8.1, "duration_min": 46, "options": 3,
            "source": "高德路径规划", "checked_at": "2026-11-09 13:45"}
WEATHER_OK = {"status": "ok", "location": "116.41,39.95",
              "forecasts": [{"date": "2026-11-09", "text": "晴", "temp_min": -3,
                             "temp_max": 12, "wind": "西南风3级"},
                            {"date": "2026-11-10", "text": "多云", "temp_min": -1,
                             "temp_max": 15, "wind": "北风2级"}],
              "source": "和风天气", "checked_at": "2026-11-09 13:45"}


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("TRAVEL_ENABLED", "1")
    travel.clear_cache()
    monkeypatch.setattr(travel, "enabled", lambda: True)
    monkeypatch.setattr(travel, "route", lambda *a, **k: dict(ROUTE_OK))
    monkeypatch.setattr(travel, "weather", lambda *a, **k: dict(WEATHER_OK))
    monkeypatch.setattr(travel, "geocode", lambda *a, **k: {
        "status": "ok", "name": "三里河", "lng": 116.33, "lat": 39.92,
        "formatted": "北京市西城区三里河", "source": "高德地理编码", "checked_at": "x"})
    yield


def test_only_travel_turns_trigger_requests():
    assert tcx.is_travel_turn("从国贸去雍和宫怎么走")
    assert tcx.is_travel_turn("妙峰山明天天气怎么样")
    assert not tcx.is_travel_turn("妙峰山求子灵不灵")     # 口碑问题不走行前
    assert not tcx.is_travel_turn("雍和宫求什么")         # 没提行前
    assert not tcx.is_travel_turn("")


def test_payload_has_route_and_weather_with_timestamps():
    payload = tcx.build_travel_payload("从国贸去雍和宫怎么走")
    assert payload["route"]["duration_min"] == 46
    assert payload["weather"]["chosen"]["date"] == "2026-11-09"
    card = tcx.travel_card(payload)
    assert card["route"]["checked_at"] and card["route"]["source"]
    assert card["weather"]["text"] == "晴"
    block = tcx.render_travel_block(payload)
    assert "<travel_data>" in block and "以出行时实际路况为准" in block


def test_unknown_origin_falls_back_to_geocoding():
    payload = tcx.build_travel_payload("从三里河南边去雍和宫怎么走")
    assert payload["origin"]["source"] == "高德地理编码"
    assert payload["route"] is not None


def test_geocode_failure_means_no_route_but_weather_still_ok(monkeypatch):
    monkeypatch.setattr(travel, "geocode", lambda *a, **k: {"status": "not_found", "reason": "无结果"})
    payload = tcx.build_travel_payload("从三里河南边去雍和宫怎么走")
    assert payload["route"] is None
    assert payload["weather"] is not None
    assert any("无法定位" in note for note in payload["notes"])


def test_route_failure_is_reported_not_invented(monkeypatch):
    monkeypatch.setattr(travel, "route", lambda *a, **k: {"status": "error", "reason": "quota"})
    payload = tcx.build_travel_payload("从国贸去雍和宫怎么走")
    assert payload["route"] is None
    assert any("路线查询失败" in note for note in payload["notes"])
    block = tcx.render_travel_block(payload)
    assert "不要自己估算" in block


def test_date_outside_forecast_is_explicit(monkeypatch):
    payload = tcx.build_travel_payload("妙峰山12月31日天气怎么样")
    assert payload["weather"]["chosen"] is None
    assert any("超出预报范围" in note for note in payload["notes"])


def test_disabled_travel_returns_nothing(monkeypatch):
    monkeypatch.setattr(travel, "enabled", lambda: False)
    assert tcx.build_travel_payload("从国贸去雍和宫怎么走") is None


def test_temple_without_coordinates_uses_geocoding_or_says_so(monkeypatch):
    # 云居寺在资料库里没有坐标
    monkeypatch.setattr(travel, "geocode", lambda *a, **k: {"status": "error", "reason": "x"})
    payload = tcx.build_travel_payload("云居寺怎么去")
    assert payload is not None
    assert "路线与天气都查不到" in " ".join(payload.get("notes") or [])
    assert payload.get("route") is None and payload.get("weather") is None


@pytest.mark.parametrize("message,mode", [
    ("从国贸开车去雍和宫", "driving"),
    ("走过去行吗", "walking"),
    ("坐地铁怎么去", "transit"),
])
def test_travel_mode_is_read_from_message(message, mode):
    assert tcx._mode(message) == mode


def test_visit_date_parsing():
    from datetime import date, timedelta

    assert tcx._visit_date("今天去") == date.today().isoformat()
    assert tcx._visit_date("明天去") == (date.today() + timedelta(days=1)).isoformat()
    assert tcx._visit_date("3月5号") == f"{date.today().year}-03-05"
    assert tcx._visit_date("想去") == ""


def test_chat_injects_travel_block_and_card(fake_llm):
    from app import data_access
    from app.agent.subgraphs import chat as chat_mod

    fake_llm.reply = "从国贸过去坐地铁约 46 分钟（接口预计），天气晴 -3~12℃。"
    with data_access.user_scope("u_travel_chat"):
        out = chat_mod.node_chat({
            "user_id": "u_travel_chat",
            "message": "从国贸去雍和宫怎么走",
            "thread_id": "t-travel",
        })
    card = out["temple_card"]
    assert card["travel"]["route"]["duration_min"] == 46
    assert card["travel"]["weather"]["text"] == "晴"
    # 引用校验把行前数据算进可核范围，不该被当成编造
    assert "我在资料里没核到出处" not in out["messages"][0]["content"]


def test_trip_plan_tool_uses_live_data_when_enabled():
    from app import data_access
    from app.agent import tool_registry

    tool_registry.ensure_defaults()
    with data_access.user_scope("u_trip_live"):
        result = tool_registry.invoke_tool(
            "temple_trip_plan", {"temple": "雍和宫", "origin": "国贸"}, {})
    data = result["data"]
    assert data["live_data"] is True
    assert data["live_route"]["duration_min"] == 46
