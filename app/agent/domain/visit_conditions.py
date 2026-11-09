"""Use recorded descriptions to compare constraints, preserving unknowns."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.agent.domain.visit_dates import parse_visit_date


def extract_conditions(message: str, previous: dict | None = None, *, today: date | None = None) -> dict:
    conditions = dict(previous or {})
    text = message or ''
    if any(word in text for word in ('不带老人', '不带父母', '爸妈不去了', '父母不去了', '自己去', '一个人去')):
        conditions['elderly'] = False
    elif any(word in text for word in ('带老人', '陪老人', '带父母', '陪父母', '和父母', '爸妈', '老年人')):
        conditions['elderly'] = True
    if any(word in text for word in ('可以爬山', '不介意爬山', '不怕爬山', '能爬山', '爬山没问题', '不用考虑爬山')):
        conditions['no_climbing'] = False
    elif any(word in text for word in ('不爬山', '不想爬山', '不能爬山', '爬不动', '少走路', '走不动', '腿脚不便', '腿脚不方便')):
        conditions['no_climbing'] = True
    if any(word in text for word in ('不用安静', '不在意人多', '热闹点', '热闹一点', '不怕人多', '安静不重要')):
        conditions['quiet'] = False
    elif any(word in text for word in ('安静', '清静', '清幽', '人少', '不拥挤', '不太热闹')):
        conditions['quiet'] = True
    date_text = text
    # Preserve 'next weekend' while the user answers the Saturday/Sunday question.
    pending = conditions.get('date_reference') or ''
    week = re.search(r'(下下|下|本|这)(?:周|星期|礼拜)', pending)
    if conditions.get('date_clarification') and week and re.fullmatch(r'(?:周|星期|礼拜)[六日天](?:去)?', text.strip()):
        date_text = week[1] + text.strip()
    parsed = parse_visit_date(date_text, today=today)
    if parsed['mentioned']:
        conditions['visit_date'] = parsed['date']
        conditions['date_clarification'] = parsed['clarification']
        conditions['special_notice'] = parsed['special_notice']
        conditions['date_reference'] = date_text if parsed['clarification'] else ''
    return conditions


def is_condition_update(message: str) -> bool:
    return bool(extract_conditions(message))


def _check(condition: str, status: str, text: str, *, evidence: str = '', source: str = '', checked_at: str = '') -> dict:
    return {'condition': condition, 'status': status, 'text': text, 'evidence': evidence,
            'source': source, 'checked_at': checked_at}


def _official_open_rule(temple: dict) -> bool:
    evidence = temple.get('open_evidence') or {}
    if evidence:
        return evidence.get('grade') == 'A'
    # Legacy records must explicitly attribute the opening rule to an official source.
    return str(temple.get('open_note') or '').startswith('官方') and any(
        source.get('kind') == 'official' for source in temple.get('sources', [])
    )


def date_feasibility(temple: dict, visit_date: str, *, special_notice: bool = False) -> dict:
    day = date.fromisoformat(visit_date)
    rules = temple.get('closure_rule') or []
    note = temple.get('open_note') or ''
    evidence = temple.get('open_evidence') or {}
    source = evidence.get('source') or ''
    checked_at = temple.get('open_verified_at') or temple.get('checked_at') or ''
    quoted = '；'.join(rules) or note
    official = _official_open_rule(temple)
    status = 'conditional'
    explanation = f'{visit_date}按已收录的常规规则未发现固定闭馆冲突；当天临时公告与预约仍需确认。'
    weekly_closed = any(re.search(r'(?:周|星期)' + '一二三四五六日'[day.weekday()], rule) for rule in rules)
    exception = any(word in quoted + note for word in ('节假日', '节日期间', '假期'))
    open_uncertain = bool(re.search(r'(?:开放(?:时间|时段|安排)|是否对外开放)[^。；;]{0,24}(?:未核实|待核|尚未确认)', note))
    if temple.get('open_status') == 'closed':
        status, explanation = 'conflict', f'{visit_date}不建议前往：资料标记为关闭。'
    elif weekly_closed and official and not exception and not special_notice:
        status, explanation = 'conflict', f'{visit_date}与已收录的固定闭馆规则冲突：{"；".join(rules)}。'
    elif (temple.get('open_status') in ('unverified', 'limited') or not official
          or open_uncertain or special_notice or (weekly_closed and exception)
          or any(word in '；'.join(rules) for word in ('农历', '初一', '十五', '诞辰', '冬季', '公告'))):
        status, explanation = 'unknown', f'{visit_date}能否参访尚不能确认，需要核实当天公告或联系场所。'
    return _check('visit_date', status, explanation, evidence=quoted, source=source, checked_at=checked_at)


def assess_conditions(temple: dict, conditions: dict | None = None) -> dict:
    conditions = conditions or {}
    access = temple.get('accessibility') or ''
    atmosphere = temple.get('atmosphere') or ''
    checks = []
    mountain = bool(re.search(r'山间|山地|山路|山区|需爬山|爬山|体力要求(?:中等偏高|较高|高)', re.sub(r'无需爬山|不用爬山|不需爬山', '', access)))
    flat = bool(re.search(r'院落(?:较)?平(?:缓|整)|台阶不多|台阶少|无需爬山|不用爬山', access))
    long_walk = '步行较远' in access
    if conditions.get('no_climbing'):
        status = 'conflict' if mountain or long_walk else 'match' if flat else 'unknown'
        text = {'conflict': '现有体力描述与少爬山、少走路的要求有冲突。',
                'match': '现有资料描述院落较平缓或台阶较少，仍需核实具体参访路线。',
                'unknown': '尚不能确认是否满足不爬山、少走路的要求。'}[status]
        checks.append(_check('no_climbing', status, text, evidence=access))
    if conditions.get('elderly'):
        status = 'conflict' if mountain or long_walk else 'match' if flat else 'unknown'
        text = {'conflict': '带长辈同行需权衡山路、台阶或较长步行距离。',
                'match': '现有体力描述较平缓，可优先比较；不等同于全程无台阶或无障碍。',
                'unknown': '带长辈的体力适配情况待核实。'}[status]
        checks.append(_check('elderly', status, text, evidence=access))
    if conditions.get('quiet'):
        positive = bool(re.search(r'安静|宁静|清幽|清静|闹中取静|游客少|游客相对少|静心', atmosphere))
        busy = bool(re.search(r'香火(?:最)?旺|热闹|游客多|排队|人气最高|人多', atmosphere))
        status = 'match' if positive and not busy else 'conflict' if busy and not positive else 'unknown'
        text = {'match': '资料描述较清幽；指定日期的人流尚未核实。',
                'conflict': '资料描述偏热闹，与安静偏好有取舍。',
                'unknown': '是否符合安静偏好尚不能确认，不能保证当天人少。'}[status]
        checks.append(_check('quiet', status, text, evidence=atmosphere))
    if conditions.get('visit_date'):
        checks.append(date_feasibility(temple, conditions['visit_date'], special_notice=bool(conditions.get('special_notice'))))
    by_name = {check['condition']: check for check in checks}
    excluded = any(check['status'] == 'conflict' and check['condition'] in ('no_climbing', 'visit_date') for check in checks)
    # Known hard-constraint fit first, then softer preferences. Unknown is never called satisfied.
    priority = tuple({'match': 0, 'conditional': 0, 'unknown': 1, 'conflict': 2}.get(by_name.get(name, {}).get('status'), 0)
                     for name in ('visit_date', 'no_climbing', 'elderly', 'quiet'))
    return {'excluded': excluded, 'priority': priority, 'checks': checks}


def booking_guidance(temple: dict, visit_date: str = '') -> dict[str, Any]:
    note = temple.get('open_note') or ''
    reservation = 'unknown'
    mixed = ('免预约' in note or '无需预约' in note) and ('需预约' in note.replace('无需预约', '') or '需提前预约' in note)
    if mixed:
        reservation = 'mixed'
    elif any(word in note for word in ('是否需预约', '是否需要预约', '预约要求未核')) or temple.get('open_status') == 'unverified':
        reservation = 'unknown'
    elif any(word in note for word in ('无需预约', '免预约', '不用预约')):
        reservation = 'not_required'
    elif temple.get('open_status') == 'reservation' or any(word in note for word in ('需提前预约', '需预约', '需公众号提前预约', '门票需预约')):
        reservation = 'required'
    window = ''
    opens_at = ''
    # Only a stated calendar-day release rule supports subtracting days.
    match = re.search(r'(?:可|可以)提前\s*(\d+)\s*(?:个)?天(?:预约|购票)|提前\s*(\d+)\s*(?:个)?天(?:开放预约|放票)', note)
    if match:
        window = match[0]
        if visit_date:
            opens_at = (date.fromisoformat(visit_date) - timedelta(days=int(match[1] or match[2]))).isoformat()
    else:
        match = re.search(r'(?:至多|最多)?提前\s*\d+\s*个?开放日', note)
        if match:
            window = match[0] + '；具体开放日与放票时间请向官方确认'
    evidence = temple.get('open_evidence') or {}
    official = _official_open_rule(temple)
    if not official:
        reservation = 'unknown'
        opens_at = ''
    return {
        'reservation': reservation, 'recorded_rule': note, 'window': window,
        'booking_opens_on': opens_at, 'availability': 'unknown',
        'availability_note': '尚未查询指定日期的实时余票或预约名额。',
        'timing_note': '' if window else '资料未明确放票时间，请先向官方渠道查询。',
        'channels': list(temple.get('finder_hint') or []),
        'rule_source': evidence.get('source') or '',
        'checked_at': temple.get('open_verified_at') or temple.get('checked_at') or '',
        'evidence_grade': evidence.get('grade') or ('A' if official else 'unverified'),
    }
