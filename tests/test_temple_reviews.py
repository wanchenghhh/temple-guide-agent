"""公开分享摘要（评价层）：只在问口碑时搜、只给摘要、不许把网友说法写成事实。"""

import pytest

from app.agent import reviews


TEMPLE_MSG = "妙峰山求子灵不灵"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from app.tools import bocha

    monkeypatch.setenv("BOCHA_ENABLED", "1")
    monkeypatch.setenv("BOCHA_API_KEY", "k")
    bocha.clear_cache()
    yield
    bocha.clear_cache()


def _fake_result(**over):
    base = {
        "status": "ok", "query": "北京 妙峰山 求子",
        "items": [
            {"title": "妙峰山求子求健康", "site": "墙根网", "published": "2010-06-03",
             "url": "https://example.com/a", "snippet": "庙会期间很多人来求子", "kind": "web"},
            {"title": "北京妙峰山求子", "site": "百度贴吧", "published": "2022-07-19",
             "url": "https://example.com/b", "snippet": "有人说很灵", "kind": "ugc"},
            {"title": "无链接的条目", "site": "某站", "published": "",
             "url": "", "snippet": "x", "kind": "web"},
            {"title": "第四条", "site": "某站", "published": "2020-01-01",
             "url": "https://example.com/d", "snippet": "y", "kind": "web"},
        ],
        "dropped_off_topic": 1,
    }
    base.update(over)
    return base


def test_only_asks_for_review_turns(monkeypatch):
    assert reviews.is_review_turn(TEMPLE_MSG)
    assert reviews.is_review_turn("雍和宫口碑怎么样")
    assert not reviews.is_review_turn("雍和宫周一开吗")      # 问开放时间不搜口碑
    assert not reviews.is_review_turn("我想求姻缘")          # 没提具体寺庙
    assert not reviews.is_review_turn("")


def test_payload_keeps_only_summary_fields_and_three_items(monkeypatch):
    from app.tools import bocha

    monkeypatch.setattr(bocha, "search_for_temple",
                        lambda *a, **k: _fake_result())
    payload = reviews.build_review_payload(TEMPLE_MSG)
    assert payload["status"] == "ok" and payload["temple"] == "妙峰山"
    assert len(payload["items"]) == 3, "最多 3 条"
    urls = [i["url"] for i in payload["items"]]
    assert "" not in urls, "没有链接的条目要丢掉"
    first = payload["items"][0]
    assert set(first) == {"title", "site", "published", "url", "snippet", "kind"}
    assert len(first["snippet"]) <= 200


def test_empty_result_says_so_instead_of_padding(monkeypatch):
    from app.tools import bocha

    monkeypatch.setattr(bocha, "search_for_temple",
                        lambda *a, **k: _fake_result(items=[], dropped_off_topic=5))
    payload = reviews.build_review_payload(TEMPLE_MSG)
    assert payload["items"] == []
    assert "没有找到相关" in payload["note"]
    block = reviews.render_review_block(payload)
    assert "没有搜到相关分享" in block


def test_disabled_search_returns_none(monkeypatch):
    monkeypatch.setenv("BOCHA_ENABLED", "0")
    assert reviews.build_review_payload(TEMPLE_MSG) is None


def test_search_failure_is_reported_not_invented(monkeypatch):
    from app.tools import bocha

    monkeypatch.setattr(bocha, "search_for_temple",
                        lambda *a, **k: {"status": "quota_exhausted", "items": []})
    payload = reviews.build_review_payload(TEMPLE_MSG)
    assert payload["status"] == "quota_exhausted"
    assert payload["items"] == [] and "不要编" in payload["note"]


def test_block_carries_the_restatement_rules(monkeypatch):
    from app.tools import bocha

    monkeypatch.setattr(bocha, "search_for_temple", lambda *a, **k: _fake_result())
    block = reviews.render_review_block(reviews.build_review_payload(TEMPLE_MSG))
    assert "<review_data>" in block
    assert "不可信来源" in block and "不得复述成事实" in block
    assert "https://example.com/a" in block


