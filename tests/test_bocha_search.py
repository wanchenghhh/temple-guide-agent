"""博查搜索工具：只取摘要、有缓存、有额度、能过滤跑题。

重点守四件事：
1. 默认关闭，没 key 不乱调；
2. 只返回标题/摘要/链接（摘要截断），不落全文；
3. 同一 query 12 小时内不重复请求；每天到额度就停；
4. 跑题结果必须丢掉（实测「法海寺」会搜出杭州「法喜寺」）。
"""

import json

import pytest

from app.tools import bocha


def _fake_body(items):
    return {"code": 200, "data": {"webPages": {"value": items}}}


def _page(name, url, site, snippet="摘要", published="2021-05-23T00:00:00+08:00"):
    return {"name": name, "url": url, "siteName": site,
            "snippet": snippet, "datePublished": published}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    monkeypatch.delenv("BOCHA_ENABLED", raising=False)
    monkeypatch.setenv("BOCHA_DAILY_CAP", "200")
    bocha.clear_cache()
    # 额度是落盘的：每个用例从零开始，否则用例之间互相污染
    path = bocha._usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": bocha._today(), "count": 0}), encoding="utf-8")
    yield
    bocha.clear_cache()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("BOCHA_ENABLED", "1")
    return True


def test_disabled_by_default_makes_no_request(monkeypatch):
    calls = []

    def fetch(request, timeout):
        calls.append(request)
        return _fake_body([])

    out = bocha.search("法海寺", 3, fetch=fetch)
    assert out["status"] == "disabled" and out["items"] == []
    assert calls == []


def test_missing_key_is_reported_not_raised(enabled, monkeypatch):
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    monkeypatch.setattr(bocha, "_dotenv_loaded", True, raising=False)
    out = bocha.search("法海寺", 3)
    assert out["status"] == "unconfigured"


def test_normalises_and_truncates(enabled):
    long_snippet = "很长的摘要" * 100

    def fetch(request, timeout):
        assert request.headers.get("Authorization") == "Bearer test-key"
        return _fake_body([
            _page("法海寺游记", "https://example.com/a", "小红书", long_snippet),
            _page("法海寺官方", "https://example.com/b", "北京市文物局", "官方介绍"),
        ])

    out = bocha.search("法海寺", 5, fetch=fetch)
    assert out["status"] == "ok" and out["count"] == 2
    first, second = out["items"]
    assert len(first["snippet"]) <= bocha.SNIPPET_CHARS
    assert first["kind"] == "ugc" and second["kind"] == "web"
    assert first["published"] == "2021-05-23"
    assert "summary" not in first and "cachedPageUrl" not in first, "不落全文"


def test_platform_boilerplate_is_stripped_from_snippets(enabled):
    """实测：今日头条的摘要会带「展开 不感兴趣 举报 扫码下载APP…」，必须清掉。"""
    noise = "前两天去了妙峰山 希望一切顺利 #记录真实生活 展开 不感兴趣 举报 扫码下载今日头条APP 看最新"
    assert "扫码下载" not in bocha._clean_snippet(noise)
    assert bocha._clean_snippet(noise) == "前两天去了妙峰山 希望一切顺利 #记录真实生活"
    assert bocha._clean_snippet("正常摘要 · 完") == "正常摘要 · 完"


def test_second_identical_query_hits_cache(enabled):
    calls = []

    def fetch(request, timeout):
        calls.append(1)
        return _fake_body([_page("法海寺", "https://example.com/a", "北京市文物局")])

    bocha.search("法海寺 门票", 3, fetch=fetch)
    out = bocha.search("法海寺 门票", 3, fetch=fetch)
    assert len(calls) == 1, "同一 query 不该重复请求"
    assert out["cached"] is True


def test_daily_cap_stops_requests(enabled, monkeypatch):
    monkeypatch.setenv("BOCHA_DAILY_CAP", "1")
    calls = []

    def fetch(request, timeout):
        calls.append(1)
        return _fake_body([_page("法海寺", "https://example.com/a", "北京市文物局")])

    assert bocha.search("query-one", 3, fetch=fetch)["status"] == "ok"
    out = bocha.search("query-two", 3, fetch=fetch)
    assert out["status"] == "quota_exhausted"
    assert len(calls) == 1
    assert out["usage"]["remaining"] == 0


def test_usage_is_persisted_and_resets_daily(enabled, monkeypatch):
    def fetch(request, timeout):
        return _fake_body([_page("法海寺", "https://example.com/a", "北京市文物局")])

    bocha.search("q", 3, fetch=fetch)
    assert bocha.usage()["count"] == 1
    # 换一天：额度自动归零
    path = bocha._usage_path()
    path.write_text(json.dumps({"date": "2000-01-01", "count": 999}), encoding="utf-8")
    assert bocha.usage()["count"] == 0


