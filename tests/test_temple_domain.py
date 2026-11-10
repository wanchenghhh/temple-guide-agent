"""Temple-guide vertical: curated data, evidence, tools, extraction, memory fields.

These tests pin the invariants that keep the vertical honest — the ones the first
data round violated:

* no source means no fact: every row is either verified (real URL + checked_at)
  or explicitly ``unverified``, never a placeholder pretending to be a citation;
* every wish has an evidence type, and 平安 is not a tag at all;
* a place you cannot visit is never recommended for a wish;
* nothing is padded when there is no match.
"""

import json
from urllib.parse import urlparse

import pytest

from app.agent import temple_context as tc
from app.agent.domain import temples as domain


@pytest.fixture(scope="module")
def dataset():
    return domain.load_dataset()


def test_dataset_shape_and_counts(dataset):
    rows = dataset["temples"]
    assert 20 <= len(rows) <= 30, "试点范围应保持在 20–30 座"
    assert len({r["id"] for r in rows}) == len(rows)
    assert len({r["name"] for r in rows}) == len(rows)
    meta = dataset["meta"]
    assert meta["schema_version"] == "v6"
    assert meta["count"] == len(rows)
    assert meta["recommendable_count"] == sum(1 for r in rows if r["wish_recommendable"])
    assert meta["visitable_count"] == sum(1 for r in rows if r["visitable"])


def test_every_row_has_open_state_or_says_unverified(dataset):
    """开放状态只有两种写法：官方已明确，或明确承认未核实。"""
    for row in dataset["temples"]:
        assert row["open_status"] in ("normal", "reservation", "limited", "closed", "unverified"), row["id"]
        if row["open_status"] != "unverified":
            assert row["open_note"], f"{row['id']} 声称开放状态就必须说明依据"
            assert row["sources"], row["id"]


def test_no_placeholder_sources(dataset):
    """A source is a real http(s) URL with a check date, or there is none at all."""
    banned = ("官方渠道", "官方公众号/官网", "以官方为准", "详见官方")
    for row in dataset["temples"]:
        status = row["sources_status"]
        assert status in ("verified", "unverified"), row["id"]
        if status == "verified":
            assert row["sources"], row["id"]
            for src in row["sources"]:
                assert urlparse(src["url"]).scheme in ("http", "https"), (row["id"], src)
                assert src["checked_at"], (row["id"], src)
                assert src["publisher"], (row["id"], src)
        else:
            assert row["sources"] == [], f"{row['id']} 未核实就不应该有 sources"
        blob = json.dumps(row["sources"], ensure_ascii=False)
        for word in banned:
            assert word not in blob, (row["id"], word)


def test_place_facts_are_checkable(dataset):
    """场所事实必须可核：有出处 URL，且该 URL 在这个寺庙的已验证来源里。"""
    for row in dataset["temples"]:
        for fact in row.get("place_facts", []):
            assert fact["text"], row["id"]
            assert fact["evidence_type"] in ("official", "reference"), row["id"]
            assert fact["source"].startswith("http"), (row["id"], fact)
            assert fact["checked_at"], row["id"]
            assert fact["source"] in {s["url"] for s in row["sources"]}, (row["id"], fact["source"])


def test_wish_claim_and_place_basis_are_two_separate_layers(dataset):
    """「殿宇有记载」不能被偷换成「在这儿求就灵」——两层各自带自己的证据等级。"""
    for row in dataset["temples"]:
        for wish in row["wish_themes"]:
            assert wish["theme"] in domain.WISH_THEMES, (row["id"], wish["theme"])
            assert wish["role"] in ("primary", "secondary"), (row["id"], wish["theme"])
            # 说法层：只能是民俗口碑或文献记载的说法
            assert wish["claim_evidence"] in ("reference", "folk"), (row["id"], wish["theme"])
            assert wish["claim"], (row["id"], wish["theme"])
            # 场所层：有出处就必须是已核链接；该寺庙已核实时，殿宇说法不能没有出处
            if wish["basis_source"]:
                assert wish["basis_source"] in {s["url"] for s in row["sources"]}, (row["id"], wish["theme"])
            if wish["basis"] and row["sources_status"] == "verified":
                assert wish["basis_source"], (row["id"], wish["theme"])
            assert "evidence_type" not in wish, "说法层不该再有 evidence_type"


