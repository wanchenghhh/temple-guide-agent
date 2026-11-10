"""Regressions from the actual failed acceptance conversation."""
from datetime import date
import uuid

import pytest

from app.agent import temple_context as tc
from app.agent.domain import temples, visit_dates
from app.agent.recommendation_reply import recover_recommendation
from app.agent.temple_followup import interpret_followup

TRANSCRIPT = [
    '周六去寺庙求平安，给我推荐一下',
    '不用管我从哪里出发，直接给我推荐吧',
    '哪个区都行', '海淀区', '东城区',
]


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(visit_dates, 'today_in_beijing', lambda: date(2026, 11, 9))


def test_exact_transcript_keeps_task_and_distinguishes_scope_from_missing_data():
    session = {}
    results = []
    for message in TRANSCRIPT:
        built = tc.build_temple_context(message, session=session)
        assert built is not None, message
        results.append(built['payload'])
        session = built['session']
        assert session['wish'] == '平安'
        assert session['conditions']['visit_date'] == '2026-11-14'
    assert all(p['items'] and not p['clarification'] for p in results[:3])
    assert results[3]['query']['district'] == '海淀区'
    assert results[3]['scope_summary']['recorded_places']
    assert '当前资料库' in results[3]['empty_result_reply']
    assert results[4]['items']
    assert all(item['district'] == '东城区' for item in results[4]['items'])


def test_location_opt_out_overrides_saved_origin_and_can_be_reversed():
    profile = {'wish': '平安', 'origin': '国贸'}
    first = tc.build_temple_context('不考虑出发地，直接推荐', profile)
    assert first['payload']['items'] and not first['payload']['query']['origin_text']
    second = tc.build_temple_context('东城区', profile, first['session'])
    assert not second['payload']['query']['origin_text']
    nearby = tc.build_temple_context('那还是就近找吧', profile, second['session'])
    # A retained destination district can be used without demanding a street address.
    assert nearby is not None
    fresh = tc.build_temple_context('附近求平安的地方')
    assert fresh['payload']['clarification']


def test_bare_district_recovers_after_an_old_session_was_lost():
    built = tc.build_temple_context('东城区', {'wish': '平安'})
    assert built['payload']['items']
    assert all(t['district'] == '东城区' for t in built['payload']['items'])


def test_data_denial_is_replaced_with_existing_candidates_but_clarification_is_preserved():
    payload = tc.build_temple_context(TRANSCRIPT[0])['payload']
    text = recover_recommendation('这次没有查到可用的寺庙资料，硬推就是编了。', payload)
    assert payload['items'][0]['name'] in text
    assert '没有查到' not in text
    clarification = tc.build_temple_context('附近找个求平安的')['payload']
    assert recover_recommendation('先确认出发区域。', clarification) == '先确认出发区域。'


def test_region_is_filtered_not_just_given_a_small_bonus():
    rows = temples.search_temples(district='东城区')
    assert rows and all(t['district'] == '东城区' for t in rows)


@pytest.mark.parametrize('output, expected', [
    ({'related': True, 'unrestricted': True}, {'related': True, 'unrestricted': True}),
    ({'related': False, 'unrestricted': False}, {'related': False, 'unrestricted': False}),
    ({'related': 'true', 'unrestricted': False}, None), ({}, None),
])
def test_semantic_followup_requires_valid_booleans(monkeypatch, output, expected):
    from app.gateway import llm_gateway
    monkeypatch.setattr(llm_gateway, 'has_llm', lambda: True)
    monkeypatch.setattr(llm_gateway, 'chat_json', lambda *a, **kw: output)
    assert interpret_followup('给个你认为值得去的就行', [{'user': TRANSCRIPT[0]}]) == expected


def test_api_replays_user_transcript_even_when_model_repeats_old_denial(client, fake_llm, monkeypatch):
    from app.agent.subgraphs import chat
    monkeypatch.setattr(chat, '_llm_risk', lambda msg: False)
    fake_llm.reply = '这次没有查到可用的寺庙资料，硬推就是编了。'
    uid = 'recovery-' + uuid.uuid4().hex
    tid = None
    for message in TRANSCRIPT:
        body = {'user_id': uid, 'message': message}
        if tid: body['thread_id'] = tid
        result = client.post('/api/chat', json=body).json()
        tid = result['thread_id']
        response = result['data']['messages'][-1]['content']
        assert '没有查到可用' not in response
        if message == '海淀区':
            assert '海淀区' in response and '当前资料库' in response
        else:
            card = result['data']['temple_card']
            assert card['items'] and card['wish'] == '平安'
            assert card['items'][0]['name'] in response


def test_api_uses_semantic_interpretation_for_unrecognised_followup(client, fake_llm, monkeypatch):
    from app.agent import temple_followup
    from app.agent.subgraphs import chat
    monkeypatch.setattr(chat, '_llm_risk', lambda msg: False)
    calls = []
    def interpret(message, turns):
        calls.append(message)
        return {'related': '小说' not in message, 'unrestricted': True}
    monkeypatch.setattr(temple_followup, 'interpret_followup', interpret)
    uid = 'semantic-followup-' + uuid.uuid4().hex
    first = client.post('/api/chat', json={'user_id': uid, 'message': TRANSCRIPT[0]}).json()
    tid = first['thread_id']
    second = client.post('/api/chat', json={'user_id': uid, 'thread_id': tid, 'message': '给个你认为值得去的就行'}).json()
    assert second['data']['temple_card']['items']
    assert calls[-1] == '给个你认为值得去的就行'
    third = client.post('/api/chat', json={'user_id': uid, 'thread_id': tid, 'message': '帮我推荐一本小说'}).json()
    assert not third['data'].get('temple_card')


def test_origin_opt_out_hides_missing_field_hint_and_repetitive_complaint():
    payload = tc.build_temple_context('不用管出发地，直接推荐', {'wish': '平安'})['payload']
    assert all(not item['distance_note'] for item in payload['items'])
    name = payload['items'][0]['name']
    reply = recover_recommendation(f'可以考虑{name}。你没给出发地，距离我算不了，只能按区县排。', payload)
    assert name in reply and '没给出发地' not in reply


def test_recommendation_does_not_require_a_choice_card(client, fake_llm, monkeypatch):
    from app.agent.subgraphs import chat
    monkeypatch.setattr(chat, '_llm_risk', lambda msg: False)
    fake_llm.reply = '可以先比较这几处。<ask>{"type":"single","question":"选哪一座？","options":["潭柘寺","戒台寺"]}</ask>'
    result = client.post('/api/chat', json={'user_id': 'optional-choice-' + uuid.uuid4().hex, 'message': TRANSCRIPT[0]}).json()
    assert result['data']['temple_card']['items']
    assert not result['data'].get('ask')


def test_peace_context_does_not_send_unrelated_wish_labels_to_model():
    payload = tc.build_temple_context(TRANSCRIPT[0])['payload']
    assert all(not row['wish_themes'] and not row['halls'] for row in payload['items'])
    name = payload['items'][0]['name']
    text = recover_recommendation(f'{name}没有专门的平安类说法。', payload)
    assert name in text and '没有专门的平安' not in text


def test_recommendation_card_explains_environment_and_effort_from_the_same_records():
    from app.agent.temple_card import build_card
    payload = tc.build_temple_context(TRANSCRIPT[0])['payload']
    card = build_card(payload)
    for row, item in zip(payload['items'], card['items']):
        assert item['atmosphere'] == row['atmosphere']
        assert item['accessibility'] == row['accessibility']
