"""链接抽查脚本的行为测试（全程不联网）。

抽查报告一旦误报，就没人再信它——所以这里重点守两件事：
1. 覆盖要全：来源、场所事实、坐标、出发地四条线都要查；
2. HEAD 失败必须用 GET 复核（很多站点 HEAD 返 404，GET 是 200）。
"""

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("check_links", ROOT / "scripts" / "check_links.py")
check_links = importlib.util.module_from_spec(SPEC)
sys.modules["check_links"] = check_links
SPEC.loader.exec_module(check_links)


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_head_404_falls_back_to_get(monkeypatch):
    """HEAD 返回 404、GET 返回 200 的站点不能被判成死链。"""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.get_method())
        if req.get_method() == "HEAD":
            raise check_links.urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return FakeResponse(200)

    monkeypatch.setattr(check_links.urllib.request, "urlopen", fake_urlopen)
    status, error = check_links.check_url("https://example.com/a")
    assert (status, error) == (200, "")
    assert calls == ["HEAD", "GET"]


def test_get_error_is_reported(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise check_links.urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, None)

    monkeypatch.setattr(check_links.urllib.request, "urlopen", fake_urlopen)
    status, error = check_links.check_url("https://example.com/b")
    assert status == 503 and "503" in error


def test_unreachable_is_reported_not_raised(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise OSError("dns failure")

    monkeypatch.setattr(check_links.urllib.request, "urlopen", fake_urlopen)
    status, error = check_links.check_url("https://example.com/c")
    assert status is None and error == "OSError"


def test_collect_covers_every_source_kind():
    items = check_links.collect(date.today(), only_due=False)
    kinds = {role for i in items for role in i.roles}
    assert {"来源", "场所事实", "坐标", "出发地坐标"} <= kinds
    urls = [(i.owner_id, i.url) for i in items]
    assert len(urls) == len(set(urls)), "同一寺庙的同一条链接不该重复检查"
    assert all(i.url.startswith("http") for i in items)


def test_only_due_skips_fresh_links():
    items = check_links.collect(date.today(), only_due=True)
    # 出发地坐标没有 checked_at → 一定在待查队列里
    assert any(i.kind == "出发地坐标" for i in items)
    # 刚核过的（今天）不该再查
    fresh = [i for i in items if i.checked_at == date.today().isoformat()]
    for item in fresh:
        assert item.error, "未到期的检查应标记跳过而不是发请求"


def test_report_writes_failures_and_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(check_links, "REPORT", tmp_path / "report.md")
    items = [
        check_links.Item("法源寺", "fayuansi", "来源", "https://ok.example/a", "2026-01-01", status=200),
        check_links.Item("灵光寺", "lingguangsi", "来源", "https://dead.example/b", "2026-01-01", status=404),
    ]
    path = check_links.write_report(check_links.Report(items=items, checked_on="2026-05-01"))
    text = Path(path).read_text(encoding="utf-8")
    assert "失败 1" in text
    assert "https://dead.example/b" in text
    assert "降级为 `unverified`" in text


def test_exit_code_is_nonzero_on_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(check_links, "REPORT", tmp_path / "r.md")
    monkeypatch.setattr(check_links, "collect", lambda today, only_due: [
        check_links.Item("X", "x", "来源", "https://dead.example/c", "2026-01-01")])
    monkeypatch.setattr(check_links, "run", lambda items, timeout, workers=8: [
        setattr(i, "status", 404) or setattr(i, "error", "HTTP 404") for i in items])
    assert check_links.main(["--timeout", "1"]) == 1


def test_ok_run_exits_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(check_links, "REPORT", tmp_path / "r.md")
    monkeypatch.setattr(check_links, "collect", lambda today, only_due: [
        check_links.Item("X", "x", "来源", "https://ok.example/d", "2026-01-01")])
    monkeypatch.setattr(check_links, "run", lambda items, timeout, workers=8: [
        setattr(i, "status", 200) for i in items])
    assert check_links.main(["--timeout", "1"]) == 0