@pytest.mark.parametrize("reply,ok", [
    ("有网友说这里求子比较灵，但只是分享。", True),
    ("据说求子很灵验，很多人来。", True),
    ("这座寺求子很灵，基本都能成。", False),
    ("求子保证能成。", False),
    ("这里求子的事情我不确定，没有依据。", True),
])
def test_claims_must_be_hedged(reply, ok):
    result = reviews.verify_review_claims(reply)
    assert result["ok"] is ok, (reply, result["hits"])


def test_chat_appends_disclaimer_and_flags_unhedged_claims(fake_llm, monkeypatch):
    from app import data_access
    from app.agent import reviews as reviews_mod
    from app.agent.harness import context as trace_ctx
    from app.agent.subgraphs import chat as chat_mod
    from app.tools import bocha

    monkeypatch.setattr(bocha, "search_for_temple", lambda *a, **k: _fake_result())
    fake_llm.reply = "妙峰山求子很灵，基本都能成。"

    captured = []
    with data_access.user_scope("u_review_chat"):
        with trace_ctx.step_context(tool="chat", thread_id="t-rev", user_id="u_review_chat", sandbox=[]):
            out = chat_mod.node_chat({
                "user_id": "u_review_chat",
                "message": TEMPLE_MSG,
                "thread_id": "t-rev",
            })
            captured.extend(trace_ctx.current().get("guardrails", []))

    reply = out["messages"][0]["content"]
    assert reviews_mod.REVIEW_FOOTER in reply
    hit = [g for g in captured if g["guardrail"] == "review_claim"]
    assert hit and hit[0]["hits"] >= 1
    card = out["temple_card"]
    assert card["reviews"]["temple"] == "妙峰山"
    assert card["reviews"]["items"][1]["ugc"] is True


def test_non_review_turn_has_no_review_block(fake_llm, monkeypatch):
    from app import data_access
    from app.agent.subgraphs import chat as chat_mod

    fake_llm.reply = "雍和宫需要线上预约。"
    with data_access.user_scope("u_review_chat2"):
        out = chat_mod.node_chat({
            "user_id": "u_review_chat2",
            "message": "雍和宫周一开吗",
            "thread_id": "t-rev2",
        })
    assert "以上是网友公开分享" not in out["messages"][0]["content"]
    assert out["temple_card"]["reviews"] is None


def test_temple_turn_skips_generic_web_search(fake_llm, monkeypatch):
    """寺庙话题有策展资料，不该再跑通用网页搜索（实测会多花 15 秒）。"""
    from app import data_access
    from app.agent import crawl_tools
    from app.agent.subgraphs import chat as chat_mod

    called = []
    monkeypatch.setattr(crawl_tools, "source_context", lambda *a, **k: called.append(1) or "")
    fake_llm.reply = "红螺寺在怀柔，市区过去宜自驾。"
    with data_access.user_scope("u_no_crawl"):
        chat_mod.node_chat({
            "user_id": "u_no_crawl",
            "message": "红螺寺怎么去",
            "thread_id": "t-no-crawl",
        })
    assert called == [], "寺庙话题不该触发通用网页搜索"


def test_non_temple_turn_still_allows_web_search(fake_llm, monkeypatch):
    from app import data_access
    from app.agent import crawl_tools
    from app.agent.subgraphs import chat as chat_mod

    called = []
    monkeypatch.setattr(crawl_tools, "source_context", lambda *a, **k: called.append(1) or "")
    monkeypatch.setattr("app.agent.tool_selection.select_tool",
                        lambda msg: type("S", (), {"tool": "web_search", "intent": "model_tool:web_search", "confidence": 0.95})())
    fake_llm.reply = "我查了一下。"
    with data_access.user_scope("u_with_crawl"):
        chat_mod.node_chat({
            "user_id": "u_with_crawl",
            "message": "今天有什么科技新闻",
            "thread_id": "t-with-crawl",
        })
    assert called == [1], "非寺庙话题的网络检索能力要保留"
