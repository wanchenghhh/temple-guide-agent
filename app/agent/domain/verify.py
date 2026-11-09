"""答案引用校验：把「不编造」从口号变成可检验的动作。

PRD 的上线门槛是「抽查答案能否回到有效原文，编造一条即不算过关」。
这里的实现是确定性的、可测试的，不调用模型：

1. **链接白名单**：回答里出现的任何 http(s) 链接，必须在本次注入的资料里出现过。
   编造的链接会被删掉（这是最危险的一类错误）。
2. **风险数字**：价格（元）、时间（HH:MM / 点）、距离（公里/km）、百分比（%），
   必须能在本次注入的资料里找到同样的数字。找不到就标记为「无出处数字」，
   由调用方补一句「以官方公告为准」，并把命中记进轨迹。
3. **来源口径**：`sources_status=unverified` 的资料被当作「已核实」引用时也记一笔。

限制（诚实说明）：这不是自然语言的语义校验，抓不到「把 A 殿的说法安到 B 殿」这类
错误归因——那种只能靠人工抽查。这里先把最容易出错、也最好机器判的两类拦住。
"""

from __future__ import annotations

import json
import re
from typing import Any

_URL = re.compile(r"https?://[^\s<>\"'）)】\]]+")
# 价格、时刻、距离、百分比——这几类一旦编错，用户会直接吃亏
_PRICE = re.compile(r"(?<![\d.])(\d{1,6}(?:\.\d+)?)\s*(?:元|块钱|块)")
_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)")
_CLOCK = re.compile(r"(?<![\d:])([01]?\d|2[0-3])\s*点(?:半|(?:\d{1,2})\s*分)?")
_DIST = re.compile(r"(?<![\d.])(\d{1,4}(?:\.\d+)?)\s*(?:公里|千米|km|KM)")
_PCT = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%")
# 温度：行前数据里是数值字段，回答里通常写成「-3℃」「12 度」
_TEMP = re.compile(r"(-?\d{1,2})\s*(?:℃|°C|度)")
# 行前数据是 JSON 数字（distance_km / temp_max…），也要能进对应的池子
_JSON_NUM = re.compile(r'"([a-z_]+)"\s*:\s*(-?\d+(?:\.\d+)?)')

# 允许出现的「非资料」数字：电话号码、热线、年份等不参与判定
_PHONE = re.compile(r"(?<!\d)(?:0\d{2,3}[-\s]?\d{7,8}|1[3-9]\d{9}|[12]0{2})(?!\d)")
_YEAR = re.compile(r"(?<!\d)(1[6-9]\d{2}|20\d{2})(?!\d)")


def _payload_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload


def allowed_urls(payload: Any) -> set[str]:
    """本次注入资料里出现过的所有 URL（含来源、场所事实、坐标出处）。"""
    return {u.rstrip(".,;，。；、") for u in _URL.findall(_payload_text(payload))}


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,;，。；、") for u in _URL.findall(text or "")]


def strip_foreign_urls(reply: str, payload: Any) -> tuple[str, list[str]]:
    """删掉不在白名单里的链接，并返回被删列表。"""
    allowed = allowed_urls(payload)
    removed: list[str] = []

    def _drop(match: re.Match[str]) -> str:
        url = match.group(0)
        clean = url.rstrip(".,;，。；、")
        if clean in allowed:
            return url
        removed.append(clean)
        return "（来源链接未核实，已隐去）"

    return _URL.sub(_drop, reply or ""), removed


_NUM_TOKEN = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])")
_CLOCK_SPAN = re.compile(r"\d{1,2}\s*[:：]\s*\d{2}")


def _numeric_tokens(text: str) -> set[str]:
    """把文本里「独立的数字」取出来，先把时刻（16:30）整体剔除。

    否则「30 元」会被「16:30」里的 30 蒙过关——这正是要抓的编造价格。
    """
    stripped = _CLOCK_SPAN.sub(" ", text or "")
    return {m.group(0) for m in _NUM_TOKEN.finditer(stripped)}


