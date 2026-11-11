"""Keep a recommendation's text consistent with the actual retrieved records."""
import re


def recover_recommendation(reply: str, payload: dict | None, *, concise: bool = False) -> str:
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
    too_long = concise and len(reply or "") > 240 and "<ask>" not in (reply or "")
    if not too_long and not misleading_generic and (not denied_data or mentions_candidate):
        return reply
    # A grounded brief leaves the full evidence and logistics in the candidate panel.
    lines = ['本次找到：' + '、'.join(item['name'] for item in items[:3]) + '。']
    cautions = []
    for item in items[:3]:
        name = item['name']
        if item.get('status') != 'religious_site':
            cautions.append(f"{name}为{item.get('status_label') or '参观场所'}，需区分参观与宗教祈福")
        checks = item.get('condition_checks') or []
        conflict = next((c for c in checks if c.get('status') == 'conflict'), None)
        uncertain_date = next((c for c in checks if c.get('condition') == 'visit_date' and c.get('status') == 'unknown'), None)
        if conflict:
            cautions.append(name + '：' + conflict['text'])
        elif uncertain_date:
            cautions.append(name + '在计划日期能否参访仍待确认')
    if cautions:
        lines.append('先留意：' + '；'.join(cautions) + '。')
    else:
        lines.append('可以先结合候选中的环境和体力要求比较，选中一处后继续追问。')
    theme = str(payload.get('query', {}).get('message_theme') or '')
    if theme in ('求子', '健康'):
        lines.append('相关祈愿说法仅作民俗文化介绍，不替代专业医疗判断。')
    return '\n\n'.join(lines)
