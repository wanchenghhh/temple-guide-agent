#!/usr/bin/env python
"""每月链接抽查：把「可核来源」从头到尾跑一遍 HTTP 检查。

用法::

    python scripts/check_links.py                 # 全量检查，写报告
    python scripts/check_links.py --only-due       # 只查超过 30 天没核的
    python scripts/check_links.py --write-status   # 把结果写回 temples.json 的 link_status
    python scripts/check_links.py --timeout 15

设计原则：
* 只读：默认不修改数据，报告写到 docs/link-check-report.md；
* 可离线测试：``check_url`` 可注入，测试里不联网；
* 失败不静默：退出码 1，CI 或 cron 能看见。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLES = ROOT / "app/agent/domain/temples.json"
ORIGINS = ROOT / "app/agent/domain/origins.json"
REPORT = ROOT / "docs/link-check-report.md"

UA = {"User-Agent": "TempleGuide/link-check (monthly audit)", "Accept-Language": "zh-CN,zh;q=0.9"}
DUE_DAYS = 30


@dataclass
class Item:
    owner: str          # 寺庙名 or 出发地
    owner_id: str
    kind: str           # 来源 / 场所事实 / 坐标（同一条 URL 可能兼任多个角色）
    url: str
    checked_at: str
    status: int | None = None
    error: str = ""
    stale: bool = False

    @property
    def roles(self) -> set[str]:
        return set(self.kind.split("+"))

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 400


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)
    checked_on: str = ""
    due_only: bool = False

    @property
    def ok_items(self) -> list[Item]:
        return [i for i in self.items if i.ok]

    @property
    def bad_items(self) -> list[Item]:
        return [i for i in self.items if i.status is not None and not i.ok]

    @property
    def skipped(self) -> list[Item]:
        return [i for i in self.items if i.status is None]


def check_url(url: str, timeout: float = 20.0) -> tuple[int | None, str]:
    """HEAD 优先，非成功再 GET。

    很多站点对 HEAD 返回 404/403/405（实际 GET 是 200），
    只信 HEAD 会误报——抽查报告一旦误报，就没人再信它了。
    """
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=UA, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, ""
        except urllib.error.HTTPError as exc:
            if method == "HEAD":
                continue          # 任何 HEAD 失败都用 GET 复核
            return exc.code, f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - 报告里只留类型，不留内容
            if method == "HEAD":
                continue
            return None, type(exc).__name__
    return None, "unreachable"


def _age_days(checked_at: str, today: date) -> int | None:
    try:
        return (today - datetime.strptime(checked_at, "%Y-%m-%d").date()).days
    except Exception:
        return None


def collect(today: date, only_due: bool) -> list[Item]:
    items: list[Item] = []
    temples = json.loads(TEMPLES.read_text(encoding="utf-8"))["temples"]
    by_key: dict[tuple[str, str], Item] = {}

    def add(owner: str, owner_id: str, role: str, url: str, checked_at: str) -> None:
        key = (owner_id, url)
        item = by_key.get(key)
        if item is None:
            item = Item(owner, owner_id, role, url, checked_at)
            by_key[key] = item
            items.append(item)
        elif role not in item.roles:
            # 同一条链接可能既是「来源」又是「场所事实」的出处：角色要合并，不能丢
            item.kind = "+".join(sorted(item.roles | {role}))

    for t in temples:
        for src in t.get("sources", []):
            add(t["name"], t["id"], "来源", src["url"], src.get("checked_at", ""))
        for fact in t.get("place_facts", []):
            url = fact.get("source") or ""
            if url:
                add(t["name"], t["id"], "场所事实", url, fact.get("checked_at", ""))
        coord_src = t.get("coord_source") or ""
        if coord_src:
            add(t["name"], t["id"], "坐标", coord_src, t.get("checked_at", ""))
    for o in json.loads(ORIGINS.read_text(encoding="utf-8"))["origins"]:
        items.append(Item(o["name"], o["name"], "出发地坐标", o["source"], ""))

    if only_due:
        kept = []
        for item in items:
            age = _age_days(item.checked_at, today)
            if age is None or age >= DUE_DAYS:
                kept.append(item)
            else:
                item.status = None
                item.error = f"{age} 天前核过，未到期"
                item.stale = False
                kept.append(item)
        return kept
    return items


def run(items: list[Item], timeout: float, workers: int = 8) -> None:
    targets = [i for i in items if not i.error]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item, (status, error) in zip(targets, pool.map(lambda i: check_url(i.url, timeout), targets)):
            item.status, item.error = status, error


def write_report(report: Report) -> str:
    bad, ok, skipped = report.bad_items, report.ok_items, [i for i in report.skipped if i.error]
    lines = [
        "# 链接抽查报告",
        "",
        f"> 生成时间：{report.checked_on}　·　检查 {len([i for i in report.items if i.status is not None])} 条"
        f"　·　通过 {len(ok)}　·　**失败 {len(bad)}**　·　跳过 {len(skipped)}",
        "> " + ("本次只检查超过 30 天未核对的链接（--only-due）。" if report.due_only else "本次为全量检查。"),
        "",
    ]
    if bad:
        lines += ["## 需要处理（链接失效或异常）", "", "| 归属 | 类型 | 状态 | 链接 |", "| --- | --- | --- | --- |"]
        lines += [f"| {i.owner} | {i.kind} | {i.status or i.error} | {i.url} |" for i in bad]
        lines += ["", "> 处理方式：能换官方新链接就换；换不到就把该条降级为 `unverified`，"
                      "并把该寺庙的 `sources_status` 改回未核实——**不要留着死链冒充可核**。", ""]
    else:
        lines += ["## 结果", "", "全部链接均可访问。", ""]
    if skipped:
        lines += ["<details><summary>跳过（未到期或未检查）</summary>", "", "| 归属 | 类型 | 原因 |", "| --- | --- | --- |"]
        lines += [f"| {i.owner} | {i.kind} | {i.error} |" for i in skipped[:50]]
        lines += ["", "</details>", ""]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(REPORT)


def write_status(items: list[Item], today: date) -> int:
    """把每条 URL 的检查结果写回 temples.json 的 link_status（可选）。"""
    data = json.loads(TEMPLES.read_text(encoding="utf-8"))
    by_url: dict[str, Item] = {}
    for item in items:
        if item.status is not None:
            by_url[item.url] = item
    changed = 0
    for t in data["temples"]:
        for src in t.get("sources", []):
            item = by_url.get(src["url"])
            if item is None:
                continue
            new = {"checked_at": today.isoformat(), "ok": item.ok,
                   "status": item.status, "error": item.error}
            if src.get("link_status") != new:
                src["link_status"] = new
                changed += 1
    TEMPLES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="抽查寺庙资料来源链接")
    ap.add_argument("--only-due", action="store_true", help="只查超过 30 天未核对的")
    ap.add_argument("--write-status", action="store_true", help="把结果写回 temples.json")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    today = date.today()
    items = collect(today, args.only_due)
    run(items, args.timeout, args.workers)
    report = Report(items=items, checked_on=today.isoformat(), due_only=args.only_due)
    path = write_report(report)
    if args.write_status:
        changed = write_status(items, today)
        print(f"已写回 {changed} 条 link_status")
    print(f"{path}\n通过 {len(report.ok_items)} / 失败 {len(report.bad_items)}")
    for item in report.bad_items:
        print(f"  FAIL {item.owner} [{item.kind}] {item.status or item.error} {item.url}")
    return 1 if report.bad_items else 0


if __name__ == "__main__":
    sys.exit(main())