# 距离允许四舍五入/取整：资料写 24.0，回答写「24 公里」是同一个数；
# 也允许「都在 20 公里出头」这类就近概括（20.9 → 20 差 0.9），
# 但编一个差 5 公里的数仍会被抓住。
_DIST_TOLERANCE = 1.5


def _tokens_by_kind(haystack: str) -> dict[str, set[str]]:
    """把资料里的数字按「价格 / 时间 / 距离 / 百分比」分区。

    必须分区：资料里有「20 元」不代表可以写「20 公里」——
    混在一起比对，编造的距离会借价格的数字蒙混过关。
    """
    text = _PHONE.sub(" ", haystack or "")
    text = _YEAR.sub(" ", text)
    out: dict[str, set[str]] = {"价格": set(), "时间": set(), "时刻": set(),
                                "距离": set(), "百分比": set()}
    out["价格"] = {m.group(1) for m in _PRICE.finditer(text)}
    out["时间"] = {f"{m.group(1)}:{m.group(2)}" for m in _TIME.finditer(text)}
    out["时刻"] = {f"{m.group(1)}点" for m in _CLOCK.finditer(text)}
    out["距离"] = {m.group(1) for m in _DIST.finditer(text)}
    out["百分比"] = {m.group(1) for m in _PCT.finditer(text)}
    out["温度"] = {m.group(1) for m in _TEMP.finditer(text)}
    for key, value in _JSON_NUM.findall(text):
        if "km" in key or "distance" in key:
            out["距离"].add(value)
        elif "temp" in key:
            out["温度"].add(value)
    return out


def _number_appears(value: str, tokens: dict[str, set[str]], kind: str) -> bool:
    pool = tokens.get(kind, set())
    if value in pool:
        return True
    if kind == "时间":
        alt = {value.replace(":", "："), value.replace(":", "")}
        return bool(pool & alt)
    if kind == "距离":
        try:
            target = float(value)
        except ValueError:
            return False
        for token in pool:
            try:
                if abs(float(token) - target) <= _DIST_TOLERANCE:
                    return True
            except ValueError:
                continue
    return False


def unsupported_numbers(reply: str, payload: Any) -> list[dict[str, str]]:
    """找出回答里「资料中没有」的价格/时间/距离/百分比。

    做法朴素但可靠：同一个数字必须能在注入资料里找到。
    例：资料写「20 元」，回答写「30 元」→ 命中。
    """
    text = reply or ""
    hay = _payload_text(payload)
    # 电话号码和年份不当作事实数字，避免误报
    text = _PHONE.sub(" ", text)
    text = _YEAR.sub(" ", text)
    tokens = _tokens_by_kind(hay)

    hits: list[dict[str, str]] = []
    for label, pattern, extract in (
        ("价格", _PRICE, lambda m: m.group(1)),
        ("时间", _TIME, lambda m: f"{m.group(1)}:{m.group(2)}"),
        ("时刻", _CLOCK, lambda m: f"{m.group(1)}点"),
        ("距离", _DIST, lambda m: m.group(1)),
        ("百分比", _PCT, lambda m: m.group(1)),
        ("温度", _TEMP, lambda m: m.group(1)),
    ):
        for match in pattern.finditer(text):
            value = extract(match)
            if _number_appears(value, tokens, label):
                continue
            hits.append({"kind": label, "value": value, "raw": match.group(0)})
    return hits


def verify_citation(reply: str, payload: Any, *, where: str = "chat") -> dict[str, Any]:
    """跑完全部引用检查，返回可直接写进轨迹的报告。

    返回 ``text`` 是清洗后的回答（只删不明链接，不改数字）。
    """
    forced = "未核实" in _payload_text(payload) and "sources_status" in _payload_text(payload)
    cleaned, removed = strip_foreign_urls(reply, payload)
    numbers = unsupported_numbers(cleaned, payload)
    report = {
        "where": where,
        "urls_checked": len(extract_urls(reply or "")),
        "urls_removed": removed,
        "unsupported_numbers": numbers,
        "payload_has_unverified_sources": bool(forced),
        "ok": not removed and not numbers,
    }
    return {"text": cleaned, "report": report}
