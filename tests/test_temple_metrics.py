"""指标与数据纠错入口的测试。

指标只存聚合字段，不允许带任何用户内容；纠错报告要能进库、能被管理员看到。
"""

import json
import time

import pytest

from app.agent import temple_metrics
from app.data_access import temple_metrics as store


@pytest.fixture(autouse=True)
def _clean():
    store.reset_for_tests()
    store.clear_all()          # 指标表是共享的：每个用例从零开始
    yield
    store.clear_all()


def _add(days_ago: int = 0, **kwargs):
    day = time.strftime("%Y-%m-%d", time.localtime(time.time() - days_ago * 86400))
    store.add_turn(day=day, **kwargs)


def test_summary_counts_rates_and_latency():
    _add(kind="recommend", wish="姻缘", candidates=3, citation_ok=True, latency_ms=3000,
         cost_units=0.02)
    _add(kind="detail", candidates=1, citation_ok=True, degraded=True, latency_ms=5000)
    _add(kind="refusal", refused=True, latency_ms=1000)
    _add(kind="review", wish="求子", candidates=2, citation_ok=False, review_items=3,
         latency_ms=7000, cost_units=0.03)

    data = temple_metrics.summary(7).as_dict()
    assert data["turns"] == 4
    assert data["traceable_rate"] == 0.75          # 3/4 通过引用校验
    assert data["degraded_rate"] == 0.25
    assert data["refusal_rate"] == 0.25
    assert data["candidate_short_rate"] == 0.75    # 3 座以下算候选不足
    assert data["review_turns"] == 1
    assert data["latency_p50_ms"] == 5000 or data["latency_p50_ms"] in (3000, 5000)
    assert data["latency_p95_ms"] >= data["latency_p50_ms"]
    assert data["cost_total"] == 0.05
    assert data["by_kind"]["recommend"] == 1 and data["by_wish"]["姻缘"] == 1


def test_summary_window_excludes_old_rows():
    _add(days_ago=30, kind="recommend", candidates=3)
    _add(days_ago=0, kind="detail", candidates=1)
    assert temple_metrics.summary(7).as_dict()["turns"] == 1
    assert temple_metrics.summary(60).as_dict()["turns"] == 2


def test_summary_is_safe_when_storage_missing(monkeypatch):
    monkeypatch.setattr(store, "turns_since", lambda day: (_ for _ in ()).throw(RuntimeError("boom")))
    data = temple_metrics.summary(7).as_dict()
    assert data["turns"] == 0 and data["traceable_rate"] == 0.0


