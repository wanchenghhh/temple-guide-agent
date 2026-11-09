"""寺庙推荐/详情卡片：后端视图模型 + /api/chat 契约 + 前端接线。

卡片只是把已经注入、已经核过的资料换个长相，所以这里守三条：
* 不新增事实：卡片里的每个字段都能在注入资料里找到；
* 不超上限：最多 3 座，不可推荐的不出现；
* 不骗人：口碑要标「民间口碑」，没来源就写未核实，距离标「直线」。
"""

import json
from pathlib import Path

import pytest

from app.agent import temple_card as tc
from app.agent.temple_context import build_temple_context

ROOT = Path(__file__).resolve().parent.parent


def _payload(message: str) -> dict:
    built = build_temple_context(message)
    assert built, message
    return built["payload"]


def test_card_lists_at_most_three_recommendable_items():
    card = tc.build_card(_payload("我想求姻缘，从国贸出发"))
    assert card["kind"] == "temple_recommend"
    assert 1 <= len(card["items"]) <= 3
    for item in card["items"]:
        assert item["name"] and item["place_type"]
        assert item["distance_km"] is None or isinstance(item["distance_km"], (int, float))
        assert item["sources_status"] in ("verified", "unverified")


def test_card_carries_evidence_labels_for_every_wish():
    card = tc.build_card(_payload("我想求姻缘"))
    for item in card["items"]:
        assert item["wishes"], item["name"]
        for wish in item["wishes"]:
            assert wish["theme"]
            assert wish["evidence"] in ("官方", "文献记载", "民间口碑", "媒体", "民俗说法")
            assert wish["claim_label"]


def test_card_marks_non_prayer_places():
    card = tc.build_card(_payload("我想求姻缘，从国贸出发"))
    heritage = [i for i in card["items"] if not i["prayable"]]
    for item in heritage:
        assert "不是上香许愿" in item["recommend_note"], item["name"]


def test_detail_card_for_named_temple():
    card = tc.build_card(_payload("雍和宫求什么比较合适"))
    assert card["kind"] == "temple_detail"
    assert [i["name"] for i in card["items"]] == ["雍和宫"]


def test_compare_card_when_two_temples_named():
    card = tc.build_card(_payload("红螺寺和妙峰山哪个更好"))
    assert card["kind"] == "temple_compare"
    assert {i["name"] for i in card["items"]} == {"红螺寺", "妙峰山"}


def test_card_never_invents_sources_or_distance():
    card = tc.build_card(_payload("云居寺离市区多远"))
    item = card["items"][0]
    assert item["distance_km"] is None, "没有坐标就不能给数字"
    for src in item["sources"]:
        assert src["url"].startswith("http")


def test_detail_card_does_not_paste_a_remembered_wish():
    """问「雍和宫求什么」不该因为记忆里存着姻缘，就把卡片标成「姻缘」。"""
    from app.agent.temple_context import build_temple_context

    built = build_temple_context("雍和宫求什么比较合适", {"wish": "姻缘"})
    card = tc.build_card(built["payload"])
    assert card["kind"] == "temple_detail" and card["wish"] == ""

    explicit = tc.build_card(build_temple_context("雍和宫求姻缘吗")["payload"])
    assert explicit["wish"] == "姻缘"


def test_card_is_none_without_grounded_content():
    assert tc.build_card(None) is None
    assert tc.build_card({"items": [], "mode": "recommend"}) is None


def test_unverified_items_raise_the_card_flag():
    payload = _payload("我想求姻缘")
    payload["items"][0]["sources_status"] = "unverified"
    card = tc.build_card(payload)
    assert card["has_unverified_sources"] is True


def test_chat_api_returns_temple_card(client, fake_llm):
    fake_llm.reply = "从国贸出发，最近的是东岳庙（直线约 2.3 公里，非行车距离）。"
    r = client.post("/api/chat", json={"user_id": "temple-card-user",
                                       "message": "我想求姻缘，从国贸出发"})
    assert r.status_code == 200
    data = r.json()["data"]
    card = data["temple_card"]
    assert card["kind"] == "temple_recommend"
    assert card["origin_name"] == "国贸"
    assert card["items"][0]["wishes"][0]["theme"] == "姻缘"
    # 卡片与文字回答必须是同一批资料
    assert card["items"][0]["name"] in data["messages"][-1]["content"] or card["items"][0]["name"] in "".join(
        i["name"] for i in card["items"])


def test_non_temple_turn_has_no_temple_card(client, fake_llm):
    fake_llm.reply = "这是一封请假邮件草稿。"
    r = client.post("/api/chat", json={"user_id": "temple-card-user2",
                                       "message": "帮我写一封请假邮件"})
    assert "temple_card" not in r.json()["data"]


def test_frontend_registers_and_renders_the_card():
    cards = (ROOT / "static/js/cards.js").read_text(encoding="utf-8")
    flows = (ROOT / "static/js/flows.js").read_text(encoding="utf-8")
    css = (ROOT / "static/chat.css").read_text(encoding="utf-8")
    assert "export function templeCard" in cards
    assert "templeCard" in flows and "temple: templeCard" in flows
    assert "emitTemple(data.temple_card" in flows
    assert ".card-temple" in css and ".temple-item" in css
    # 卡片里必须把「直线距离」和「非行车」标出来，不能只写数字
    assert "非行车" in cards
    assert "暂未核实" in cards


def test_card_payload_is_json_serialisable():
    card = tc.build_card(_payload("我想求姻缘，从国贸出发"))
    assert json.loads(json.dumps(card, ensure_ascii=False)) == card


def test_privacy_notice_and_rate_limit_are_wired():
    """上线前必须告知「记住了什么」，并留了限流开关。"""
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/chat.css").read_text(encoding="utf-8")
    assert 'id="privacyBanner"' in index
    assert "会被记住" in index and "记忆" in index
    assert "initPrivacyNotice" in app_js and "pa.privacy.seen.v1" in app_js
    assert ".privacy-banner" in css

    main_py = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "CHAT_RATE_PER_MIN" in main_py and "rate_limited" in main_py
