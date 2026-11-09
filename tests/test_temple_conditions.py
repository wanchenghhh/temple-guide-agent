"""Behavioral comparisons: changing one visit condition changes candidate fit."""
from copy import deepcopy
from datetime import date
import uuid

import pytest

from app.agent import temple_context as tc
from app.agent.domain import temples, visit_dates
from app.agent.domain.visit_conditions import assess_conditions, booking_guidance, extract_conditions, date_feasibility
from app.agent.domain.visit_dates import parse_visit_date
from app.agent.temple_card import build_card

TODAY = date(2026, 11, 9)  # Monday, independent of the machine's clock.


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(visit_dates, 'today_in_beijing', lambda: TODAY)


@pytest.fixture
def candidates(monkeypatch):
    base = deepcopy(temples.get_temple('雍和宫'))
    rows = []
    for ident, name, access, atmosphere in [
        ('steep', '山路寺', '山地寺院，台阶与坡道较多。', '香火旺，游客多，节假日排队。'),
        ('flat', '平地寺', '院落平缓，部分殿堂有台阶。', '香火旺，游客多。'),
        ('quiet', '静院寺', '院落平缓，台阶不多。', '古树清幽，游客少。'),
    ]:
        row = deepcopy(base)
        row.update(id=ident, name=name, aliases=[], accessibility=access, atmosphere=atmosphere,
                   status='religious_site', open_status='normal', closure_rule=[],
                   open_note='无需预约，现场购票。',
                   open_evidence={'grade': 'A', 'source': 'https://example.test/rules', 'method': 'official_web'},
                   open_verified_at='2026-11-09')
        rows.append(row)
    monkeypatch.setattr(temples, 'all_temples', lambda: rows)
    return rows


@pytest.mark.parametrize('text, expected', [
    ('今天去', '2026-11-09'), ('明天', '2026-11-10'), ('后天', '2026-11-11'),
    ('周一', '2026-11-09'), ('周二去', '2026-11-10'), ('下周一', '2026-11-16'),
    ('下下周日', '2026-11-29'), ('本周六', '2026-11-14'),
    ('2027年1月2日', '2027-01-02'), ('2026-11-15', '2026-11-15'),
    ('11月15号', '2026-11-15'),
])
def test_dates_resolve_to_explicit_calendar_day(text, expected):
    parsed = parse_visit_date(text)
    assert parsed['date'] == expected and not parsed['clarification']


@pytest.mark.parametrize('text', ['周末', '下周', '下个月', '春节去', '11月31日', '2026年2月29日', '2026-11-08', '明天或后天'])
def test_ambiguous_invalid_or_past_date_is_clarified(text):
    assert parse_visit_date(text)['clarification']


def test_weekend_reply_retains_next_week_and_year_rollover():
    pending = extract_conditions('下周末去')
    chosen = extract_conditions('周六', pending)
    assert chosen['visit_date'] == '2026-11-21'
    assert not chosen['date_clarification']
    assert parse_visit_date('下周一', today=date(2026, 12, 31))['date'] == '2027-01-04'


def test_elderly_is_a_preference_and_changes_order(candidates):
    baseline = temples.search_temples(wish_theme='平安')
    elderly = temples.search_temples(wish_theme='平安', conditions={'elderly': True})
    assert baseline[0]['id'] == 'steep'
    assert elderly[0]['id'] == 'flat'
    assert any(t['id'] == 'steep' for t in elderly), 'Do not infer that every older person cannot climb'


def test_no_climbing_removes_conflicts_and_quiet_changes_order(candidates):
    no_climb = temples.search_temples(wish_theme='平安', conditions={'no_climbing': True})
    assert {t['id'] for t in no_climb} == {'flat', 'quiet'}
    quiet = temples.search_temples(wish_theme='平安', conditions={'quiet': True})
    assert quiet[0]['id'] == 'quiet'
    assert all('人流尚未核实' in c['text'] for c in assess_conditions(quiet[0], {'quiet': True})['checks'])


