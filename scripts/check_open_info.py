#!/usr/bin/env python
"""每周开放信息巡检：只读抓 A 级官方公告页，产出差异候选报告。

用法::

    python scripts/check_open_info.py                  # 全量巡检
    python scripts/check_open_info.py --temple 卧佛寺   # 只查一座
    python scripts/check_open_info.py --dry-run        # 不落盘，只打印摘要
    python scripts/check_open_info.py --delay 2        # 每条请求间隔秒数

设计原则（与 scripts/check_links.py 一致）：
* 只读：绝不修改 temples.json。快照/候选/报告写到 docs/。
* 不自动判定：正则命中的片段只是「候选」，必须人工确认后，
  用 apply_open_info.py --method official_web --source-kind official 落地。
* 低频：串行、每条间隔 2 秒、只 GET、带可识别 UA、不登录、不碰公众号/小程序。
* 失败不静默：抓取失败不覆盖上次快照，退出码 1。
* 可离线测试：fetch_page 可注入，run() 不依赖真实网络。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "open_info_sources.json"
TEMPLES = ROOT / "app" / "agent" / "domain" / "temples.json"
SNAPSHOTS = ROOT / "docs" / "open-info-snapshots.json"
CANDIDATES = ROOT / "docs" / "open-info-candidates.json"
REPORT = ROOT / "docs" / "open-info-weekly.md"

UA = "TempleGuide/open-info-weekly (public page audit)"

TIME_RE = re.compile(r"(?:[0-2]?\d[:：][0-5]\d)\s*[-–—~～至到]\s*(?:[0-2]?\d[:：][0-5]\d)")
MONEY_RE = re.compile(r"\d+(?:\.\d+)?\s*元")
CLOSURE_RE = re.compile(r"周[一二三四五六日天](?:闭馆|闭园|不开放)|(?:周一|周二)[^。；\n]{0,12}闭馆|全年[^。；\n]{0,8}(?:无休|开放)")
RESERVE_RE = re.compile(r"无需预约|不用预约|需(?:要)?预约|须预约|实名(?:制)?(?:分时)?预约|分时预约|现场购票|网上预约")
EFFECTIVE_RE = re.compile(r"(?:自|从)\s*\d{1,2}\s*月\s*\d{1,2}\s*日起|\d{1,2}\s*月\s*\d{1,2}\s*日起|\d{4}[-/]\d{1,2}[-/]\d{1,2}")
STOP_RE = re.compile(r"停止(?:售票|入馆|入园|检票)[^。；\n]{0,14}")
KEYWORDS = ("开放时间", "门票", "票价", "闭馆", "闭园", "预约", "恢复开放",
            "暂停开放", "调整", "公告", "停止", "开放", "元")

FIELDS = {
    "hours": TIME_RE, "ticket": MONEY_RE, "closure": CLOSURE_RE,
    "reservation": RESERVE_RE, "effective": EFFECTIVE_RE, "stop": STOP_RE,
}

REVIEW_CHANGES = ("content_changed", "no_signal", "fetch_failed")


@dataclass
class Observation:
    temple: str
    publisher: str
    url: str
    kind: str
    note: str
    fields: list[str]
    status: int | None = None
    error: str = ""
    text_hash: str = ""
    values: dict[str, list[str]] = field(default_factory=dict)
    sentences: list[str] = field(default_factory=list)
    change: str = ""
    new_values: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 400 and not self.error


def to_text(raw: str) -> str:
    """HTML → 纯文本；只用于哈希与片段抽取，不追求还原排版。"""
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def fetch_page(url: str, timeout: float = 20.0, ua: str = UA) -> tuple[int | None, str, str]:
    """单次 GET。返回 (status, text, error)；失败时 text 为空。"""
    req = urllib.request.Request(
        url, method="GET",
        headers={"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9",
                 "Accept-Encoding": "identity"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1_500_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                decoded = raw.decode(charset, errors="replace")
            except (LookupError, TypeError):
                decoded = raw.decode("utf-8", errors="replace")
            # 政府站偶有 GBK 且未声明 charset；乱码时兜底一次。
            if decoded.count("\ufffd") > len(decoded) * 0.02:
                try:
                    alt = raw.decode("gb18030", errors="replace")
                    if alt.count("\ufffd") < decoded.count("\ufffd"):
                        decoded = alt
                except (LookupError, TypeError):
                    pass
            return resp.status, to_text(decoded), ""
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - 报告里只留异常类型
        return None, "", type(exc).__name__


def extract(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """抽出结构化候选值 + 含关键词的原句。只作提示，不下结论。"""
    values: dict[str, list[str]] = {}
    for name, pattern in FIELDS.items():
        seen: list[str] = []
        for match in pattern.finditer(text):
            value = re.sub(r"\s+", "", match.group(0))[:80]
            if value not in seen:
                seen.append(value)
            if len(seen) >= 8:
                break
        if seen:
            values[name] = seen

    sentences: list[str] = []
    for part in re.split(r"[。；;！!\n]", text):
        part = part.strip()
        if 8 <= len(part) <= 160 and any(k in part for k in KEYWORDS):
            if part not in sentences:
                sentences.append(part)
        if len(sentences) >= 10:
            break
    return values, sentences


def flat(values: dict[str, list[str]]) -> list[str]:
    return [f"{k}:{v}" for k, items in values.items() for v in items]


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run(
    sources: list[dict[str, Any]],
    snapshots: dict[str, Any],
    fetch_fn: Callable[[str, float, str], tuple[int | None, str, str]] = fetch_page,
    *,
    delay: float = 2.0,
    timeout: float = 20.0,
) -> tuple[list[Observation], dict[str, Any]]:
    """执行一轮巡检，返回观测列表与更新后的快照（失败条目保留旧快照）。"""
    observations: list[Observation] = []
    updated = dict(snapshots)
    today = date.today().isoformat()

    for index, src in enumerate(sources):
        obs = Observation(
            temple=src["temple"], publisher=src["publisher"], url=src["url"],
            kind=src.get("kind", "media"), note=src.get("note", ""),
            fields=list(src.get("fields", [])),
        )
        status, text, error = fetch_fn(src["url"], timeout, UA)
        obs.status, obs.error = status, error

        if obs.ok and text:
            obs.text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            obs.values, obs.sentences = extract(text)
            previous = snapshots.get(src["url"])
            if not previous:
                obs.change = "first_seen"
            elif previous.get("hash") != obs.text_hash:
                obs.change = "content_changed"
                before = set(previous.get("values") or [])
                obs.new_values = [v for v in flat(obs.values) if v not in before][:12]
            else:
                obs.change = "unchanged"

            if not obs.values and not obs.sentences:
                obs.change = "no_signal"   # JS 渲染页 / 反爬页 / 改版，需人工看

            updated[src["url"]] = {
                "temple": obs.temple, "publisher": obs.publisher,
                "hash": obs.text_hash, "values": flat(obs.values),
                "checked_at": today, "status": obs.status,
            }
        else:
            obs.change = "fetch_failed"
            # 关键：失败不覆盖快照，否则下周会把「抓不到」误判成「页面变了」。

        observations.append(obs)
        if delay > 0 and index < len(sources) - 1:
            time.sleep(delay)

    return observations, updated


def current_state(temples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        t["name"]: {
            "open_status": t.get("open_status", ""),
            "open_note": (t.get("open_note") or "")[:120],
            "closure_rule": t.get("closure_rule") or [],
            "open_checked_at": t.get("open_checked_at", ""),
        }
        for t in temples
    }


def write_candidates(observations: list[Observation], state: dict[str, dict[str, Any]], today: str) -> dict[str, Any]:
    items = []
    for obs in observations:
        if obs.change not in REVIEW_CHANGES:
            continue
        items.append({
            "temple": obs.temple, "publisher": obs.publisher, "url": obs.url,
            "source_kind": obs.kind, "change": obs.change,
            "status": obs.status, "error": obs.error,
            "new_values": obs.new_values,
            "values": obs.values, "sentences": obs.sentences[:6],
            "note": obs.note, "current": state.get(obs.temple, {}),
            "review_status": "pending_review",
        })
    payload = {"generated_at": today, "count": len(items), "items": items,
               "note": "只读巡检产物。人工确认后由 apply_open_info.py 落地，本文件不写回 temples.json。"}
    CANDIDATES.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def write_report(observations: list[Observation], manual: list[dict[str, Any]],
                 state: dict[str, dict[str, Any]], today: str, total_sources: int) -> str:
    counts: dict[str, int] = {}
    for obs in observations:
        counts[obs.change] = counts.get(obs.change, 0) + 1
    ok = sum(1 for o in observations if o.ok)
    failed = counts.get("fetch_failed", 0)
    review = [o for o in observations if o.change in REVIEW_CHANGES]
    first = [o for o in observations if o.change == "first_seen"]

    lines = [
        "# 开放信息每周巡检",
        "",
        f"> 生成：{today}　·　登记来源 {total_sources} 条　·　本次抓取 {len(observations)} 条"
        f"　·　成功 {ok}　·　**失败 {failed}**　·　内容变化 {counts.get('content_changed', 0)}"
        f"　·　首次基线 {len(first)}　·　无变化 {counts.get('unchanged', 0)}",
        "> **只读巡检：本次没有修改 `temples.json`。** 下面所有命中片段都只是候选，"
        "必须打开原文人工确认后，才可以用 `apply_open_info.py` 落地。",
        "> 只抓无需登录的公开网页，串行且每条间隔 2 秒；不抓公众号/小程序。",
        "",
        "## 一、需要人工确认",
        "",
    ]
    if review:
        lines += ["| 寺庙 | 来源 | 变化 | 新出现的候选值 | 当前数据 | 原链接 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for o in review:
            label = {"content_changed": "页面内容变了", "no_signal": "抓到页面但无有效信号",
                     "fetch_failed": "抓取失败"}[o.change]
            frag = "、".join(o.new_values[:6]) or (o.error or "—")
            cur = state.get(o.temple, {})
            cur_text = f"{cur.get('open_status', '—')}；" + "、".join(cur.get("closure_rule") or []) or "—"
            lines.append(f"| {o.temple} | {o.publisher} | {label} | {frag[:160]} | {cur_text[:60]} | [打开]({o.url}) |")
        lines += ["", "> 「无有效信号」通常是 JS 渲染页、反爬页或页面改版，"
                  "不要当成「没有变化」——请打开链接人工看一眼。", ""]
    else:
        lines += ["本周没有需要确认的变化。", ""]

    lines += ["## 二、抓取失败（不覆盖上次快照）", ""]
    if failed:
        lines += ["| 寺庙 | 来源 | 状态 | 链接 |", "| --- | --- | --- | --- |"]
        lines += [f"| {o.temple} | {o.publisher} | {o.status or o.error} | {o.url} |"
                  for o in observations if o.change == "fetch_failed"]
        lines += ["", "> 连续两周失败就把该来源标为失效；能换 A 级新链接就换，"
                  "换不到就把它从白名单移到下方人工清单，别留着死链冒充可核。", ""]
    else:
        lines += ["无。", ""]

    if first:
        lines += ["<details><summary>首次建立基线（本周新增，不算变更）</summary>", "",
                  "| 寺庙 | 来源 | 抓到的候选值 |", "| --- | --- | --- |"]
        for o in first:
            lines.append(f"| {o.temple} | {o.publisher} | {'、'.join(flat(o.values)[:5]) or '—'} |")
        lines += ["", "</details>", ""]

    lines += ["## 三、未纳入自动巡检（人工 / 电话）", "",
              "| 寺庙 | 优先 | 原因 | 渠道 |", "| --- | --- | --- | --- |"]
    lines += [f"| {m['temple']} | {m['priority']} | {m['reason']} | {m['channel']} |" for m in manual]
    lines += ["",
              "> 这些场所要么没有 A 级公告页，要么公告只在公众号且按农历变动。"
              "有公告时把链接或截图贴进 `docs/open-info-candidates.json`，走同一套人工确认流程。",
              "",
              "## 四、确认后怎么落库",
              "",
              "```bash",
              "# 只看改动，不写盘",
              "python scripts/apply_open_info.py --temple 卧佛寺 --open yes --dry-run \\",
              "    --method official_web --source-kind official",
              "",
              "# 确认无误后落地（只传 kind=official 的 A 级链接）",
              "python scripts/apply_open_info.py --temple 卧佛寺 --open yes \\",
              "    --reservation yes --closure mon --ticket '北园5元＋卧佛寺5元' \\",
              "    --hours '旺季8:00-17:30；淡季8:30-17:00' \\",
              "    --source https://yllhj.beijing.gov.cn/ztxx/kpjd/202312/t20231222_3508032.shtml \\",
              "    --publisher 北京市园林绿化局 --source-kind official --method official_web \\",
              "    --note '按每周巡检报告确认'",
              "```",
              "",
              "> `kind=media` 的链接（如北京旅游网景区页）**只能作变更提示，不能作为 `--source`**。",
              "> 落库后网站会自动读到新数据（`load_dataset` 已按文件修改时间失效缓存），无需重启。",
              "",
    ]

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(REPORT)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="每周开放信息只读巡检")
    ap.add_argument("--temple", default="", help="只巡检某一座")
    ap.add_argument("--dry-run", action="store_true", help="不写快照/候选/报告")
    ap.add_argument("--delay", type=float, default=None, help="每条请求间隔秒数")
    ap.add_argument("--timeout", type=float, default=None, help="单条请求超时")
    args = ap.parse_args(argv)

    config = load_json(CONFIG, None)
    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        print(f"白名单配置不可用：{CONFIG}")
        return 2
    policy = config.get("policy") or {}
    delay = args.delay if args.delay is not None else float(policy.get("request_delay_seconds", 2))
    timeout = args.timeout if args.timeout is not None else float(policy.get("timeout_seconds", 20))

    sources = config["sources"]
    if args.temple:
        sources = [s for s in sources if s.get("temple") == args.temple]
        if not sources:
            print(f"白名单里没有 {args.temple} 的自动巡检来源（可能在 manual 清单里）")
            return 2

    snapshots = load_json(SNAPSHOTS, {})
    if not isinstance(snapshots, dict):
        snapshots = {}
    temples = load_json(TEMPLES, {"temples": []})["temples"]
    state = current_state(temples)
    today = date.today().isoformat()

    observations, updated = run(sources, snapshots, delay=delay, timeout=timeout)
    review = [o for o in observations if o.change in REVIEW_CHANGES]
    failed = [o for o in observations if o.change == "fetch_failed"]

    if not args.dry_run:
        SNAPSHOTS.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_candidates(observations, state, today)
        path = write_report(observations, config.get("manual", []), state, today, len(config["sources"]))
        print(f"报告：{path}")
    else:
        print("--dry-run：未写盘")

    print(f"抓取 {len(observations)} 条｜成功 {sum(1 for o in observations if o.ok)}"
          f"｜失败 {len(failed)}｜需人工确认 {len(review)}")
    for o in failed:
        print(f"  FAIL {o.temple} [{o.status or o.error}] {o.url}")
    for o in review:
        if o.change != "fetch_failed" and o.new_values:
            print(f"  CAND {o.temple}: {'、'.join(o.new_values[:4])}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
