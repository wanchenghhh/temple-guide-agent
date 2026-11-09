"""引用校验：编造的链接必须被删，编造的数字必须被标记。

PRD 的上线门槛是「抽查答案能否回到有效原文，编造一条即不算过关」。
这里把这些门槛变成断言：不是靠模型自觉，而是输出后再检一遍。
"""

import json

import pytest

from app.agent.domain import verify


PAYLOAD = {
    "items": [
        {
            "name": "法海寺",
            "open_note": "开放 09:00–16:30，16:00 停止售票，每周一闭馆；普通门票 20 元，壁画真迹 100 元需预约。",
            "distance_km": 12.3,
            "distance_note": "距你直线约 12.3 公里（非行车距离）",
            "sources": [{"url": "https://www.bjsjs.gov.cn/a.shtml", "publisher": "石景山区政府"}],
        }
    ]
}


def test_foreign_urls_are_stripped_and_allowed_kept():
    reply = ("看法海寺的公告 https://www.bjsjs.gov.cn/a.shtml ，"
             "另有攻略说 https://fake-guide.example.com/fahaisi 。")
    cleaned, removed = verify.strip_foreign_urls(reply, PAYLOAD)
    assert "https://www.bjsjs.gov.cn/a.shtml" in cleaned
    assert "fake-guide.example.com" not in cleaned
    assert removed == ["https://fake-guide.example.com/fahaisi"]
    assert "来源链接未核实" in cleaned


@pytest.mark.parametrize("reply,flagged", [
    ("普通门票 20 元。", []),
    ("壁画真迹 100 元。", []),
    ("普通门票 30 元。", ["30"]),           # 资料写 20，模型写 30
    ("开放 09:00–16:30。", []),
    ("开放 08:00–17:00。", ["08:00", "17:00"]),
    ("距你约 12.3 公里。", []),
    ("距你约 25 公里。", ["25"]),
    ("直线都在 20 公里出头。", ["20"]),   # 资料里只有 12.3 公里；「20 元」不能当距离用

    ("成功率高 80%。", ["80"]),             # PRD 明令不许编成功率
])
def test_unsupported_numbers_are_flagged(reply, flagged):
    hits = verify.unsupported_numbers(reply, PAYLOAD)
    assert [h["value"] for h in hits] == flagged


def test_travel_json_numbers_are_traceable():
    """行前数据是 JSON 数字（distance_km / temp_max），回答引用它们不算编造。"""
    payload = {"travel": {"route": {"distance_km": 8.1, "duration_min": 46},
                          "weather": {"weather": {"chosen": {"temp_min": -3, "temp_max": 12}}}}}
    reply = "坐地铁约 8.1 公里、46 分钟，今天 -3 到 12℃。"
    assert verify.unsupported_numbers(reply, payload) == []


def test_invented_temperature_is_flagged():
    payload = {"travel": {"weather": {"chosen": {"temp_min": -3, "temp_max": 12}}}}
    hits = verify.unsupported_numbers("今天 25 度。", payload)
    assert [h["kind"] for h in hits] == ["温度"]


def test_price_number_cannot_borrow_a_distance_number():
    """资料里「20 元」不代表能写「20 公里」：分区比对。"""
    payload = {"items": [{"open_note": "门票 20 元", "distance_km": 12.3,
                          "sources": []}]}
    hits = verify.unsupported_numbers("距你约 20 公里。", payload)
    assert [h["value"] for h in hits] == ["20"]


def test_distance_rounding_is_still_allowed():
    payload = {"items": [{"distance_note": "直线约 24.0 公里", "sources": []}]}
    assert verify.unsupported_numbers("直线约 24 公里。", payload) == []


def test_phone_numbers_and_years_are_not_treated_as_facts():
    hits = verify.unsupported_numbers("咨询电话 010-88715776，2001 年列为文保单位。", PAYLOAD)
    assert hits == []


def test_verify_citation_reports_and_cleans():
    reply = ("法海寺普通门票 30 元，详情见 https://fake.example.com/x 。")
    out = verify.verify_citation(reply, PAYLOAD)
    assert out["report"]["ok"] is False
    assert out["report"]["urls_removed"] == ["https://fake.example.com/x"]
    assert out["report"]["unsupported_numbers"][0]["value"] == "30"
    assert "fake.example.com" not in out["text"]


def test_clean_reply_passes():
    reply = "法海寺普通门票 20 元，壁画真迹 100 元需预约，09:00–16:30 开放。"
    out = verify.verify_citation(reply, PAYLOAD)
    assert out["report"]["ok"] is True
    assert out["text"] == reply


def test_chat_turn_strips_fabricated_link_and_flags_fabricated_price(fake_llm):
    """端到端：模型编链接 + 编价格，回答里都不许原样出现。"""
    from app import data_access
    from app.agent.subgraphs import chat as chat_mod
    from app.agent.harness import context as trace_ctx

    fake_llm.reply = ("法海寺普通门票 30 元，预约看这个 https://fake.example.com/y 。"
                      "开放 09:00–16:30，周一闭馆。")

    captured: list[dict] = []
    with data_access.user_scope("u-cite"):
        with trace_ctx.step_context(tool="chat", thread_id="t-cite", user_id="u-cite", sandbox=[]):
            out = chat_mod.node_chat({
                "user_id": "u-cite",
                "message": "法海寺门票多少钱",
                "thread_id": "t-cite",
            })
            captured.extend(trace_ctx.current().get("guardrails", []))

    reply = out["messages"][0]["content"]
    assert "fake.example.com" not in reply
    assert "以官方公告为准" in reply          # 数字没出处 → 加提示
    hit = next(g for g in captured if g["guardrail"] == "citation_check")
    assert hit["urls_removed"] == 1
    assert hit["unsupported_numbers"] == 1


def test_non_temple_turn_is_untouched(fake_llm):
    from app import data_access
    from app.agent.subgraphs import chat as chat_mod

    fake_llm.reply = "这是一封请假邮件的草稿，费用 30 元。"
    with data_access.user_scope("u-cite2"):
        out = chat_mod.node_chat({
            "user_id": "u-cite2",
            "message": "帮我写一封请假邮件",
            "thread_id": "t-cite2",
        })
    assert out["messages"][0]["content"] == fake_llm.reply


def test_payload_urls_include_sources_facts_and_coordinates():
    payload = {
        "items": [{"sources": [{"url": "https://a.example/x"}],
                   "place_facts": [{"source": "https://b.example/y"}],
                   "coord_source": "https://c.example/z"}]
    }
    assert verify.allowed_urls(payload) == {
        "https://a.example/x", "https://b.example/y", "https://c.example/z"}