def test_folk_claims_stay_folk_even_with_a_documented_hall(dataset):
    by_id = {r["id"]: r for r in dataset["temples"]}
    # 孔庙：大成殿祭孔是可核的场所事实；「求学业」仍是民俗，不许升成文献
    kongmiao = domain.wish_evidence(by_id["kongmiao"], "学业")
    assert kongmiao["basis"] and kongmiao["basis_source"]
    assert kongmiao["claim_evidence"] == "folk"
    # 白云观：月老/送子等殿有文献记载，说法本身也按文献记（reference）
    baiyun = domain.wish_evidence(by_id["baiyunguan"], "求子")
    assert baiyun["claim_evidence"] == "reference" and baiyun["basis"]


def test_wechat_channels_are_finder_hints_not_sources(dataset):
    """公众号无法程序核验：只能当「去哪问」，不能当引用来源。"""
    for row in dataset["temples"]:
        assert isinstance(row.get("finder_hint"), list), row["id"]
        for hint in row["finder_hint"]:
            assert "公众号" not in json.dumps(row["sources"], ensure_ascii=False), row["id"]
        for src in row["sources"]:
            assert "mp.weixin.qq.com" not in src["url"], row["id"]
            assert "公众号" not in src["publisher"], row["id"]
    # 未核实的寺庙必须给出去哪问
    for row in dataset["temples"]:
        if row["sources_status"] != "verified":
            assert row["finder_hint"], row["id"]


def test_ping_an_is_not_a_tag_any_more(dataset):
    for row in dataset["temples"]:
        themes = [w["theme"] for w in row["wish_themes"]]
        assert "平安" not in themes, row["id"]
    assert domain.is_generic_wish("平安")
    assert "「平安」不作为寺庙标签" in dataset["meta"]["wish_policy"]
    assert "finder_hint" in dataset["meta"]["source_policy"]
    assert "place_facts" in dataset["meta"]["evidence_policy"]


def test_unvisitable_places_are_never_recommendable(dataset):
    for row in dataset["temples"]:
        if row["status"] in ("relic", "closed", "market"):
            assert row["wish_recommendable"] is False, row["id"]
            assert row["recommend_note"], row["id"]
    names = {r["name"] for r in dataset["temples"] if r["status"] in ("relic", "closed")}
    # 慈寿寺只剩塔、大慧寺只剩殿且不开放：两座都不能进推荐
    assert {"慈寿寺", "大慧寺"} <= names
    for temple in ("慈寿寺", "大慧寺"):
        for theme in domain.WISH_THEMES + ("平安",):
            assert temple not in [t["name"] for t in domain.search_temples(wish_theme=theme, limit=5)]


def test_non_prayer_venues_say_so(dataset):
    """文博点/景区可以参观，但不是上香许愿的地方——必须说清。"""
    for row in dataset["temples"]:
        if row["status"] in ("heritage", "scenic") and row["wish_recommendable"]:
            assert "不是上香许愿" in row["recommend_note"], row["id"]


def test_place_type_vocabulary_is_precise(dataset):
    """「活跃寺院」不能拿来称呼道观和景区庙宇。"""
    assert set(domain.STATUS_LABELS) == {
        "religious_site", "heritage", "scenic", "relic", "closed", "market"}
    assert "寺院" not in domain.STATUS_LABELS["religious_site"]
    for row in dataset["temples"]:
        assert row["status_label"] == domain.STATUS_LABELS[row["status"]], row["id"]
        assert row["religious_registered"] in (True, False, None), row["id"]
        # 登记状态不是“猜”的：True 必须有来源
        if row["religious_registered"] is True:
            assert row["sources"], row["id"]


def test_reviewed_hard_errors_stay_fixed(dataset):
    by_id = {r["id"]: r for r in dataset["temples"]}
    # 大钟寺：没有任何"学业"依据
    assert "学业" not in [w["theme"] for w in by_id["dazhongsi"]["wish_themes"]]
    # 天宁寺：尼众寺院 + 正确的地址与地铁线
    assert by_id["tianningsi"]["sect"] == "汉传佛教（尼众）"
    assert "甲3号" in by_id["tianningsi"]["address_hint"]
    assert "7号线" in by_id["tianningsi"]["transport"]
    assert "9号线" not in by_id["tianningsi"]["transport"]
    # 法海寺：模式口是 11 号线
    assert "11号线" in by_id["fahaisi"]["transport"]
    # 孔庙与国子监是两个门牌
    assert "13号" in by_id["kongmiao"]["address_hint"]
    # 易变的开放时间不再写成事实
    for row in dataset["temples"]:
        assert "9:00" not in row["visit_note"], row["id"]


