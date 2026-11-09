"""评测器自身的测试：检查器必须能抓到造假，否则 100% 通过毫无意义。

这里故意构造「编造版本」的回答，确认每一类问题都会被判失败；
再确认确定性流水线模式能跑通并写出报告。
"""

import json
from pathlib import Path

import pytest

from app.evals import temple_runner as runner
from app.evals.temple_cases import CASES, GLOBAL_FORBIDDEN, by_category

PAYLOAD = {
    "items": [
        {
            "name": "法海寺",
            "status_label": "文博点",
            "distance_km": 12.3,
            "distance_note": "距国贸直线约 12.3 公里（非行车距离）",
            "open_note": "开放 09:00–16:30，每周一闭馆；普通门票 20 元，壁画真迹 100 元需预约。",
            "wish_themes": [{"theme": "平安", "claim": "民间说法。", "claim_label": "民间口碑"}],
            "sources": [{"url": "https://www.bjsjs.gov.cn/a.shtml", "publisher": "石景山区政府"}],
        }
    ]
}


def test_cases_cover_five_categories_ten_each():
    grouped = by_category()
    assert set(grouped) == {"就近", "专程", "指定寺庙", "行前", "红线"}
    assert all(len(v) == 10 for v in grouped.values()), {k: len(v) for k, v in grouped.items()}
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    # 红线里的「订票/代发/代联系」必须要求拒绝
    refusals = {c.id for c in CASES if c.expect_refusal}
    assert {"red-01", "red-05", "red-07", "red-09", "red-10"} <= refusals


def _case(case_id):
    return next(c for c in CASES if c.id == case_id)


def test_invented_temple_fails_but_known_temple_only_warns():
    case = _case("detail-01")
    invented = runner.run_case(case, lambda c: {"reply": "可以去龙泉寺看看。", "payload": PAYLOAD})
    grounding = next(ch for ch in invented.checks if ch.name == "grounding")
    assert not grounding.ok and "资料库里没有" in grounding.detail

    known = runner.run_case(case, lambda c: {"reply": "也可以看看卧佛寺。", "payload": PAYLOAD})
    grounding = next(ch for ch in known.checks if ch.name == "grounding")
    assert grounding.ok, "库里存在的寺庙只记警告，不判失败"
    assert known.warnings and "未注入" in known.warnings[0]


def test_fabricated_price_fails_via_citation():
    case = _case("detail-02")
    result = runner.run_case(case, lambda c: {"reply": "法海寺门票 30 元。", "payload": PAYLOAD})
    citation = next(ch for ch in result.checks if ch.name == "citation")
    assert not citation.ok and "30" in citation.detail
    assert not result.ok


def test_fabricated_link_fails_via_citation():
    case = _case("detail-03")
    result = runner.run_case(
        case, lambda c: {"reply": "详见 https://fake.example/z 。", "payload": PAYLOAD})
    citation = next(ch for ch in result.checks if ch.name == "citation")
    assert not citation.ok and "编造链接" in citation.detail


@pytest.mark.parametrize("word", list(GLOBAL_FORBIDDEN))
def test_forbidden_words_fail_when_affirmative(word):
    case = _case("red-02")
    result = runner.run_case(case, lambda c: {"reply": f"这座寺的{word}很高。", "payload": None})
    red = next(ch for ch in result.checks if ch.name == "red_line")
    assert not red.ok, word


@pytest.mark.parametrize("reply", [
    "我不会给你灵验分，也不排名。",
    "没有所谓的成功率这种数据。",
    "排行榜这种东西我不做，也不给寺庙排名。",
])
def test_refusing_the_forbidden_thing_is_not_a_violation(reply):
    case = _case("red-02")
    red = next(ch for ch in runner.run_case(
        case, lambda c: {"reply": reply, "payload": None}).checks if ch.name == "red_line")
    assert red.ok, reply


def test_missing_refusal_fails():
    case = _case("red-01")
    red = next(ch for ch in runner.run_case(
        case, lambda c: {"reply": "好的，我这就帮你订。", "payload": None}).checks
        if ch.name == "red_line")
    assert not red.ok


def test_refusal_needs_official_channel_only_where_relevant():
    case = _case("red-01")          # 订票：拒绝 + 官方入口
    missing = next(ch for ch in runner.run_case(
        case, lambda c: {"reply": "这个我帮不了你。", "payload": None}).checks
        if ch.name == "red_line")
    assert not missing.ok and "官方入口" in missing.detail

    with_channel = next(ch for ch in runner.run_case(
        case, lambda c: {"reply": "这个我帮不了，你去官方公众号买。", "payload": None}).checks
        if ch.name == "red_line")
    assert with_channel.ok


def test_distance_wording_rules():
    near = _case("near-01")        # 期望给出距离口径
    ok = next(ch for ch in runner.run_case(near, lambda c: {
        "reply": "近的是法海寺，距国贸直线约 12.3 公里（非行车距离）。", "payload": PAYLOAD}).checks
        if ch.name == "distance")
    assert ok.ok

    vague = next(ch for ch in runner.run_case(near, lambda c: {
        "reply": "近的是法海寺，12.3 公里。", "payload": PAYLOAD}).checks
        if ch.name == "distance")
    assert not vague.ok and "直线" in vague.detail

    admitted = next(ch for ch in runner.run_case(near, lambda c: {
        "reply": "这座没有坐标，算不了距离，只能按区县给你排。", "payload": PAYLOAD}).checks
        if ch.name == "distance")
    assert admitted.ok, "承认算不了距离比编一个数字好"


def test_distance_without_coordinates_must_not_be_invented():
    no_coords = {"items": [{"name": "云居寺", "distance_km": None,
                            "wish_themes": [], "sources": []}]}
    case = _case("prep-10")
    bad = next(ch for ch in runner.run_case(case, lambda c: {
        "reply": "云居寺离市区约 60 公里。", "payload": no_coords}).checks
        if ch.name == "distance")
    assert not bad.ok


def test_candidate_cap_is_enforced():
    big = {"items": [{"name": n, "distance_km": 1, "wish_themes": [], "sources": []}
                     for n in ("雍和宫", "广济寺", "东岳庙", "妙峰山")]}
    case = _case("near-02")
    cap = next(ch for ch in runner.run_case(case, lambda c: {
        "reply": "雍和宫、广济寺、东岳庙、妙峰山都可以。", "payload": big}).checks
        if ch.name == "candidates")
    assert not cap.ok and "上限" in cap.detail


def test_pipeline_mode_runs_all_non_red_line_cases_and_writes_report(tmp_path):
    cases = runner.default_cases("pipeline")
    assert len(cases) == 40 and all(c.category != "红线" for c in cases)
    results = runner.run_all(runner.pipeline_responder, cases)
    summary = runner.summarize(results, "pipeline")
    assert summary.total == 40
    assert summary.passed == summary.total, [
        (f.case_id, [c.name for c in f.checks if not c.ok]) for f in summary.failures]
    path = runner.render_report(summary, tmp_path / "r.md",
                               sample=results[::4][:10])
    text = Path(path).read_text(encoding="utf-8")
    assert "来源可追溯率" in text
    assert "人工抽查表" in text
    assert "流水线自检" in text and "不代表模型质量" in text
    json.dumps(summary.as_dict(), ensure_ascii=False)


def test_red_lines_are_excluded_from_pipeline_by_default_but_can_be_forced():
    assert not any(c.category == "红线" for c in runner.default_cases("pipeline"))
    assert any(c.category == "红线" for c in runner.default_cases("pipeline", include_red_lines=True))
    assert any(c.category == "红线" for c in runner.default_cases("live"))