def test_http_error_is_reported_without_leaking_key(enabled):
    import urllib.error

    def fetch(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    out = bocha.search("法海寺", 3, fetch=fetch)
    assert out["status"] == "error" and "401" in out["reason"]
    assert "test-key" not in json.dumps(out, ensure_ascii=False)


def test_off_topic_results_are_dropped(enabled):
    """实测：搜「法海寺」会返回杭州「法喜寺」的帖子，必须丢掉。"""
    def fetch(request, timeout):
        return _fake_body([
            _page("法喜寺求姻缘很灵验", "https://example.com/hz", "搜狐"),
            _page("北京法海寺壁画求姻缘的说法", "https://example.com/bj", "北京市文物局"),
        ])
    # search_for_temple 内部自己调用 search，这里直接替换模块函数
    original = bocha.search
    bocha.search = lambda q, c=5, **kw: original(q, c, fetch=fetch)
    try:
        result = bocha.search_for_temple("法海寺", "姻缘")
    finally:
        bocha.search = original
    assert result["count"] == 1
    assert result["dropped_off_topic"] == 1
    assert "法海寺" in result["items"][0]["title"]
    assert "北京" in result["query"] and "法海寺" in result["query"]


def test_theme_mismatch_returns_nothing_instead_of_noise(enabled, monkeypatch):
    """法海寺的游记跟「姻缘」无关：宁可 0 条，也不拿无关内容凑数。"""
    def fetch(request, timeout):
        return _fake_body([_page("北京法海寺游记", "https://example.com/bj", "简书", "风景不错")])

    original = bocha.search
    monkeypatch.setattr(bocha, "search", lambda q, c=5, **kw: original(q, c, fetch=fetch))
    result = bocha.search_for_temple("法海寺", "姻缘")
    assert result["count"] == 0
    assert result["dropped_by_theme"] == 1

    # 摘要里提到心愿的才保留
    def fetch2(request, timeout):
        return _fake_body([_page("法海寺攻略", "https://example.com/bj2", "简书", "据说求姻缘的人不少")])

    monkeypatch.setattr(bocha, "search", lambda q, c=5, **kw: original(q, c, fetch=fetch2))
    bocha.clear_cache()
    kept = bocha.search_for_temple("法海寺", "姻缘")
    assert kept["count"] == 1 and kept["items"][0]["kind"] == "ugc"


def test_celebrity_gossip_is_not_a_review(enabled, monkeypatch):
    """实测：搜「白云观 求子」先返回张兰上香的娱乐新闻，那不是口碑。"""
    def fetch(request, timeout):
        return _fake_body([
            _page("张兰北京白云观求子上香被偶遇", "https://example.com/gossip", "网易", "网友说求子很灵"),
            _page("白云观送子娘娘殿求子攻略", "https://example.com/real", "马蜂窝", "有人分享过求子流程"),
        ])

    original = bocha.search
    monkeypatch.setattr(bocha, "search", lambda q, c=5, **kw: original(q, c, fetch=fetch))
    result = bocha.search_for_temple("白云观", "求子")
    assert result["dropped_as_gossip"] == 1
    assert result["count"] == 1
    assert "攻略" in result["items"][0]["title"]


def test_title_theme_match_ranks_first(enabled, monkeypatch):
    def fetch(request, timeout):
        return _fake_body([
            _page("去白云观的一天", "https://example.com/a", "简书", "顺便求子"),
            _page("白云观求子攻略", "https://example.com/b", "马蜂窝", "流程分享"),
        ])

    original = bocha.search
    monkeypatch.setattr(bocha, "search", lambda q, c=5, **kw: original(q, c, fetch=fetch))
    result = bocha.search_for_temple("白云观", "求子")
    assert result["items"][0]["title"].startswith("白云观求子攻略")


def test_tool_wrapper_marks_trust_and_rule(enabled, monkeypatch):
    from app import data_access

    monkeypatch.setattr(bocha, "search", lambda q, c=5: {
        "status": "ok", "query": q, "items": [], "count": 0, "cached": False,
        "usage": bocha.usage()})
    with data_access.user_scope("u_bocha_test"):
        out = bocha.web_search_bocha("法海寺", 3)
    assert out["trust"] == "untrusted_source_data"
    assert "不可信" in out["instruction"]
    assert "网友说法" in out["data"]["rule"]


def test_tool_is_registered_as_read_only():
    from app.agent import tool_registry

    tool_registry.ensure_defaults()
    spec = tool_registry.get("web_search_bocha")
    assert spec is not None
    assert spec.risk_level == "read" and spec.requires_confirm is False
