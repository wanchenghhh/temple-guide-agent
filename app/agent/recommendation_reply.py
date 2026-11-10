"""Keep a recommendation's text consistent with the actual retrieved records."""
import re


def recover_recommendation(reply: str, payload: dict | None) -> str:
    if not payload or payload.get('mode') != 'recommend' or payload.get('clarification'):
        return reply
    if payload.get('empty_result_reply'):
        return payload['empty_result_reply']
    items = payload.get('items') or []
    if not items:
        return reply
    denied_data = re.search(r'(?:没(?:有|能)?查到|未(?:能)?查到|没有|缺少)[^。！？\n]{0,25}(?:资料|候选)|硬(?:推|给)[^。！？\n]{0,15}编', reply or '')
    if payload.get('query', {}).get('ignore_origin'):
        reply = re.sub(r'[^。！？\n]*(?:没给|未提供|没有)(?:具体的?)?(?:出发地|位置)[^。！？\n]*(?:算不了|没法|无法|不能|只能)[^。！？\n]*[。！？]?', '', reply or '').strip()
    mentions_candidate = any(item['name'] in (reply or '') for item in items)
    misleading_generic = payload.get('query', {}).get('generic_wish') and re.search(
        r'没有(?:专门的?)?(?:平安(?:类)?(?:说法|标签)|(?:求)?平安的寺)', reply or ''
    )
    if not misleading_generic and (not denied_data or mentions_candidate):
        return reply
    lines = [payload.get('scope_note') or '可以先比较下面几处。']
    for item in items[:3]:
        reasons = [c['text'] for c in item.get('condition_checks', []) if c['condition'] != 'visit_date']
        description = ' '.join(reasons[:2]) or item.get('atmosphere') or item.get('accessibility') or '可以进一步了解其参访情况。'
        lines.append(f"**{item['name']}（{item['district']}）**：{description}")
        date_check = next((c for c in item.get('condition_checks', []) if c['condition'] == 'visit_date'), None)
        if date_check:
            lines.append(date_check['text'])
        elif item.get('closure_rule'):
            lines.append('参访限制：' + '、'.join(item['closure_rule']))
    lines.append('选中一处后，可以继续了解习俗、公开分享和参访准备。')
    return '\n\n'.join(lines)