@pytest.mark.parametrize("spoken,expected", [
    ("孔庙", "孔庙和国子监"), ("国子监", "孔庙和国子监"),
    ("火神庙", "火德真君庙"), ("石刻博物馆", "五塔寺"),
    ("玲珑塔", "慈寿寺"), ("白塔寺", "妙应寺"),
    ("古钟博物馆", "大钟寺"), ("民俗博物馆", "东岳庙"),
])
def test_people_call_places_by_short_names(spoken, expected):
    """用户不会说全称：问「孔庙」不能答「没收录」。"""
    temple = domain.get_temple(spoken)
    assert temple is not None, spoken
    assert temple["name"] == expected
    assert tc.mentioned_temple(f"想问{spoken}求学业") is not None


def test_lookup_by_name_alias_and_id():
    assert domain.get_temple("雍和宫")["id"] == "yonghegong"
    assert domain.get_temple("白塔寺")["id"] == "miaoyingsi"      # alias
    assert domain.get_temple("yonghegong")["id"] == "yonghegong"  # id
    assert domain.get_temple("不存在的寺") is None


@pytest.mark.parametrize("theme,expected", [
    ("求子", {"白云观", "妙峰山"}),
    ("姻缘", {"红螺寺", "广济寺", "妙峰山"}),
    ("学业", {"卧佛寺", "孔庙和国子监"}),
])
def test_documented_wishes_find_their_temples(theme, expected):
    names = {t["name"] for t in domain.search_temples(wish_theme=theme, limit=5)}
    assert expected <= names


@pytest.mark.parametrize("theme", ["姻缘", "求子", "学业", "财运", "健康", "事业"])
def test_every_recommended_temple_can_be_visited_and_documents_the_wish(theme):
    rows = domain.search_temples(wish_theme=theme, limit=5)
    assert rows, theme
    for row in rows:
        assert row["wish_recommendable"] is True, (theme, row["id"])
        assert domain.wish_evidence(row, theme) is not None, (theme, row["id"])


def test_religious_sites_outrank_other_venues_for_a_wish():
    rows = domain.search_temples(wish_theme="姻缘", limit=5)
    statuses = [r["status"] for r in rows]
    first_other = next((i for i, s in enumerate(statuses) if s != "religious_site"), len(statuses))
    assert all(s == "religious_site" for s in statuses[:first_other])


def test_generic_wish_is_not_a_ranking():
    rows = domain.search_temples(wish_theme="平安", limit=3)
    assert rows, "用户说平安时不能返回空"
    for row in rows:
        assert row["wish_recommendable"] is True
    # 与不带心愿时的顺序一致 = 没有额外打分
    assert [r["id"] for r in rows] == [r["id"] for r in domain.search_temples(limit=3)]


def test_search_never_pads_and_has_no_fuzzy_back_door():
    assert domain.search_temples(wish_theme="考试顺利") == []
    assert domain.search_temples(wish_theme="不存在的主题") == []
    # 曾经用 note 子串兜底，导致“健康”虚胖命中（备注里出现“健康”就算）。
    # 现在只认显式依据：结果里每一座都必须真有一条“健康”依据，不能靠备注蹭。
    assert domain.search_temples(wish_theme="健康", district="房山区", limit=5) == []
    rows = domain.search_temples(wish_theme="健康", limit=5)
    assert rows
    for row in rows:
        assert domain.wish_evidence(row, "健康") is not None, row["id"]
    assert "云居寺" not in [r["name"] for r in rows]  # 房山区这座没有健康依据


def test_temple_tools_are_read_only_and_declare_the_disclaimer():
    from app.agent import tool_registry

    tool_registry.ensure_defaults()
    for name in ("temple_search", "temple_detail", "temple_trip_plan"):
        spec = tool_registry.get(name)
        assert spec is not None, name
        assert spec.risk_level == "read", name
        assert spec.requires_confirm is False, name


