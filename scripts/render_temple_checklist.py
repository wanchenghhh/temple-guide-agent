"""Render docs/temple-review-checklist.md from temples.json (schema v2).

The checklist is the human-review surface: it must show everything a reviewer
needs to judge a row without opening the JSON (现状 / 开放约束 / 依据 / 来源),
and it must never hide an unverified source.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

DATA = Path("app/agent/domain/temples.json")
OUT = Path("docs/temple-review-checklist.md")

EVID = {"official": "官方", "reference": "文献", "folk": "口碑"}


def main() -> None:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    rows, meta = d["temples"], d["meta"]
    L: list[str] = []
    L.append("# 北京试点寺庙名单 · 人工复核清单（30 座）\n")
    L.append("> 复核口径：不凭记忆判断「对不对」，只问 **能不能给出一个公开出处（链接）**。")
    L.append("> 判定标准：**可用** = 现状、心愿依据、来源三者都对得上；**需改** = 有一处与来源不符；")
    L.append("> **删/降级** = 不可寻访、已非寺院，或找不到任何公开出处。\n")
    L.append(f"资料版本：{meta['schema_version']}　·　整理/核对日期：{meta['checked_at']}　·　"
             f"条目：{len(rows)}　·　可许愿：{meta['recommendable_count']}"
             f"　·　可参观：{meta['visitable_count']}\n")
    L.append(f"> {meta['note']}\n")
    L.append(f"> 心愿口径：{meta['wish_policy']}\n")

    L.append("## 统计\n")
    L.append("| 现状 | 数量 |\n| --- | --- |")
    status = Counter(r["status_label"] for r in rows)
    for k, v in status.most_common():
        L.append(f"| {k} | {v} |")
    L.append(f"| **合计** | **{sum(status.values())}** |")
    L.append("\n| 心愿 | 覆盖（仅有依据的） | 其中官方/文献 | 其中民间口碑 |\n| --- | --- | --- | --- |")
    for theme in ("姻缘", "求子", "学业", "事业", "财运", "健康"):
        hits = [r for r in rows for w in r["wish_themes"] if w["theme"] == theme]
        solid = [r for r in hits if any(w["theme"] == theme and w["claim_evidence"] != "folk"
                                        for w in r["wish_themes"])]
        L.append(f"| {theme} | {len(hits)} | {len(solid)} | {len(hits) - len(solid)} |")
    L.append("\n> 「平安」不作为标签，走默认项：用户只说平安时按「能上香 + 近 + 氛围」给候选，不排序、不比较灵验。\n")

    L.append("## 逐条复核表\n")
    L.append("| # | 寺庙 | 区县 | 场所类型 | 宗派 | 登记宗教场所 | 可参观 | 可许愿 | 开放约束 | 心愿（说法／殿宇） | 来源 | 结论 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(rows, 1):
        def _cell(w):
            claim = EVID.get(w.get("claim_evidence"), "说法")
            return f"{w['theme']}（{claim}／{w['basis']}）" if w.get("basis") else f"{w['theme']}（{claim}，殿宇未核）"

        wishes = "、".join(_cell(w) for w in r["wish_themes"]) or "—（无具体心愿说法）"
        closure = "、".join(r.get("closure_rule") or []) or ("需预约" if r.get("open_status") == "reservation" else "—")
        if r["open_status"] == "closed":
            closure = "不开放"
        elif r["open_status"] == "unverified" and r["status"] == "active_temple":
            closure = (closure + "；开放待核").strip("；")
        if not r["wish_recommendable"] and r.get("recommend_note"):
            closure = f"{closure}｜{r['recommend_note']}"
        src = f"已核（{len(r['sources'])} 条）" if r["sources_status"] == "verified" else "**未核实**"
        rec = "可" if r["wish_recommendable"] else "**否**"
        look = "可" if r.get("visitable") else "**否**"
        reg = {True: "是", False: "否", None: "待核"}[r.get("religious_registered")]
        L.append(f"| {i} | {r['name']} | {r['district']} | {r['status_label']} | {r.get('sect','')} | {reg} | {look} | {rec} | {closure} | {wishes} | {src} |  |")

    L.append("\n## 复核时只看四件事\n")
    L.append("1. **现状**：这座现在还能上香许愿吗？还是只算博物馆/遗址？（错了就整条作废）")
    L.append("2. **心愿依据**：标「口碑」的说法你认不认？标「文献」的殿名对不对？")
    L.append("3. **开放约束**：周一闭馆 / 要预约 / 正在修缮，有没有漏？")
    L.append("4. **来源**：标「未核实」的条目，你手上有官方链接的请补上；公众号只能当渠道，不能当引用。")

    L.append("\n## 去哪问（渠道名，不是来源）\n")
    L.append("| 寺庙 | 渠道 |\n| --- | --- |")
    for r in rows:
        if r.get("finder_hint"):
            L.append(f"| {r['name']} | {'、'.join(r['finder_hint'])} |")

    L.append("\n## 附录：全部来源链接（可点开审计）\n")
    L.append("| 寺庙 | 来源 | 类型 | 链接 | 核对日期 |\n| --- | --- | --- | --- | --- |")
    KIND = {"official": "官方", "reference": "百科/文献", "media": "媒体"}
    for r in rows:
        if not r["sources"]:
            L.append(f"| {r['name']} | — | **未核实** | — | — |")
        for src in r["sources"]:
            L.append(f"| {r['name']} | {src['publisher']} | {KIND.get(src['kind'], src['kind'])} | {src['url']} | {src['checked_at']} |")

    L.append("\n## 附录：坐标（就近推荐的依据）\n")
    L.append("| 寺庙 | 纬度 | 经度 | 备注 | 来源 |\n| --- | --- | --- | --- | --- |")
    for r in rows:
        if r.get("lat") is None:
            L.append(f"| {r['name']} | — | — | {r.get('coord_note','未取到坐标')} | — |")
        else:
            L.append(f"| {r['name']} | {r['lat']} | {r['lng']} | {r.get('coord_note','') or '—'} | {r['coord_source']} |")
    L.append("\n> 坐标只取自维基百科坐标接口或维基数据；取不到就留空，距离退回区县并告知用户。\n")

    missing = [r["name"] for r in rows if r["sources_status"] != "verified"]
    L.append("\n## 未核实的条目（需要补链接）\n")
    L.append(("、".join(missing) if missing else "无——30 条都能点开。") + f"　（未核实：{len(missing)}）\n")
    L.append("\n> 已核实的来源均为公开网页（佛协 / 文博机构 / 政府 / 协会官网 / 百科），每条带核对日期；"
             "链接会失效，需按月抽查。\n")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", OUT, "| verified:", sum(1 for r in rows if r['sources_status'] == 'verified'),
          "| unverified:", len(missing))


if __name__ == "__main__":
    main()
