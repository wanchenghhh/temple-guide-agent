#!/usr/bin/env python
"""生成《电话核对单》：照着念就行，打完用 apply_open_info.py 一条命令落地。

    python scripts/render_call_sheet.py        # 写 docs/电话核对单.md
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "agent" / "domain" / "temples.json"
OUT = ROOT / "docs" / "电话核对单.md"

PRIORITY = {
    "法源寺": "P0", "灵光寺": "P0",
    "通教寺": "P1", "天宁寺": "P1", "广济寺": "P1", "广化寺": "P1",
    "白云观": "P1", "火德真君庙": "P1",
    "卧佛寺": "P2",
}
QUESTIONS = [
    "平时对普通游客开放吗？",
    "需要提前预约吗？",
    "周几闭馆 / 有没有不开放的日子？",
    "门票多少钱？开放到几点？",
]


def _pending_claims(payload: dict) -> list[dict]:
    rows = []
    for temple in payload["temples"]:
        for wish in temple.get("wish_themes", []):
            if wish.get("claim_evidence") == "folk" and not wish.get("basis"):
                rows.append({"temple": temple["name"], "theme": wish["theme"],
                             "claim": wish.get("claim", "")})
    return rows


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    rows = [t for t in payload["temples"] if t.get("open_status") == "unverified"]
    rows.sort(key=lambda t: (PRIORITY.get(t["name"], "P9"), t["name"]))

    lines = ["# 电话核对单（寺庙开放信息）", "",
             f"> 生成：{date.today().isoformat()}　·　待核 {len(rows)} 座　·　每座 4 个问题，5 分钟打完一座",
             "> 打完用一条命令落地：",
             "",
             "```bash",
             "python scripts/apply_open_info.py --temple 法源寺 \\",
             "    --open yes --reservation no --closure none --ticket 免费 --hours 8:30-15:30 \\",
             '    --source <官网或公告链接> --note "电话确认"',
             "```",
             "",
             "> `--open` 可选：`yes`（正常开放）/ `no`（不对外）/ `limited`（如仅初一十五）/ `reservation`（必须预约）",
             "> `--closure` 可选：`none` / `mon`（周一）/ `mon-tue`（周一+周二）/ `first-lunar`（仅初一十五）",
             "> **没给 `--source` 就不会升级成「已核实」**，只会更新开放信息。",
             ""]

    for index, temple in enumerate(rows, 1):
        priority = PRIORITY.get(temple["name"], "P9")
        lines += [
            f"## {index}. {temple['name']}（{priority}）",
            "",
            f"- 区县：{temple['district']}　类型：{temple['status_label']}",
            f"- 现有记录：{temple.get('open_note') or '—'}",
            f"- 现有来源：{('、'.join(s['publisher'] for s in temple.get('sources', [])) or '**未核实**')}",
            "",
            "要问的 4 句：",
            "",
        ]
        lines += [f"{i}. {q}" for i, q in enumerate(QUESTIONS, 1)]
        lines += [
            "",
            "答案（现场填）：",
            "",
            "```",
            "平时开放：是 / 否 / 仅初一十五 / 需预约",
            "预约：需要 / 不需要",
            "闭馆日：",
            "门票与时段：",
            "官方链接（能问到就给）：",
            "```",
            "",
        ]

    claims = _pending_claims(payload)
    lines += ["---", "", "## 附：还没定论的心愿说法", "",
              "> 这些只有民间口碑、指不出具体殿宇。找懂行的人问一句就能补上。", ""]
    if claims:
        lines += ["| 寺庙 | 心愿 | 现在的说法 | 需要确认 |", "| --- | --- | --- | --- |"]
        for item in claims:
            lines.append(f"| {item['temple']} | {item['theme']} | {item['claim'][:36]} | 是哪座殿、供哪尊？ |")
    else:
        lines.append("无。")
    lines += ["", "> 确认后同样用 `apply_open_info.py` 的思路补 `basis`（殿宇）即可；"
                  "在那之前，回答里一律说成「民间说法」。", ""]

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {OUT}（待核 {len(rows)} 座，说法待定 {len(claims)} 条）")


if __name__ == "__main__":
    main()