def test_temple_tools_surface_status_evidence_and_gaps():
    from app import data_access
    from app.agent import tool_registry

    tool_registry.ensure_defaults()
    with data_access.user_scope("u_temple_tools"):
        search = tool_registry.invoke_tool("temple_search", {"wish_theme": "姻缘"}, {})
        detail = tool_registry.invoke_tool("temple_detail", {"temple": "白云观"}, {})
        heritage = tool_registry.invoke_tool("temple_detail", {"temple": "智化寺"}, {})
        relic = tool_registry.invoke_tool("temple_detail", {"temple": "慈寿寺"}, {})
        plan = tool_registry.invoke_tool("temple_trip_plan", {"temple": "红螺寺", "origin": "国贸"}, {})
        blocked = tool_registry.invoke_tool("temple_trip_plan", {"temple": "慈寿寺"}, {})
        unknown = tool_registry.invoke_tool("temple_detail", {"temple": "没这座寺"}, {})

    assert search["trust"] == "curated_reference"
    assert search["disclaimer"] and search["data"]["count"] >= 1
    assert search["data"]["note"]
    for item in search["data"]["items"]:
        assert item["status_label"] and item["wish_recommendable"] is True
        assert "姻缘" in [w["theme"] for w in item["wish_themes"]]
        for wish in item["wish_themes"]:
            assert wish["claim_label"] and wish["claim"]

    assert detail["data"]["found"] and detail["data"]["sources_status"] == "verified"
    assert detail["data"]["halls"], "白云观应该给出殿宇"
    assert any(h["themes"] for h in detail["data"]["halls"])
    assert "周一闭馆" in heritage["data"]["closure_rule"]
    assert heritage["data"]["recommend_note"]
    assert relic["data"]["wish_recommendable"] is False and relic["data"]["recommend_note"]
    assert plan["data"]["live_data"] is False and "实时" in plan["data"]["weather"]
    assert blocked["data"]["blocked_reason"]
    assert unknown["data"]["found"] is False


@pytest.mark.parametrize("message,theme", [
    ("我想求姻缘", "姻缘"),
    ("想要个孩子，一直没怀上", "求子"),
    ("考研想上岸", "学业"),
    ("最近想发财", "财运"),
    ("求平安", "平安"),
    ("今天天气怎么样", None),
    ("帮我写封邮件", None),
])
def test_wish_detection_is_explicit_only(message, theme):
    assert tc.detect_theme(message) == theme


@pytest.mark.parametrize("message,origin", [
    ("从国贸出发", "国贸"),
    ("我在北京朝阳区", "北京朝阳区"),
    ("我住在五道口", "五道口"),
])
def test_origin_detection(message, origin):
    assert tc.detect_origin(message) == origin


def test_companions_and_travel_preferences_are_labeled():
    assert tc.detect_companions("想和父母一起去") == ["父母"]
    assert "步行少" in tc.detect_travel_preferences("腿脚不方便，不想爬山")


def test_temple_context_is_injected_only_for_temple_turns():
    assert tc.temple_context("帮我写一封请假邮件") == ""
    assert tc.temple_context("今天天气怎么样") == ""
    grounded = tc.temple_context("我想求姻缘，从国贸出发")
    assert "<temple_data>" in grounded
    assert "灵验分" in grounded          # the red line travels with the data
    assert "暂未查到" in grounded        # the honest-gap instruction too
    assert "民间口碑" in grounded        # folk claims must be labelled
    assert "周一闭馆" in grounded        # avoid-the-wasted-trip rule


def test_temple_context_uses_the_named_temple_for_detail_mode():
    grounded = tc.temple_context("雍和宫求什么比较合适")
    assert '"mode": "detail"' in grounded
    assert "雍和宫" in grounded


def test_generic_wish_turn_is_flagged_as_not_a_ranking():
    grounded = tc.temple_context("我想求平安")
    assert '"generic_wish": true' in grounded
    assert "generic_note" in grounded


def test_temple_context_reports_an_empty_candidate_set_instead_of_padding():
    grounded = tc.temple_context("我想求一个资料库没有的主题")
    assert grounded == "" or "没有匹配的候选" in grounded


def test_remember_temple_fields_writes_only_explicit_statements(tmp_path, monkeypatch):
    from app import data_access, db

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    with data_access.user_scope("u_temple_mem"):
        stored = tc.remember_temple_fields("u_temple_mem", "我想求姻缘，从国贸出发，和父母一起")
        profile = db.get_profile("u_temple_mem")
    assert stored == ["companions", "origin", "wish"]
    assert profile["wish"] == "姻缘"
    assert profile["origin"] == "国贸"
    assert profile["companions"] == ["父母"]

    with data_access.user_scope("u_temple_mem2"):
        assert tc.remember_temple_fields("u_temple_mem2", "你好呀") == []
        assert db.get_profile("u_temple_mem2").get("wish") is None


def test_vertical_memory_fields_are_on_the_card_and_forgettable(tmp_path, monkeypatch):
    from app import data_access, db
    from app.agent.memory import card

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    uid = "u_temple_card"
    with data_access.user_scope(uid):
        db.merge_and_save(uid, {"wish": "姻缘", "origin": "国贸"})
        labels = {f["field"]: f["value"] for f in card.card_view(uid)["facts"]}
        assert labels["wish"] == "姻缘" and labels["origin"] == "国贸"
        card.delete_fact(uid, "wish")
        assert db.get_profile(uid).get("wish") in (None, "")


