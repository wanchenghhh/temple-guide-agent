#!/usr/bin/env python
"""清理评测/调试残留用户（默认只删「明显是测试」的账号）。

背景：本地跑评测会造大量临时账号（u_eval_*、u_probe* …）。因为每个节点都要把
业务库整库快照一次，库越大每轮越慢——本地 495 个用户时，一次对话从 4 秒涨到 18 秒。
所以开发环境要定期清。

安全规则：
* 只匹配白名单前缀（见 ``TEST_PREFIXES``），不碰真实用户名；
* 默认 ``--dry-run``：先看要删多少，加 ``--yes`` 才真删；
* 只删带 ``user_id`` 的表；删前打印每张表的影响行数。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "profiles.db"

TEST_PREFIXES = (
    "u_eval_", "u_probe", "u_temple", "u_debug", "u_bocha", "u_coord",
    "u_cite", "u_review", "u_x", "u_card", "u_mem", "u_bulk_", "test-", "u-f",
)


def _match_clause() -> tuple[str, list[str]]:
    parts = " OR ".join("user_id LIKE ?" for _ in TEST_PREFIXES)
    return f"({parts})", [f"{p}%" for p in TEST_PREFIXES]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="清理评测残留用户")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--yes", action="store_true", help="真的执行删除（默认只看）")
    ap.add_argument("--keep", default="", help="额外保留的用户 id（逗号分隔）")
    args = ap.parse_args(argv)

    path = Path(args.db)
    if not path.exists():
        print(f"数据库不存在：{path}")
        return 2

    clause, params = _match_clause()
    keep = [k for k in (args.keep or "").split(",") if k.strip()]
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=OFF")
    tables = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'")]
    total = 0
    plan: list[tuple[str, int]] = []
    for name in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
        if "user_id" not in cols:
            continue
        where = clause
        extra = list(params)
        for kept in keep:
            where += " AND user_id != ?"
            extra.append(kept)
        count = conn.execute(f"select count(*) from {name} where {where}", extra).fetchone()[0]
        if count:
            plan.append((name, count))
            total += count

    for name, count in plan:
        print(f"  {name}: {count} 行")
    print(f"合计 {total} 行待删除" + ("" if args.yes else "（预览，加 --yes 执行）"))
    if not args.yes or not total:
        return 0

    with conn:
        for name, _ in plan:
            where = clause
            extra = list(params)
            for kept in keep:
                where += " AND user_id != ?"
                extra.append(kept)
            conn.execute(f"delete from {name} where {where}", extra)
    conn.execute("VACUUM")
    conn.close()
    print(f"已删除 {total} 行并 VACUUM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
