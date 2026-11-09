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


def test_source_is_verified_before_adoption(sandbox, monkeypatch):
    code = _run(monkeypatch, "--temple", "白云观", "--open", "yes",
                "--source", "https://example.com/baiyun", "--publisher", "白云观官网")
    assert code == 0
    temple = _temple(sandbox, "白云观")
    assert temple["sources_status"] == "verified"
    assert any(s["url"] == "https://example.com/baiyun" for s in temple["sources"])


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
