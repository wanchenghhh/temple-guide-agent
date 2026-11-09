"""User-facing regressions for peace wishes, clarification and thread follow-ups."""
import uuid

from app.agent import temple_context as tc
from app.agent.temple_card import build_card


def test_peace_without_location_asks_one_question_instead_of_reporting_no_match():
    built = tc.build_temple_context('我想找个求平安的')
    payload = built['payload']
    assert payload['query']['message_theme'] == '平安'
    assert payload['clarification']
    assert payload['items'] == []
    assert 'missing' not in payload
    assert '没有专门' not in built['block']
    assert build_card(payload) is None


def test_location_answer_continues_peace_wish():
    first = tc.build_temple_context('我想找个求平安的')
    second = tc.build_temple_context('国贸', session=first['session'])
    payload = second['payload']
    assert not payload['clarification']
    assert payload['query']['message_theme'] == '平安'
    assert payload['query']['origin_matched'] == '国贸'
    assert payload['items']
    card = build_card(payload)
    assert card['wish'] == '平安'
    assert all(not item['wishes'] for item in card['items'])


def test_ordinal_then_pronoun_follows_actual_candidates():
    first = tc.build_temple_context('从国贸出发，求平安')
    expected = first['payload']['items'][1]['name']
    second = tc.build_temple_context('第二个怎么样', session=first['session'])
    assert second['payload']['query']['named_temple'] == expected
    third = tc.build_temple_context('那里怎么去', session=second['session'])
    assert third['payload']['query']['named_temple'] == expected
    assert expected in third['resolved_message']


def test_ambiguous_pronoun_asks_instead_of_picking_a_temple():
    first = tc.build_temple_context('从国贸出发，求平安')
    second = tc.build_temple_context('那里人多吗', session=first['session'])
    assert second['payload']['clarification']
    assert not second['payload']['items']


def test_nearby_without_origin_clarifies_and_nearest_request_changes_order():
    first = tc.build_temple_context('附近求姻缘去哪')
    assert first['payload']['clarification']
    second = tc.build_temple_context('国贸', session=first['session'])
    distances = [i['distance_km'] for i in second['payload']['items']]
    assert len(distances) > 1
    assert distances == sorted(distances)


def test_explicit_wish_correction_and_new_task():
    assert tc.detect_theme('不是求子，是求平安') == '平安'
    assert tc.detect_theme('不求姻缘，想求事业') == '事业'
    first = tc.build_temple_context('从国贸出发求平安')
    assert tc.build_temple_context('这个代码怎么改', session=first['session']) is None
    named = tc.build_temple_context('雍和宫求什么比较合适')
    assert not named['payload']['clarification']


def test_chat_api_clarification_then_location_then_review(client, fake_llm, monkeypatch):
    from app.agent.subgraphs import chat
    from app.tools import bocha
    monkeypatch.setattr(chat, '_llm_risk', lambda message: False)
    monkeypatch.setattr(bocha, 'enabled', lambda: True)
    searches = []
    def search(name, theme, **kwargs):
        searches.append((name, theme))
        return {'status': 'ok', 'items': []}
    monkeypatch.setattr(bocha, 'search_for_temple', search)
    uid = 'peace-flow-' + uuid.uuid4().hex
    first = client.post('/api/chat', json={'user_id': uid, 'message': '我想找个求平安的'}).json()
    assert '出发' in first['data']['messages'][-1]['content']
    assert not first['data'].get('temple_card')
    tid = first['thread_id']
    second = client.post('/api/chat', json={'user_id': uid, 'thread_id': tid, 'message': '国贸'}).json()
    card = second['data']['temple_card']
    assert card['wish'] == '平安' and card['origin_name'] == '国贸'
    expected = card['items'][1]['name']
    third = client.post('/api/chat', json={'user_id': uid, 'thread_id': tid, 'message': '第二个怎么样'}).json()
    assert third['data']['temple_card']['items'][0]['name'] == expected
    assert searches[-1] == (expected, '平安')
    # Fresh threads cannot inherit the selection from this thread.
    fresh = client.post('/api/chat', json={'user_id': uid, 'message': '第二个怎么样'}).json()
    assert not fresh['data'].get('temple_card')


def test_district_only_answer_resolves_location_question():
    first = tc.build_temple_context('想求平安')
    second = tc.build_temple_context('朝阳区', session=first['session'])
    assert second['payload']['query']['district'] == '朝阳区'
    assert not second['payload']['clarification']
    assert second['payload']['items']


def test_session_is_invalidated_with_memory_revision_or_thread(uid):
    from app.agent.context_assembler import conversation_state
    from app.agent.memory import profile
    saved = conversation_state({'user_id': uid, 'thread_id': 'temple-one'})
    saved['temple_session'] = {'wish': '平安', 'focus': 'yonghegong'}
    state = {'user_id': uid, 'thread_id': 'temple-one', 'conversation_context': saved}
    assert conversation_state(state)['temple_session']['focus'] == 'yonghegong'
    assert 'temple_session' not in conversation_state({**state, 'thread_id': 'temple-two'})
    profile.merge(uid, {'memory_rev': saved['memory_rev'] + 1})
    assert 'temple_session' not in conversation_state(state)


def test_user_can_decline_location_constraint_without_repeated_question():
    first = tc.build_temple_context('想求平安')
    second = tc.build_temple_context('哪里都行，我愿意专程去', session=first['session'])
    assert not second['payload']['clarification']
    assert second['payload']['items']
    assert second['payload']['query']['message_theme'] == '平安'
