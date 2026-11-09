#!/usr/bin/env python
"""内测反馈处理台：看待处理、标状态、导出 CSV。

    python scripts/triage_reports.py                  # 看未处理（默认）
    python scripts/triage_reports.py --all            # 看全部
    python scripts/triage_reports.py --stats          # 按寺庙聚合，看哪座被报得最多
    python scripts/triage_reports.py --resolve 3      # 已改数据
    python scripts/triage_reports.py --reject 4 --why "核过官方页面，用户记错"
    python scripts/triage_reports.py --export out.csv # 导出给人工批量核

设计：**只改状态，不改数据**。数据改动仍走 `apply_open_info.py` 或直接改
`temples.json`，这样每一条修正都能追溯到一次命令。
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fmt_time(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def cmd_list(status: str, limit: int) -> int:
    from app.data_access import temple_reports as store

    items = store.list_reports(status, limit)
    counts = store.counts()
    label = {"open": "待处理", "resolved": "已处理", "rejected": "已驳回", "": "全部"}[status]
    print(f"{label}：{len(items)} 条"
          f"（总计 {counts['total']}｜待 {counts['status_open']}｜已处理 {counts['status_resolved']}"
          f"｜已驳回 {counts['status_rejected']}）\n")
    if not items:
        print("没有需要处理的反馈。")
        return 0
    print(f"{'ID':<5}{'时间':<12}{'寺庙':<10}{'字段':<10}描述")
    for item in items:
        print(f"{item['id']:<5}{_fmt_time(item['created_at']):<12}"
              f"{item['temple'][:8]:<10}{item['field'][:8]:<10}{item['note'][:60]}")
    return 0


def cmd_stats() -> int:
    from app.data_access import temple_reports as store

    counts = store.counts()
    print(f"总计 {counts['total']}｜待处理 {counts['status_open']}"
          f"｜已处理 {counts['status_resolved']}｜已驳回 {counts['status_rejected']}\n")
    if not counts["by_temple"]:
        print("没有待处理反馈。")
        return 0
    print("待处理反馈最多的寺庙（先修这些）：")
    for temple, count in counts["by_temple"].items():
        print(f"  {temple:<10} {count} 条")
    return 0


def cmd_set(report_id: int, status: str, why: str) -> int:
    from app.data_access import temple_reports as store

    try:
        row = store.set_status(report_id, status)
    except ValueError as exc:
        print(exc)
        return 2
    if row is None:
        print(f"报告不存在：{report_id}")
        return 2
    note = "已处理" if status == "resolved" else "已驳回"
    print(f"#{row['id']} {row['temple']} · {row['field']} → {note}"
          + (f"（{why}）" if why else ""))
    counts = store.counts()
    print(f"剩余待处理：{counts['status_open']}")
    return 0


def cmd_export(path: Path, status: str) -> int:
    from app.data_access import temple_reports as store

    items = store.list_reports(status, 500)
    if not items:
        print("没有可导出的反馈。")
        return 0
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ID", "时间", "寺庙", "字段", "用户描述", "状态"])
        for item in items:
            writer.writerow([item["id"], _fmt_time(item["created_at"]), item["temple"],
                             item["field"], item["note"], item["status"]])
    print(f"已导出 {len(items)} 条到 {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="内测反馈处理台")
    ap.add_argument("--all", action="store_true", help="列出全部（默认只看待处理）")
    ap.add_argument("--status", choices=["open", "resolved", "rejected"], default="")
    ap.add_argument("--stats", action="store_true", help="按寺庙聚合")
    ap.add_argument("--resolve", type=int, default=0, help="标记为已处理")
    ap.add_argument("--reject", type=int, default=0, help="标记为已驳回")
    ap.add_argument("--why", default="", help="备注原因（会打印，不写库）")
    ap.add_argument("--export", default="", help="导出 CSV 路径")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args(argv)

    if args.resolve:
        return cmd_set(args.resolve, "resolved", args.why)
    if args.reject:
        return cmd_set(args.reject, "rejected", args.why)
    if args.stats:
        return cmd_stats()
    if args.export:
        return cmd_export(Path(args.export), args.status or "open")
    status = args.status or ("" if args.all else "open")
    return cmd_list(status, args.limit)


if __name__ == "__main__":
    sys.exit(main())
