"""开放信息回填脚本：能改对、能校验来源、不假装有出处。"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("apply_open_info", ROOT / "scripts" / "apply_open_info.py")
apply_mod = importlib.util.module_from_spec(SPEC)
sys.modules["apply_open_info"] = apply_mod
SPEC.loader.exec_module(apply_mod)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    payload = json.loads((ROOT / "app/agent/domain/temples.json").read_text(encoding="utf-8"))
    path = tmp_path / "temples.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(apply_mod, "DATA", path)
    return path


def _run(monkeypatch, *args, source_ok=True):
    monkeypatch.setattr(apply_mod, "_check_url", lambda url, timeout=15.0: source_ok)
    monkeypatch.setattr(apply_mod.subprocess, "run", lambda *a, **k: None)
    return apply_mod.main(list(args))


def _temple(path, name):
    data = json.loads(path.read_text(encoding="utf-8"))
    return next(t for t in data["temples"] if t["name"] == name)


def test_applies_open_status_and_note(sandbox, monkeypatch):
    code = _run(monkeypatch, "--temple", "法源寺", "--open", "yes",
                "--reservation", "no", "--ticket", "免费", "--hours", "8:30-15:30")
    assert code == 0
    temple = _temple(sandbox, "法源寺")
    assert temple["open_status"] == "normal"
    assert "无需预约" in temple["open_note"] and "免费" in temple["open_note"]
    assert "8:30-15:30" in temple["open_note"]


def test_partial_answer_is_allowed(sandbox, monkeypatch):
    code = _run(monkeypatch, "--temple", "通教寺", "--open", "limited", "--closure", "first-lunar")
    assert code == 0
    temple = _temple(sandbox, "通教寺")
    assert temple["closure_rule"] == ["仅农历初一、十五开放"]
    assert temple["open_status"] == "unverified"      # limited 仍算未完全核实


def test_only_official_source_upgrades_status(sandbox, monkeypatch):
    """默认 media：能打开也不许把攻略当官方。"""
    code = _run(monkeypatch, "--temple", "白云观", "--open", "yes",
                "--source", "https://example.com/ctrip", "--publisher", "某攻略站")
    assert code == 0
    temple = _temple(sandbox, "白云观")
    assert any(s["url"] == "https://example.com/ctrip" for s in temple["sources"])
    assert temple["sources"].pop()["kind"] == "media"


def test_media_source_does_not_upgrade_when_unverified(sandbox, monkeypatch):
    data = json.loads(sandbox.read_text(encoding="utf-8"))
    for t in data["temples"]:
        if t["name"] == "大悲寺":
            t["sources"] = []
            t["sources_status"] = "unverified"
    sandbox.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _run(monkeypatch, "--temple", "大悲寺", "--open", "yes",
         "--source", "https://example.com/blog", "--source-kind", "folk")
    assert _temple(sandbox, "大悲寺")["sources_status"] == "unverified"


def test_source_is_verified_before_adoption(sandbox, monkeypatch):
    code = _run(monkeypatch, "--temple", "白云观", "--open", "yes",
                "--source", "https://example.com/baiyun", "--publisher", "白云观官网",
                "--source-kind", "official", "--method", "official_web")
    assert code == 0
    temple = _temple(sandbox, "白云观")
    assert temple["sources_status"] == "verified"
    assert any(s["url"] == "https://example.com/baiyun" for s in temple["sources"])


def test_method_decides_the_note_wording(sandbox, monkeypatch):
    """联网查的不能写成「电话核对」——那是伪造证据来源。"""
    _run(monkeypatch, "--temple", "万寿寺", "--open", "yes", "--method", "official_web")
    note = _temple(sandbox, "万寿寺")["open_note"]
    assert "官方页面核查" in note and "电话核对" not in note
    assert _temple(sandbox, "万寿寺")["open_verified_at"]

    _run(monkeypatch, "--temple", "法源寺", "--open", "yes", "--method", "phone")
    assert "电话核对" in _temple(sandbox, "法源寺")["open_note"]


def test_closure_merges_instead_of_overwriting(sandbox, monkeypatch):
    data = json.loads(sandbox.read_text(encoding="utf-8"))
    for t in data["temples"]:
        if t["name"] == "孔庙和国子监":
            t["closure_rule"] = ["周一闭馆"]
    sandbox.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _run(monkeypatch, "--temple", "孔庙和国子监", "--open", "yes",
         "--closure", "mon-tue", "--merge-closure")
    rules = _temple(sandbox, "孔庙和国子监")["closure_rule"]
    assert "周一闭馆" in rules and "周二闭馆" in rules


def test_contradictory_arguments_are_rejected(sandbox, monkeypatch):
    code = _run(monkeypatch, "--temple", "白云观", "--open", "reservation", "--reservation", "no")
    assert code == 2


def test_dead_source_is_rejected_and_nothing_written(sandbox, monkeypatch):
    before = _temple(sandbox, "白云观")["open_status"]
    code = _run(monkeypatch, "--temple", "白云观", "--open", "yes",
                "--source", "https://dead.example/x", source_ok=False)
    assert code == 1
    assert _temple(sandbox, "白云观")["open_status"] == before


def test_without_source_status_stays_unverified(sandbox, monkeypatch):
    data = json.loads(sandbox.read_text(encoding="utf-8"))
    for t in data["temples"]:
        if t["name"] == "大悲寺":
            t["sources"] = []
            t["sources_status"] = "unverified"
    sandbox.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    code = _run(monkeypatch, "--temple", "大悲寺", "--open", "yes")
    assert code == 0
    temple = _temple(sandbox, "大悲寺")
    assert temple["sources_status"] == "unverified", "没给来源就不能升级成已核实"


def test_unknown_temple_is_rejected(sandbox, monkeypatch):
    assert _run(monkeypatch, "--temple", "不存在的寺", "--open", "yes") == 2


def test_dry_run_writes_nothing(sandbox, monkeypatch):
    before = sandbox.read_text(encoding="utf-8")
    code = _run(monkeypatch, "--temple", "广济寺", "--open", "yes", "--dry-run")
    assert code == 0
    assert sandbox.read_text(encoding="utf-8") == before


def test_official_channel_counts_as_grade_a(sandbox, monkeypatch):
    """用户从官方公众号核对（无链接）也是 A 级，但不能冒充网页来源。"""
    _run(monkeypatch, "--temple", "白云观", "--open", "yes",
         "--ticket", "10元", "--method", "official_channel",
         "--note", "官方公众号核对")
    temple = _temple(sandbox, "白云观")
    assert temple["open_evidence"]["method"] == "official_channel"
    assert temple["open_evidence"]["grade"] == "A"
    assert temple["open_evidence"]["source"] == ""
    assert "官方公众号核对" in temple["open_note"]
    assert "电话核对" not in temple["open_note"]


def test_media_method_stays_grade_c(sandbox, monkeypatch):
    _run(monkeypatch, "--temple", "白云观", "--open", "yes", "--method", "media")
    assert _temple(sandbox, "白云观")["open_evidence"]["grade"] == "C"