def test_unknown_access_is_not_reported_as_matching(candidates):
    candidates[0]['accessibility'] = ''
    fit = assess_conditions(candidates[0], {'no_climbing': True})
    assert not fit['excluded'] and fit['checks'][0]['status'] == 'unknown'
    candidates[0]['accessibility'] = '院落平缓，无需爬山。'
    assert not assess_conditions(candidates[0], {'no_climbing': True})['excluded']


def test_date_changes_candidates_but_retains_holiday_exception_as_unknown(candidates):
    candidates[0]['closure_rule'] = ['周一闭馆']
    monday = temples.search_temples(wish_theme='平安', conditions={'visit_date': '2026-11-09'})
    tuesday = temples.search_temples(wish_theme='平安', conditions={'visit_date': '2026-11-10'})
    assert 'steep' not in {t['id'] for t in monday}
    assert 'steep' in {t['id'] for t in tuesday}
    candidates[0]['closure_rule'] = ['周一闭馆（法定节假日除外）']
    assert date_feasibility(candidates[0], '2026-11-09')['status'] == 'unknown'
    candidates[0]['closure_rule'] = ['仅农历初一、十五开放']
    assert date_feasibility(candidates[0], '2026-11-10')['status'] == 'unknown'


def test_nonofficial_rule_is_not_asserted_as_confirmed_closure(candidates):
    temple = candidates[0]
    temple.update(closure_rule=['周一闭馆'], open_evidence={'grade': 'C'}, sources=[])
    assert date_feasibility(temple, '2026-11-09')['status'] == 'unknown'


def test_pure_condition_followups_and_reversals(candidates):
    first = tc.build_temple_context('从国贸出发求平安')
    second = tc.build_temple_context('带老人，不爬山，安静点', session=first['session'])
    assert second['payload']['items'][0]['name'] == '静院寺'
    assert '山路寺' not in {t['name'] for t in second['payload']['items']}
    third = tc.build_temple_context('这次自己去，可以爬山，热闹点也行', session=second['session'])
    conditions = third['payload']['query']['conditions']
    assert not any(conditions[k] for k in ('elderly', 'no_climbing', 'quiet'))
    assert third['payload']['items'][0]['name'] == '山路寺'


def test_weekend_clarification_and_named_destination_conflict(candidates):
    first = tc.build_temple_context('从国贸出发求平安，下周末去')
    assert first['payload']['clarification'] and not first['payload']['items']
    second = tc.build_temple_context('周六', session=first['session'])
    assert second['payload']['query']['conditions']['visit_date'] == '2026-11-21'
    candidates[0]['closure_rule'] = ['周一闭馆']
    named = tc.build_temple_context('山路寺怎么样')
    dated = tc.build_temple_context('周一去', session=named['session'])
    assert dated['payload']['mode'] == 'detail'
    assert dated['payload']['items'][0]['name'] == '山路寺'
    assert dated['payload']['items'][0]['condition_checks'][0]['status'] == 'conflict'


def test_no_match_does_not_relax_constraints(candidates):
    for t in candidates:
        t['accessibility'] = '山路，需要爬山。'
    built = tc.build_temple_context('从国贸出发求平安，不爬山')
    assert not built['payload']['items']
    assert '调整' in built['payload']['missing']
    assert built['session']['conditions']['no_climbing']


def test_booking_rules_have_no_inventory_or_invented_release_time(candidates):
    t = candidates[0]
    t.update(open_status='reservation', open_note='需要提前预约，现场不售票。')
    guide = booking_guidance(t, '2026-11-20')
    assert guide['reservation'] == 'required'
    assert guide['availability'] == 'unknown'
    assert not guide['booking_opens_on'] and guide['timing_note']
    t['open_note'] = '可提前7天预约。'
    assert booking_guidance(t, '2026-11-20')['booking_opens_on'] == '2026-11-13'
    t['open_note'] = '至多提前3个开放日预约。'
    guide = booking_guidance(t, '2026-11-20')
    assert '开放日' in guide['window'] and not guide['booking_opens_on']
    t['open_note'] = '普通参观免预约，壁画真迹需预约。'
    assert booking_guidance(t)['reservation'] == 'mixed'


