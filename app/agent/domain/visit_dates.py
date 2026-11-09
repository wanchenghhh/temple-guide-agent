"""Resolve visit dates in the product timezone without guessing holidays."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def today_in_beijing() -> date:
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def parse_visit_date(message: str, *, today: date | None = None) -> dict:
    today = today or today_in_beijing()
    text = message or ''
    result = {'mentioned': False, 'date': '', 'clarification': '', 'special_notice': False}
    if any(word in text for word in ('日期未定', '时间未定', '还没定时间', '还没定日期', '不限日期', '先不定日期')):
        return {**result, 'mentioned': True}
    special = any(word in text for word in ('春节', '国庆', '五一', '元旦', '清明', '端午', '中秋', '节假日', '假期'))
    result['special_notice'] = special
    values: list[date] = []
    invalid = False
    # Explicit years are honored; an omitted year means this year and is shown to the user.
    pattern = r'(?:(\d{4})[年/-])?(\d{1,2})(?:月|[/-])(\d{1,2})(?:[日号])?'
    for match in re.finditer(pattern, text):
        result['mentioned'] = True
        try:
            values.append(date(int(match[1] or today.year), int(match[2]), int(match[3])))
        except ValueError:
            invalid = True
    for word, offset in (('今天', 0), ('明天', 1), ('后天', 2)):
        if word in text and not re.search(r'(?:不是|不去|不选)' + word, text):
            result['mentioned'] = True
            values.append(today + timedelta(days=offset))
    for match in re.finditer(r'(下下|下|本|这)?(?:周|星期|礼拜)([一二三四五六日天])', text):
        prefix = text[:match.start()]
        if re.search(r'(?:不是|不去|不选)$', prefix):
            continue
        result['mentioned'] = True
        weekday = '一二三四五六日'.find(match[2].replace('天', '日'))
        monday = today - timedelta(days=today.weekday())
        week = match[1] or ''
        offset = {'下下': 14, '下': 7, '本': 0, '这': 0, '': 0}[week]
        chosen = monday + timedelta(days=offset + weekday)
        if not week and chosen < today:
            chosen += timedelta(days=7)
        values.append(chosen)
    if invalid:
        result['clarification'] = '这个日期无效。你想哪年哪月哪日去？'
    elif len(set(values)) > 1:
        result['clarification'] = '你提到了多个日期。这次先按哪一天帮你筛选？'
    elif values:
        chosen = values[0]
        result['date'] = chosen.isoformat()
        if chosen < today:
            result['clarification'] = f'{chosen.isoformat()}已经过去了。你想按哪一年或哪一天安排？'
    elif any(word in text for word in ('周末', '星期末')):
        result['mentioned'] = True
        result['clarification'] = '你想周六还是周日去？确定哪一天后，我帮你检查开放与预约要求。'
    elif any(word in text for word in ('下个月', '下月', '月底', '月初', '下周', '下星期', '下礼拜')):
        result['mentioned'] = True
        result['clarification'] = '你具体想哪一天去？确定日期后我再核对开放与预约要求。'
    elif special:
        result['mentioned'] = True
        result['clarification'] = '假期不同日期的开放安排可能不同。你具体想哪年哪月哪日去？'
    return result