def test_docs_stats_match_the_data(dataset):
    """文档里的数字必须与数据一致：上一轮“文档写着处理过、数据是空的”就是这类型错。"""
    from collections import Counter
    from pathlib import Path

    rows = dataset["temples"]
    verified = sum(1 for r in rows if r["sources_status"] == "verified")
    unverified = len(rows) - verified
    recommendable = sum(1 for r in rows if r["wish_recommendable"])
    evidence = Counter(w["claim_evidence"] for r in rows for w in r["wish_themes"])
    total = sum(evidence.values())

    guide = Path("docs/temple-guide.md").read_text(encoding="utf-8")
    assert f"| 总条目 | {len(rows)} |" in guide
    assert f"| 可许愿 | {recommendable} |" in guide
    assert f"| 可参观 | {sum(1 for r in rows if r['visitable'])} |" in guide
    assert f"| 来源已核 | {verified} |" in guide
    assert f"| **来源未核实** | **{unverified}** |" in guide
    assert f"| 心愿条目 | {total} |" in guide
    assert f"文献记载 {evidence['reference']} / 民间口碑 {evidence['folk']}" in guide

    checklist = Path("docs/temple-review-checklist.md").read_text(encoding="utf-8")
    assert f"条目：{len(rows)}" in checklist
    assert f"可许愿：{recommendable}" in checklist
    assert f"未核实：{unverified}" in checklist or f"**未核实**" in checklist
    for row in rows:
        assert row["name"] in checklist, row["name"]


def test_second_review_round_corrections(dataset):
    """第二轮复核的结论必须固化，否则下一个人又会填回去。"""
    by = {r["id"]: r for r in dataset["temples"]}

    # 妙峰山：不是宗教活动场所，只是景区（wiki 明说无僧道进驻）
    ms = by["miaofengshan"]
    assert ms["status"] == "scenic" and ms["religious_registered"] is False
    assert any("并非宗教活动场所" in f["text"] for f in ms["place_facts"])
    # 财神殿供赵公明；三霄娘娘在三仙姑殿（涧沟村，独立于景区）
    assert domain.wish_evidence(ms, "财运")["basis"] == "财神殿（赵公明）"
    assert "三霄" not in json.dumps(domain.wish_evidence(ms, "财运"), ensure_ascii=False)
    # 文昌殿在回香阁东厢殿，不在娘娘庙里
    assert "回香阁" in domain.wish_evidence(ms, "学业")["basis"]

    # 东岳庙：既是民俗博物馆，也是道教活动场所（2008 登记、2015 挂牌）
    dym = by["dongyuemiao"]
    assert dym["religious_registered"] is True and dym["status"] == "heritage"
    assert any("宗教活动场所" in f["text"] for f in dym["place_facts"])

    # 广化寺：不能写“正常开放”
    gh = by["guanghuasi"]
    assert gh["open_status"] != "normal"
    assert "初一" in gh["open_note"] or "不对游客开放" in gh["open_note"]

    # 雍和宫：限流 + 需预约
    assert by["yonghegong"]["open_status"] == "reservation"

    # 红螺寺：官网自称景区、谢绝带香
    hl = by["hongluosi"]
    assert hl["status"] == "scenic"
    assert any("谢绝带香" in f["text"] for f in hl["place_facts"])

    # 灵光寺不再挂“姻缘”；大悲寺补位（佛协登记）
    assert domain.wish_evidence(by["lingguangsi"], "姻缘") is None
    assert by["dabeisi"]["religious_registered"] is True
    assert domain.wish_evidence(by["dabeisi"], "姻缘")["claim_evidence"] == "folk"

    # 孔庙：场所事实里有“最高学府”，但「求学业」仍是民俗，不升格
    km = by["kongmiao"]
    assert any("最高学府" in f["text"] for f in km["place_facts"])
    assert domain.wish_evidence(km, "学业")["claim_evidence"] == "folk"


def test_persona_pins_the_vertical_and_keeps_the_safety_floor():
    from app.agent.subgraphs.chat import PERSONA

    assert "寺庙寻访向导" in PERSONA
    for floor in ("CRISIS_NOTE", "安全 > 底线", "不编造", "不擅自外发", "不假装真人", "确认卡"):
        assert floor in PERSONA, floor
    for red_line in ("灵验分", "暂未查到", "不替代专业医疗", "民间口碑", "文博点", "平安"):
        assert red_line in PERSONA, red_line