def test_card_has_conditions_and_booking_rules(candidates):
    built = tc.build_temple_context('从国贸出发求平安，明天带老人去，不爬山，安静点')
    card = build_card(built['payload'])
    assert card['conditions']['visit_date'] == '2026-11-10'
    assert card['items'][0]['condition_checks']
    assert card['items'][0]['booking_guidance']['availability'] == 'unknown'


def test_api_condition_changes_rerank_and_date_flows_into_travel(client, fake_llm, candidates, monkeypatch):
    from app.agent.subgraphs import chat
    from app.tools import travel
    monkeypatch.setattr(chat, '_llm_risk', lambda message: False)
    monkeypatch.setattr(travel, 'enabled', lambda: False)
    uid = 'conditions-' + uuid.uuid4().hex
    first = client.post('/api/chat', json={'user_id': uid, 'message': '从国贸出发求平安'}).json()
    tid = first['thread_id']
    second = client.post('/api/chat', json={'user_id': uid, 'thread_id': tid, 'message': '带老人，不爬山，安静点，明天去'}).json()
    card = second['data']['temple_card']
    assert card['items'][0]['name'] == '静院寺'
    assert '山路寺' not in {i['name'] for i in card['items']}
    assert card['conditions']['visit_date'] == '2026-11-10'
    third = client.post('/api/chat', json={'user_id': uid, 'thread_id': tid, 'message': '第一个怎么去'}).json()
    assert third['data']['temple_card']['conditions']['visit_date'] == '2026-11-10'


def test_background_official_source_cannot_upgrade_media_opening_rule(candidates):
    t = candidates[0]
    t.update(open_note='网络整理称无需预约。', open_evidence={'grade': 'C'},
             sources=[{'kind': 'official', 'url': 'https://example.test/history'}],
             closure_rule=['周一闭馆'])
    assert booking_guidance(t)['reservation'] == 'unknown'
    assert date_feasibility(t, '2026-11-09')['status'] == 'unknown'


def test_forecast_uses_date_from_current_visit_session(monkeypatch):
    from app.agent.travel_context import build_travel_payload
    from app.tools import travel
    monkeypatch.setattr(travel, 'enabled', lambda: True)
    monkeypatch.setattr(travel, 'route', lambda *args, **kwargs: {'status': 'error', 'reason': 'test'})
    monkeypatch.setattr(travel, 'weather', lambda *args: {
        'status': 'ok', 'forecasts': [
            {'date': '2026-11-09', 'text': '晴'}, {'date': '2026-11-10', 'text': '多云'}
        ], 'source': 'synthetic', 'checked_at': '2026-11-09'
    })
    payload = build_travel_payload('从国贸去雍和宫怎么走', {'visit_date': '2026-11-10'})
    assert payload['visit_date'] == '2026-11-10'
    assert payload['weather']['chosen']['date'] == '2026-11-10'


def test_eval_accepts_necessary_date_clarification_without_fabricated_distance():
    from app.evals.temple_runner import check_distance
    from app.evals.temple_cases import CASES
    case = next(c for c in CASES if c.id == 'near-07')
    payload = {'clarification': '你想周六还是周日去？', 'items': []}
    assert check_distance(payload['clarification'], payload, case).ok
    assert not check_distance(payload['clarification'] + '距离20公里', payload, case).ok


def test_unverified_opening_hours_remain_unknown_even_with_official_background(candidates):
    t = candidates[0]
    t['open_note'] = '官方：已对外开放；具体开放时段与是否收费尚未核实。'
    assert date_feasibility(t, '2026-11-10')['status'] == 'unknown'
