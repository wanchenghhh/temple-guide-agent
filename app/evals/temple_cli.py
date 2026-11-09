"""评测 CLI。

    python -m app.evals.temple_cli --mode pipeline          # 流水线自检（不需 key）
    python -m app.evals.temple_cli --mode live              # 真实模型（需要 key）
    python -m app.evals.temple_cli --mode live --category 红线
    python -m app.evals.temple_cli --mode pipeline --out docs/eval-baseline.md

退出码：有失败用例 → 1（CI 可当门禁用）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="寺庙寻访向导评测")
    ap.add_argument("--mode", choices=("pipeline", "live"), default="pipeline")
    ap.add_argument("--category", default="", help="只跑某一类：就近/专程/指定寺庙/行前/红线")
    ap.add_argument("--out", default="docs/eval-baseline.md")
    ap.add_argument("--json", default="", help="另外输出一份 JSON 结果")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="每个用例之间暂停（真实模型模式建议 0.5，避免被限流）")
    ap.add_argument("--sample", type=int, default=10,
                    help="报告里附多少条人工抽查（默认 10）")
    ap.add_argument("--include-red-lines", action="store_true",
                    help="pipeline 模式下也跑红线（默认跳过：拒绝话术属模型能力）")
    args = ap.parse_args(argv)

    import app.main  # noqa: F401  串起提示词注册与 .env（与线上一致）
    from app.evals.temple_cases import CASES
    from app.evals.temple_runner import (
        default_cases, live_responder_factory, pipeline_responder, render_report, run_all, summarize,
    )

    cases = default_cases(args.mode, args.category, args.limit, args.include_red_lines)
    if not cases:
        print("没有匹配的用例")
        return 2

    if args.mode == "live":
        from app.gateway.llm_gateway import has_llm, route

        if not has_llm(route("chat")):
            print("live 模式需要模型 key：请先配置 KIMI_API_KEY 或 LLM_FAST_API_KEY")
            return 2
        responder = live_responder_factory()
    else:
        responder = pipeline_responder

    def _progress(index: int, total: int, result) -> None:
        mark = "ok  " if result.ok else "FAIL"
        print(f"  [{index}/{total}] {mark} {result.case_id}", flush=True)

    results = run_all(responder, cases, sleep_s=args.sleep, progress=_progress)
    summary = summarize(results, args.mode)
    out = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    step = max(1, len(results) // max(1, args.sample))
    sample = results[::step][: args.sample]
    render_report(summary, out, sample=sample)
    if args.json:
        target = Path(args.json) if Path(args.json).is_absolute() else ROOT / args.json
        target.write_text(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    print(f"{args.mode}: {summary.passed}/{summary.total} 通过　"
          f"来源可追溯率 {summary.traceable_rate:.0%}　"
          f"p50 {summary.latency_p50:.0f}ms p95 {summary.latency_p95:.0f}ms")
    for failure in summary.failures:
        reasons = "；".join(f"{c.name}: {c.detail}" for c in failure.checks if not c.ok) or failure.error
        print(f"  FAIL {failure.case_id} [{failure.category}] {reasons}")
    print(f"报告：{out}")
    return 1 if summary.failures else 0


if __name__ == "__main__":
    sys.exit(main())
