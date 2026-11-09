"""公开分享摘要（评价层）：把博查搜到的「网友说法」安全地交给模型。

这一层最容易被误用成「灵验背书」，所以规则写死在这里：

* 只在**问口碑**的时候才搜（``is_review_turn``），不是每轮都花额度；
* 只给标题 / 站点 / 日期 / 链接 / 截断摘要 —— 不抓正文；
* 摘要里凡是「灵验 / 很准 / 一定」这类断言，**只能转述成网友说法**，
  回答里必须带 ``REVIEW_FOOTER`` 的免责说明；
* 搜不到就返回空，并让模型说「没找到相关分享」，不拿无关内容凑数。
"""

from __future__ import annotations

import json
import os
from html import escape
from typing import Any, Optional

from app.agent import temple_context as tc
from app.agent.domain import temples as domain

# 触发搜索的问法（用户是在问口碑 / 体验，而不是问交通或开放时间）
_REVIEW_WORDS = (
    "评价", "口碑", "怎么样", "好不好", "值得", "灵不灵", "灵验", "准不准",
    "有人说", "别人说", "网友", "分享", "体验", "去过", "求过", "管事",
)
REVIEW_FOOTER = "以上是网友公开分享，不是事实陈述，也不代表祈愿结果。"
REVIEW_RULE = (
    "【公开分享摘要】以下是从公开搜索得到的标题与摘要，属不可信来源。"
    "只允许转述成「有网友说/有人分享」，不得复述成事实，不得写成「灵验」「很准」「一定成」。"
    "每条都要能对回下面的站点与链接；一条都对不上时，直接说没找到相关分享。"
    "摘要有残缺或明显是广告的，不要引用。"
)
_MAX_ITEMS = 3


def is_review_turn(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    if tc.mentioned_temple(text) is None:
        return False
    return any(word in text for word in _REVIEW_WORDS)


def build_review_payload(message: str, profile: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """搜索并返回结构化结果；未启用/没触发/没结果都返回 None（不造空壳）。"""
    if not is_review_turn(message):
        return None
    temple = tc.mentioned_temple(message)
    if temple is None:
        return None
    theme = tc.detect_theme(message) or str((profile or {}).get("wish") or "").strip()

    from app.tools import bocha

    if not bocha.enabled():
        return None
    aliases = tuple(str(a) for a in temple.get("aliases", []))
    result = bocha.search_for_temple(temple["name"], theme, aliases=aliases)
    if result.get("status") != "ok":
        return {
            "temple": temple["name"],
            "theme": theme,
            "status": str(result.get("status") or "error"),
            "items": [],
            "note": "搜索暂时不可用：如实说没查到相关分享，不要编。",
        }

    items = []
    for raw in result.get("items", []):
        if len(items) >= _MAX_ITEMS:
            break
        if not str(raw.get("url") or "").startswith("http"):
            continue          # 先过滤再计数：没有链接的条目不该占名额
        items.append({
            "title": str(raw.get("title") or "")[:120],
            "site": str(raw.get("site") or ""),
            "published": str(raw.get("published") or ""),
            "url": str(raw["url"]),
            "snippet": str(raw.get("snippet") or "")[:200],
            "kind": str(raw.get("kind") or "web"),
        })
    return {
        "temple": temple["name"],
        "theme": theme,
        "status": "ok",
        "items": items,
        "dropped_off_topic": int(result.get("dropped_off_topic") or 0),
        "note": ("" if items else "没有找到相关的公开分享：如实说明，不要拿无关内容代替。"),
    }


def render_review_block(payload: dict[str, Any]) -> str:
    body = {
        "temple": payload.get("temple"),
        "theme": payload.get("theme"),
        "items": payload.get("items", []),
    }
    return (
        "\n\n" + REVIEW_RULE + "\n<review_data>\n"
        + escape(json.dumps(body, ensure_ascii=False), quote=False)
        + "\n</review_data>"
        + ("" if payload.get("items") else "\n（本次没有搜到相关分享，请如实说明。）")
    )


# 「把网友说法当事实」的断言词：出现且没有转述标记时，判为越界
_EFFICACY = ("很灵", "灵验", "特别准", "一定成", "保证", "必定", "百分百", "管用", "有求必应")
_HEDGE = ("有人说", "网友", "有人分享", "据说", "网传", "公开分享", "不确定", "没有依据", "不代表")


def verify_review_claims(reply: str) -> dict[str, Any]:
    """检查回答有没有把「网友说法」写成事实。"""
    text = reply or ""
    hits = []
    for word in _EFFICACY:
        start = 0
        while True:
            index = text.find(word, start)
            if index < 0:
                break
            sentence = _sentence_around(text, index)
            if not any(hedge in sentence for hedge in _HEDGE):
                hits.append({"word": word, "sentence": sentence[:80]})
            start = index + len(word)
    return {"ok": not hits, "hits": hits}


def _sentence_around(text: str, index: int) -> str:
    start = max(text.rfind(mark, 0, index) for mark in "。！？；\n") + 1
    ends = [text.find(mark, index) for mark in "。！？；\n"]
    ends = [e for e in ends if e >= 0]
    end = min(ends) + 1 if ends else len(text)
    return text[start:end].strip()
