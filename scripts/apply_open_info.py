#!/usr/bin/env python
"""把「电话核对到的开放信息」写回数据（唯一入口，避免手改 JSON 出错）。

    # 打听到的结果，一条命令落地
    python scripts/apply_open_info.py --temple 法源寺 \
        --open yes --reservation no --closure none --ticket 免费 \
        --source https://zgfxy.cn/fys --note "电话确认：工作日 8:30-15:30 对游客开放"

    # 只确认了一部分也可以
    python scripts/apply_open_info.py --temple 通教寺 --open limited --closure 初一十五

    # 先看会改什么，不落盘
    python scripts/apply_open_info.py --temple 白云观 --ticket 10 --dry-run

规则：
* ``--source`` 给了 URL 就用它当来源并**当场 HTTP 校验**（200 才升级为 verified）；
* 没给来源就只更新开放信息，``sources_status`` 保持未核实（不假装有出处）；
* 改完自动重生成复核清单，并跑一遍垂直领域测试。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "agent" / "domain" / "temples.json"

SOURCE_KINDS = {
    "official": ("official", True),    # 政府/场所官网/官方公告 → 可升级
    "media": ("media", False),         # 旅游平台/媒体 → 只记录，不升级
    "folk": ("folk", False),           # 攻略/百科/UGC → 只记录，不升级
}
METHODS = {
    "phone": "电话核对",
    "official_web": "官方页面核查",
    "official_channel": "官方公众号核对",   # 官方渠道转述、无链接
    "media": "联网资料核查",
}
# 证据等级：官方三种口径都算 A；二手资料只能算 C
METHOD_GRADE = {
    "phone": "A",
    "official_web": "A",
    "official_channel": "A",
    "media": "C",
}

OPEN_CHOICES = {
    "yes": ("normal", "可正常参观/上香"),
    "no": ("closed", "不对外开放"),
    "limited": ("unverified", "有限开放（如仅初一十五、仅法会）"),
    "reservation": ("reservation", "可去但必须提前预约"),
    "unknown": ("unverified", "仍待核实"),
}
CLOSURE_MAP = {
    "none": [],
    "mon": ["周一闭馆"],
    "mon-tue": ["周一闭馆", "周二闭馆"],
    "first-lunar": ["仅农历初一、十五开放"],
    "winter": ["冬季闭馆（以公告为准）"],
}


def _check_url(url: str, timeout: float = 15.0) -> bool:
    for method in ("HEAD", "GET"):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "TempleGuide/link-check"}, method=method)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if 200 <= response.status < 400:
                    return True
        except Exception:
            continue
    return False


def _open_note(args: argparse.Namespace, status_label: str) -> str:
    method = METHODS.get(args.method, METHODS["media"])
    bits = [f"{method}（{date.today().isoformat()}）：{status_label}"]
    if args.reservation == "yes":
        bits.append("需提前预约")
    elif args.reservation == "no":
        bits.append("无需预约")
    if args.ticket:
        bits.append(f"门票：{args.ticket}")
    if args.hours:
        bits.append(f"开放时段：{args.hours}")
    if args.note:
        bits.append(args.note)
    return "；".join(bits)


def apply(args: argparse.Namespace) -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    rows = payload["temples"]
    temple = next((r for r in rows if r["name"] == args.temple or r["id"] == args.temple), None)
    if temple is None:
        print(f"找不到寺庙：{args.temple}")
        return 2

    if args.open == "reservation" and args.reservation == "no":
        print("自相矛盾：--open reservation 表示必须预约，不能再 --reservation no")
        return 2
    if args.source and args.source_kind == "official" and not args.method == "phone" and args.no_verify:
        print("提示：--source-kind official 建议保留 HTTP 校验（去掉 --no-verify）")

    changes: list[str] = []
    if args.open:
        key, label = OPEN_CHOICES[args.open]
        if temple.get("open_status") != key:
            changes.append(f"open_status: {temple.get('open_status')} → {key}")
            temple["open_status"] = key
        note = _open_note(args, label)
        if temple.get("open_note") != note:
            changes.append(f"open_note 更新为：{note[:48]}…")
            temple["open_note"] = note
    if args.closure:
        closure = CLOSURE_MAP[args.closure]
        existing = list(temple.get("closure_rule") or [])
        merged = list(dict.fromkeys(existing + closure)) if args.merge_closure else closure
        if merged != existing:
            changes.append(f"closure_rule: {existing} → {merged}")
            temple["closure_rule"] = merged
        elif existing:
            changes.append("closure_rule 未变（已包含这些规则）")

    if args.source:
        ok = _check_url(args.source) if not args.no_verify else True
        if not ok:
            print(f"来源链接打不开，未采纳：{args.source}")
            return 1
        publisher = args.publisher or "核对来源"
        kind, upgrades = SOURCE_KINDS[args.source_kind]
        sources = temple.setdefault("sources", [])
        if all(s["url"] != args.source for s in sources):
            sources.append({"url": args.source, "publisher": publisher,
                            "kind": kind, "checked_at": date.today().isoformat()})
            changes.append(f"新增来源（{kind}）：{publisher}")
        # 只有官方来源或电话确认，才允许把「来源」升级为已核实
        if upgrades or args.method == "phone":
            temple["sources_status"] = "verified"
        else:
            changes.append(f"来源等级 {kind}：不改动 sources_status（避免把攻略当官方）")

    # 4) 开放信息单独记录证据等级，不与 sources_status / checked_at 混用
    if args.open or args.closure or args.ticket or args.hours:
        temple["open_verified_at"] = date.today().isoformat()
        temple["open_evidence"] = {
            "method": args.method,
            "grade": METHOD_GRADE.get(args.method, "C"),
            "source": args.source or "",
            "note": (args.note or "")[:160],
        }

    if not changes:
        print("没有需要修改的内容（参数没变）")
        return 0

    temple["checked_at"] = date.today().isoformat()
    print("将修改：")
    for line in changes:
        print(f"  - {line}")
    if args.dry_run:
        print("\n--dry-run：未写入")
        return 0

    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        shown = DATA.relative_to(ROOT)
    except ValueError:
        shown = DATA
    print(f"\n已写入 {shown}")

    if args.render:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "render_temple_checklist.py")],
                       cwd=ROOT, check=False)
    if args.test:
        subprocess.run([sys.executable, "-m", "pytest", "tests/test_temple_domain.py", "-q"],
                       cwd=ROOT, check=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把电话核对到的开放信息写回数据")
    ap.add_argument("--temple", required=True, help="寺庙名或 id")
    ap.add_argument("--open", choices=list(OPEN_CHOICES), help="是否对外开放")
    ap.add_argument("--reservation", choices=["yes", "no"], help="是否必须预约")
    ap.add_argument("--closure", choices=list(CLOSURE_MAP), help="闭馆规则")
    ap.add_argument("--ticket", default="", help="门票（如 免费 / 20 元）")
    ap.add_argument("--hours", default="", help="开放时段（如 8:30-16:30）")
    ap.add_argument("--source", default="", help="来源 URL（会当场校验）")
    ap.add_argument("--source-kind", choices=list(SOURCE_KINDS), default="media",
                    help="来源等级：official 才升级为已核实（默认 media，避免把攻略当官方）")
    ap.add_argument("--method", choices=list(METHODS), default="media",
                    help="核实方式：phone 电话 / official_web 官方页面 / media 联网资料（默认）")
    ap.add_argument("--publisher", default="", help="来源名称（如 寺院官网）")
    ap.add_argument("--merge-closure", action="store_true",
                    help="把新规则并入已有闭馆规则（默认替换）")
    ap.add_argument("--note", default="", help="备注（会写进 open_note）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="跳过来源 HTTP 校验（不推荐）")
    ap.add_argument("--no-render", dest="render", action="store_false", default=True)
    ap.add_argument("--no-test", dest="test", action="store_false", default=True)
    args = ap.parse_args(argv)
    return apply(args)


if __name__ == "__main__":
    sys.exit(main())