def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(store, "add_turn", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    temple_metrics.record(kind="detail")     # 不抛异常


def test_metrics_store_no_user_content():
    """表结构里不该出现 user_id / 文本字段——指标只存数字。"""
    columns = {c.name for c in store.TempleTurn.__table__.columns}
    assert "user_id" not in columns and "message" not in columns and "reply" not in columns
    assert {"day", "kind", "wish", "candidates", "citation_ok", "latency_ms"} <= columns


def test_render_outputs_the_launch_gate():
    _add(kind="recommend", candidates=3, citation_ok=True, latency_ms=2500)
    text = temple_metrics.render(temple_metrics.summary(7))
    assert "来源可追溯率" in text and "上线门槛" in text
    assert "p50" in text and "p95" in text


def test_admin_endpoint_requires_admin(client):
    r = client.get("/api/admin/temple/metrics")
    assert r.status_code in (401, 403, 503)   # 未配置管理员令牌时是 503


def test_user_can_report_bad_data(client):
    from app.data_access import temple_reports

    temple_reports.clear_all()
    r = client.post("/api/temple/report", json={
        "temple": "法海寺", "field": "开放时间", "note": "周一闭馆这条我看公告说正常开放"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["id"] and data["known_temple"] is True
    # 重复提交不再累加
    again = client.post("/api/temple/report", json={
        "temple": "法海寺", "field": "开放时间", "note": "周一闭馆这条我看公告说正常开放"})
    assert again.json()["data"]["duplicate"] is True
    assert len(temple_reports.list_open()) == 1
    temple_reports.clear_all()


def test_report_requires_temple_name(client):
    r = client.post("/api/temple/report", json={"temple": "  ", "note": "x"})
    assert r.status_code == 400


def test_report_does_not_store_identity():
    from app.data_access import temple_reports

    columns = {c.name for c in temple_reports.TempleReport.__table__.columns}
    assert "user_id" not in columns and "ip" not in columns


def test_admin_can_list_reports(client):
    from app.data_access import temple_reports

    temple_reports.clear_all()
    temple_reports.add("雍和宫", "交通", "地铁换乘写错了")
    r = client.get("/api/admin/temple/reports")
    assert r.status_code in (401, 403, 503)
    assert len(temple_reports.list_open()) == 1
    temple_reports.clear_all()


def test_chat_rate_limit_is_off_by_default(client, fake_llm, monkeypatch):
    monkeypatch.delenv("CHAT_RATE_PER_MIN", raising=False)
    fake_llm.reply = "在。"
    codes = [client.post("/api/chat", json={"message": "你好"}).status_code for _ in range(3)]
    assert codes == [200, 200, 200]


def test_chat_rate_limit_blocks_after_threshold(client, fake_llm, monkeypatch):
    import app.main as main_mod

    monkeypatch.setenv("CHAT_RATE_PER_MIN", "2")
    main_mod._CHAT_HITS.clear()
    fake_llm.reply = "在。"
    first = client.post("/api/chat", json={"message": "你好"})
    second = client.post("/api/chat", json={"message": "你好"})
    third = client.post("/api/chat", json={"message": "你好"})
    assert first.status_code == 200 and second.status_code == 200
    assert third.status_code == 429
    body = third.json()["detail"]
    assert body["code"] == "rate_limited" and "频繁" in body["message"]
    main_mod._CHAT_HITS.clear()


# ── 反馈处理流转 ────────────────────────────────────────────────────────────

def test_report_lifecycle_and_counts():
    from app.data_access import temple_reports as store

    store.clear_all()
    first = store.add("万寿寺", "开放时间", "周一闭馆这条不对")
    second = store.add("法源寺", "开放时间", "公众号说不对外")
    assert store.counts()["status_open"] == 2

    assert store.set_status(first["id"], "resolved")["status"] == "resolved"
    assert store.set_status(second["id"], "rejected")["status"] == "rejected"

    counts = store.counts()
    assert counts["total"] == 2
    assert counts["status_open"] == 0
    assert counts["status_resolved"] == 1 and counts["status_rejected"] == 1
    assert store.list_reports("open") == []
    assert len(store.list_reports("")) == 2
    store.clear_all()


def test_unknown_status_is_rejected():
    from app.data_access import temple_reports as store

    store.clear_all()
    row = store.add("潭柘寺", "门票", "票价不对")
    with pytest.raises(ValueError):
        store.set_status(row["id"], "whatever")
    assert store.set_status(9999, "resolved") is None
    store.clear_all()


def test_triage_cli_lists_and_resolves(capsys):
    import importlib.util
    import sys as _sys
    from pathlib import Path as _Path

    from app.data_access import temple_reports as store

    root = _Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "triage_reports", root / "scripts" / "triage_reports.py")
    triage = importlib.util.module_from_spec(spec)
    _sys.modules["triage_reports"] = triage
    spec.loader.exec_module(triage)

    store.clear_all()
    row = store.add("万寿寺", "门票", "价格好像变了")
    assert triage.main([]) == 0
    out = capsys.readouterr().out
    assert "待处理：1 条" in out and "万寿寺" in out

    assert triage.main(["--resolve", str(row["id"])]) == 0
    assert store.counts()["status_open"] == 0
    store.clear_all()


def test_admin_report_status_requires_admin(client):
    r = client.post("/api/admin/temple/reports/1/status?status=resolved")
    assert r.status_code in (401, 403, 503)


def test_admin_report_listing_returns_counts(client):
    r = client.get("/api/admin/temple/reports")
    assert r.status_code in (401, 403, 503)
