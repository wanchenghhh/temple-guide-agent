"""坐标与「就近」口径：可核坐标、诚实距离、不猜数。

三条不变量（上一轮就是在这里最容易造假）：
1. 坐标必须有出处（维基百科坐标接口 / 维基数据 P625），且落在北京范围内；
2. 取不到坐标就留空，距离必须返回 None，**不许估一个数字**；
3. 距离只能以「直线约 X 公里（非行车距离）」呈现，且证据强度优先于距离。
"""

import json

import pytest

from app.agent import temple_context as tc
from app.agent.domain import origins as oi
from app.agent.domain import temples as domain


@pytest.fixture(scope="module")
def origins():
    return oi.all_origins()


def test_origin_table_is_checkable_and_in_beijing(origins):
    assert len(origins) >= 10
    names = [o["name"] for o in origins]
    assert len(names) == len(set(names))
    aliases = [a for o in origins for a in o.get("aliases", [])]
    assert len(aliases) == len(set(aliases)), "别名不能重复"
    for item in origins:
        assert oi.in_beijing_bbox(item["lat"], item["lng"]), item["name"]
        assert item["source"].startswith("http"), item["name"]
        assert "wikipedia.org" in item["source"] or "wikidata.org" in item["source"], item["name"]


def test_temple_coordinates_are_sourced_or_empty():
    for row in domain.all_temples():
        if row.get("lat") is None:
            # 允许留空，但必须说明为什么，且不能带来源
            assert row.get("coord_note"), row["id"]
            assert not row.get("coord_source"), row["id"]
            continue
        assert oi.in_beijing_bbox(row["lat"], row["lng"]), row["id"]
        assert row["coord_source"].startswith("http"), row["id"]
        assert "wikipedia.org" in row["coord_source"] or "wikidata.org" in row["coord_source"], row["id"]

    # 已知取不到的两座仍然留空，不能为了好看补一个数字
    empty = {r["name"] for r in domain.all_temples() if r.get("lat") is None}
    assert {"云居寺", "和平寺"} <= empty


@pytest.mark.parametrize("text,expected", [
    ("从国贸出发", "国贸"),
    ("我在五道口", "五道口"),
    ("我在北京西站", "北京西站"),
    ("望京这边方便", "望京"),
    ("通州过去", "通州北苑"),
    ("中关村附近", "中关村"),
])
def test_origin_matching(text, expected):
    match = oi.match_origin(text)
    assert match is not None, text
    assert match["name"] == expected


@pytest.mark.parametrize("text", ["三里河南边", "我家", "", "海外", "门头沟山里"])
def test_unknown_origin_is_not_guessed(text):
    assert oi.match_origin(text) is None


def test_distance_is_sane():
    guomao = oi.match_origin("国贸")
    yonghe = domain.get_temple("雍和宫")
    hongluo = domain.get_temple("红螺寺")
    d1 = oi.distance_from(guomao, yonghe["lat"], yonghe["lng"])
    d2 = oi.distance_from(guomao, hongluo["lat"], hongluo["lng"])
    assert 4 <= d1 <= 9, d1          # 国贸→雍和宫 直线约 5.7km
    assert 45 <= d2 <= 70, d2        # 国贸→红螺寺 直线约 54km
    assert d2 > d1
    # 没有坐标就不能返回数字
    assert oi.distance_from(guomao, None, None) is None
    assert oi.distance_from(None, yonghe["lat"], yonghe["lng"]) is None


def test_generic_wish_puts_prayer_venues_first_then_distance():
    """只说平安时，先给能上香的地方，同类里再按距离——否则最近的三座可能全是博物馆。"""
    guomao = oi.match_origin("国贸")
    near = domain.search_temples(wish_theme="平安", limit=4, origin=guomao)
    assert [t["status"] for t in near] == ["religious_site"] * 4, [t["name"] for t in near]
    dists = [oi.distance_from(guomao, t["lat"], t["lng"]) for t in near]
    assert dists == sorted(d for d in dists if d is not None), dists

    # 具体心愿：能上香的宗教活动场所仍然排在文博点前面，哪怕文博点更近
    rows = domain.search_temples(wish_theme="姻缘", limit=5, origin=guomao)
    statuses = [r["status"] for r in rows]
    first_other = next((i for i, s in enumerate(statuses) if s != "religious_site"), len(statuses))
    assert all(s == "religious_site" for s in statuses[:first_other])


def test_tools_expose_distance_and_refuse_to_invent_it():
    from app import data_access
    from app.agent import tool_registry

    tool_registry.ensure_defaults()
    with data_access.user_scope("u_coord_tools"):
        hit = tool_registry.invoke_tool("temple_search", {"wish_theme": "姻缘", "origin": "国贸"}, {})
        unknown = tool_registry.invoke_tool("temple_search", {"wish_theme": "姻缘", "origin": "三里河南边"}, {})
        gap = tool_registry.invoke_tool("temple_detail", {"temple": "云居寺", "origin": "国贸"}, {})
        plan = tool_registry.invoke_tool("temple_trip_plan", {"temple": "红螺寺", "origin": "国贸"}, {})

    assert hit["data"]["origin"]["name"] == "国贸"
    for item in hit["data"]["items"]:
        assert item["distance_km"] is not None, item["name"]
        assert "非行车距离" in item["distance_note"]

    assert unknown["data"]["origin"] is None
    assert "不要猜坐标" in unknown["data"]["origin_note"]
    assert all(i["distance_km"] is None for i in unknown["data"]["items"])

    assert gap["data"]["distance_km"] is None
    assert "不能说距离" in gap["data"]["distance_note"]
    assert plan["data"]["distance_km"] is not None and plan["data"]["live_data"] is False


def test_context_injects_distance_and_warns_on_unknown_origin():
    grounded = tc.temple_context("我想求姻缘，从国贸出发")
    assert '"origin_matched": "国贸"' in grounded
    assert "非行车距离" in grounded

    missing = tc.temple_context("我想求姻缘，从三里河南边出发")
    assert "origin_missing" in missing
    assert "不要猜坐标" in missing


def test_profile_origin_is_used_when_message_omits_it():
    grounded = tc.temple_context("我想求姻缘", {"origin": "国贸"})
    assert '"origin_matched": "国贸"' in grounded
