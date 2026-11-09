"""寺庙向导的领域指标：把「能不能上线」变成几个能天天看的数。

只记聚合所需的最小信息，不记内容、不记原文：

* ``turns``：一轮对话的总数（分母）；
* ``traceable_ok``：引用校验通过（没有编造链接/数字）的轮数；
* ``degraded``：降级次数（资料缺失、来源未核实、搜索不可用、额度用完）；
* ``refused``：明确拒绝的请求（订票、代发、代打电话…）；
* ``candidate_short``：候选不足（少于 3 座）的推荐轮数；
* ``review_turns``：带公开分享的轮数；
* ``latency_ms`` / ``cost_units``：时延与花销。

存储与查询在 ``app.data_access.temple_metrics``（独立审计库）；
这里只做聚合，不碰连接，也绝不返回用户内容。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


def record(*, kind: str = "", wish: str = "", candidates: int = 0, citation_ok: bool = True,
           degraded: bool = False, refused: bool = False, review_items: int = 0,
           latency_ms: int = 0, cost_units: float = 0.0) -> None:
    """记一轮；任何异常都不能影响用户回答。"""
    try:
        from app.data_access import temple_metrics as store

        store.add_turn(
            day=time.strftime("%Y-%m-%d"), kind=kind, wish=wish, candidates=candidates,
            citation_ok=citation_ok, degraded=degraded, refused=refused,
            review_items=review_items, latency_ms=latency_ms, cost_units=cost_units,
        )
    except Exception:
        return


def _pct(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


@dataclass
class Summary:
    days: int
    turns: int = 0
    traceable: int = 0
    degraded: int = 0
    refused: int = 0
    candidate_short: int = 0
    review_turns: int = 0
    latency_p50: int = 0
    latency_p95: int = 0
    cost_total: float = 0.0
    by_kind: dict[str, int] = field(default_factory=dict)
    by_wish: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "turns": self.turns,
            "traceable_rate": _pct(self.traceable, self.turns),
            "degraded_rate": _pct(self.degraded, self.turns),
            "refusal_rate": _pct(self.refused, self.turns),
            "candidate_short_rate": _pct(self.candidate_short, self.turns),
            "review_turns": self.review_turns,
            "latency_p50_ms": self.latency_p50,
            "latency_p95_ms": self.latency_p95,
            "cost_total": round(self.cost_total, 4),
            "cost_per_turn": round(self.cost_total / self.turns, 4) if self.turns else 0.0,
            "by_kind": self.by_kind,
            "by_wish": self.by_wish,
        }


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return int(ordered[index])


def _rows(days: int) -> list[dict[str, Any]]:
    try:
        from app.data_access import temple_metrics as store

        day_from = time.strftime("%Y-%m-%d", time.localtime(time.time() - max(1, int(days)) * 86400))
        return store.turns_since(day_from)
    except Exception:
        return []


def summary(days: int = 7) -> Summary:
    rows = _rows(days)
    out = Summary(days=days, turns=len(rows))
    latencies: list[int] = []
    for row in rows:
        out.traceable += int(row["citation_ok"] or 0)
        out.degraded += int(row["degraded"] or 0)
        out.refused += int(row["refused"] or 0)
        out.review_turns += 1 if int(row["review_items"] or 0) else 0
        if int(row["candidates"] or 0) < 3:
            out.candidate_short += 1
        latencies.append(int(row["latency_ms"] or 0))
        out.cost_total += float(row["cost_units"] or 0.0)
        kind = row["kind"] or "unknown"
        out.by_kind[kind] = out.by_kind.get(kind, 0) + 1
        wish = row["wish"] or "-"
        out.by_wish[wish] = out.by_wish.get(wish, 0) + 1
    out.latency_p50 = _percentile(latencies, 50)
    out.latency_p95 = _percentile(latencies, 95)
    return out


def render(summary_obj: Summary) -> str:
    data = summary_obj.as_dict()
    lines = [
        f"# 寺庙向导指标（最近 {data['days']} 天）",
        "",
        f"- 轮次：{data['turns']}",
        f"- **来源可追溯率：{data['traceable_rate']:.0%}**（上线门槛：编造一条即不算过关）",
        f"- 降级率：{data['degraded_rate']:.0%}　·　候选不足率：{data['candidate_short_rate']:.0%}",
        f"- 带公开分享的轮次：{data['review_turns']}",
        f"- 时延：p50 {data['latency_p50_ms']} ms　p95 {data['latency_p95_ms']} ms",
        f"- 成本：合计 {data['cost_total']}　单轮 {data['cost_per_turn']}",
        "",
    ]
    if data["by_kind"]:
        lines += ["| 类型 | 轮次 |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(data["by_kind"].items(), key=lambda x: -x[1])]
        lines.append("")
    if data["by_wish"]:
        lines += ["| 心愿 | 轮次 |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(data["by_wish"].items(), key=lambda x: -x[1])]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="打印寺庙向导指标")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="", help="写进文件（默认打印到终端）")
    args = ap.parse_args()
    text_out = render(summary(args.days))
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(text_out + chr(10), encoding="utf-8")
        print(f"已写入 {args.out}")
    else:
        print(text_out)
    sys.exit(0)
