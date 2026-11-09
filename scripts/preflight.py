#!/usr/bin/env python
"""上线前自检：一条命令看清「能不能给人用」。

    python scripts/preflight.py                 # 本地配置 + 远程冒烟
    python scripts/preflight.py --offline       # 只查本地配置与数据
    python scripts/preflight.py --base https://your.app --admin-token <token>

检查项分四组：

1. **配置**：AUTH_SECRET、LLM key、DATA_DIR 可写、加密 key、管理员令牌、
   外部服务开关与 key 是否配对（开关开了却没 key = 上线必炸）。
2. **数据**：寺庙条目数、来源是否都可核、坐标覆盖、复核清单与报告是否新鲜。
3. **运行**（需网络）：/health、一次真实对话（寺庙问题）、卡片是否返回、时延、错误码。
4. **外部依赖**（--online）：高德 / 和风 / 博查 各打一次，确认额度与 key 有效。

只输出 PASS/FAIL 与建议，**任何密钥都不打印**。
退出码：有 FAIL → 1。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "TempleGuide/preflight"}

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, group: str, status: str, message: str) -> None:
        self.rows.append((group, status, message))

    @property
    def failures(self) -> int:
        return sum(1 for _, status, _ in self.rows if status == FAIL)

    def render(self) -> str:
        lines = ["", "上线前自检", "=" * 60]
        group = None
        for name, status, message in self.rows:
            if name != group:
                group = name
                lines.append(f"\n[{group}]")
            icon = {PASS: "✓", FAIL: "✗", WARN: "!"}[status]
            lines.append(f"  {icon} {status:4} {message}")
        lines.append("")
        lines.append(f"结果：{len(self.rows) - self.failures} 项通过，{self.failures} 项失败")
        if self.failures:
            lines.append("→ 失败项必须处理完再上线。")
        return "\n".join(lines)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _truthy(name: str, default: str = "0") -> bool:
    return _env(name, default).lower() in ("1", "true", "yes", "on")


def check_config(report: Report) -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    secret = _env("AUTH_SECRET")
    if len(secret) >= 32:
        report.add("配置", PASS, f"AUTH_SECRET 已配置（{len(secret)} 位）")
    else:
        report.add("配置", FAIL, "AUTH_SECRET 缺失或过短（至少 32 位）；否则所有 /api 返回 503")

    from app.gateway.llm_gateway import has_llm, route

    if has_llm(route("chat")):
        report.add("配置", PASS, "模型 Key 可用（聊天走真实模型）")
    else:
        report.add("配置", WARN, "没有模型 Key：聊天会走离线占位，只能演示")

    data_dir = Path(_env("DATA_DIR", str(ROOT / "data")))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".preflight"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        size_mb = sum(p.stat().st_size for p in data_dir.glob("*") if p.is_file()) / 1e6
        report.add("配置", PASS, f"DATA_DIR 可写：{data_dir}（约 {size_mb:.1f} MB）")
        if size_mb > 500:
            report.add("配置", WARN, "数据目录超过 500 MB：检查是否需要归档/清理")
    except Exception as exc:  # noqa: BLE001
        report.add("配置", FAIL, f"DATA_DIR 不可写：{type(exc).__name__}")

    if _env("SECRETS_FERNET_KEY"):
        report.add("配置", PASS, "SECRETS_FERNET_KEY 已配置（安全输入区可用）")
    else:
        report.add("配置", WARN, "SECRETS_FERNET_KEY 未配置：密码类安全输入区不可用")

    if _env("HARNESS_ADMIN_TOKENS"):
        report.add("配置", PASS, "管理员令牌已配置（指标/轨迹可查）")
    else:
        report.add("配置", WARN, "HARNESS_ADMIN_TOKENS 未配置：管理接口返回 503，看不到指标")

    pairs = (
        ("TRAVEL_ENABLED", "AMAP_KEY", "地图路线"),
        ("TRAVEL_ENABLED", "QWEATHER_KEY", "天气"),
        ("BOCHA_ENABLED", "BOCHA_API_KEY", "公开分享搜索"),
    )
    for flag, key, label in pairs:
        on = _truthy(flag, "1" if flag == "TRAVEL_ENABLED" else "0")
        has = bool(_env(key))
        if on and has:
            report.add("配置", PASS, f"{label}已启用且已配 key")
        elif on and not has:
            report.add("配置", FAIL, f"{label}开关开着但缺少 {key}：会一直降级")
        elif not on and has:
            report.add("配置", WARN, f"{label}有 key 但开关关着（{flag}=0）")

    if _truthy("PROACTIVE_ENABLED"):
        report.add("配置", PASS, "定时任务调度已开启")
    else:
        report.add("配置", WARN, "PROACTIVE_ENABLED=0：提醒/定时任务不会触发")

    cap = _env("AGENT_COST_CAP_FREE_DAILY")
    report.add("配置", PASS if cap else WARN,
               f"单用户日成本上限：{cap or '未设置（建议设 1–2 元）'}")


def check_data(report: Report) -> None:
    from app.agent.domain import origins, temples

    rows = temples.all_temples()
    report.add("数据", PASS, f"寺庙条目：{len(rows)}")
    verified = sum(1 for r in rows if r.get("sources_status") == "verified")
    if verified == len(rows):
        report.add("数据", PASS, f"来源可核：{verified}/{len(rows)}")
    else:
        report.add("数据", FAIL, f"还有 {len(rows) - verified} 座来源未核实")

    with_coord = sum(1 for r in rows if r.get("lat") is not None)
    report.add("数据", PASS if with_coord >= len(rows) - 2 else WARN,
               f"坐标覆盖：{with_coord}/{len(rows)}（其余按区县估算）")

    recommendable = sum(1 for r in rows if r.get("wish_recommendable"))
    report.add("数据", PASS, f"可作为许愿推荐：{recommendable} 座")

    report.add("数据", PASS, f"常见出发地：{len(origins.all_origins())} 个")

    checklist = ROOT / "docs" / "temple-review-checklist.md"
    if checklist.exists():
        age_days = (time.time() - checklist.stat().st_mtime) / 86400
        report.add("数据", PASS if age_days < 60 else WARN,
                   f"复核清单 {age_days:.0f} 天前生成")
    else:
        report.add("数据", WARN, "缺少 docs/temple-review-checklist.md")
        return

    link_report = ROOT / "docs" / "link-check-report.md"
    if link_report.exists():
        text = link_report.read_text(encoding="utf-8")
        age_days = (time.time() - link_report.stat().st_mtime) / 86400
        if "失败 0" in text:
            report.add("数据", PASS, f"链接抽查最近一次全通过（{age_days:.0f} 天前）")
        else:
            report.add("数据", FAIL, "链接抽查存在失效链接：先跑 scripts/check_links.py 处理")
        if age_days > 35:
            report.add("数据", WARN, f"链接抽查已 {age_days:.0f} 天未跑（建议每月一次）")
    else:
        report.add("数据", WARN, "还没有链接抽查报告：跑 scripts/check_links.py")


def _http(url: str, *, data: dict | None = None, timeout: float = 30.0,
          headers: dict | None = None) -> tuple[int, Any]:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={**UA, **(headers or {})},
                                     method="POST" if body else "GET")
    if body:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                return response.status, json.loads(raw)
            except Exception:
                return response.status, raw[:200]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:200]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


def check_runtime(report: Report, base: str, admin_token: str) -> None:
    status, body = _http(f"{base}/health")
    if status == 200 and isinstance(body, dict) and body.get("ok"):
        mode = body.get("llm")
        report.add("运行", PASS if mode == "live" else WARN,
                   f"/health 正常（llm={mode}，版本 {body.get('version')}）")
        if mode != "live":
            report.add("运行", WARN, "模型处于 mock 模式：真实用户会看到占位回复")
    else:
        report.add("运行", FAIL, f"/health 异常：HTTP {status}")
        return

    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(f"{base}/api/session", data=b"", headers=UA, method="POST")
    try:
        with opener.open(request, timeout=30) as response:
            session = json.loads(response.read())
        report.add("运行", PASS, "会话签发正常（AUTH_SECRET 生效）")
    except Exception as exc:  # noqa: BLE001
        report.add("运行", FAIL, f"会话签发失败：{type(exc).__name__}")
        return

    payload = json.dumps({"message": "我想求姻缘，从国贸出发"}).encode()
    started = time.time()
    try:
        with opener.open(urllib.request.Request(
                f"{base}/api/chat", data=payload,
                headers={**UA, "Content-Type": "application/json"}, method="POST"),
                timeout=120) as response:
            chat = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001
        report.add("运行", FAIL, f"真实对话失败：{type(exc).__name__}")
        return
    elapsed = time.time() - started

    data = (chat.get("data") or {})
    reply = ""
    for message in reversed(data.get("messages") or []):
        if message.get("role") == "assistant":
            reply = message.get("content") or ""
            break
    if data.get("error"):
        report.add("运行", FAIL, f"对话返回错误码：{data['error']}")
    elif not reply:
        report.add("运行", FAIL, "对话没有返回内容")
    else:
        report.add("运行", PASS, f"对话正常（{elapsed:.1f}s，{len(reply)} 字）")
    if elapsed > 12:
        report.add("运行", WARN, f"首轮响应 {elapsed:.1f}s，超过 10 秒目标（冷启动可忽略）")

    card = data.get("temple_card") or {}
    items = card.get("items") or []
    if items and 1 <= len(items) <= 3:
        report.add("运行", PASS, f"推荐卡片正常（{len(items)} 座）")
        if any(not (i.get("sources") or []) for i in items):
            report.add("运行", WARN, "有卡片条目没有来源链接")
    else:
        report.add("运行", FAIL, "没有返回推荐卡片或候选数超限")

    if "灵验分" in reply or "排行榜" in reply:
        report.add("运行", FAIL, "回答里出现了灵验分/排行榜")

    if admin_token:
        status, metrics = _http(f"{base}/api/admin/temple/metrics?days=7", headers={
            "Authorization": f"Bearer {admin_token}", "X-Admin-Token": admin_token})
        if status == 200 and isinstance(metrics, dict):
            report.add("运行", PASS,
                       f"指标接口正常（{metrics.get('turns')} 轮，"
                       f"可追溯率 {metrics.get('traceable_rate', 0):.0%}）")
        else:
            report.add("运行", WARN, f"指标接口返回 HTTP {status}（检查管理员令牌 scope）")


def check_external(report: Report) -> None:
    from app.tools import bocha, travel

    if _env("AMAP_KEY"):
        geo = travel.geocode("雍和宫")
        report.add("外部", PASS if geo.get("status") == "ok" else FAIL,
                   f"高德地理编码：{geo.get('status')}")
    if _env("QWEATHER_KEY"):
        weather = travel.weather(116.4173, 39.9472)
        report.add("外部", PASS if weather.get("status") == "ok" else FAIL,
                   f"和风天气：{weather.get('status')}")
    if _truthy("BOCHA_ENABLED"):
        result = bocha.search("雍和宫 开放时间", 1)
        report.add("外部", PASS if result.get("status") == "ok" else FAIL,
                   f"博查搜索：{result.get('status')}")
    usage_travel = travel._usage()
    report.add("外部", WARN if usage_travel.get("remaining", 1) == 0 else PASS,
               f"地图/天气今日剩余额度：{usage_travel.get('remaining')}/{usage_travel.get('cap')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="上线前自检")
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--admin-token", default=os.getenv("HARNESS_ADMIN_TOKEN_PROBE", ""))
    ap.add_argument("--offline", action="store_true", help="只查配置与数据")
    ap.add_argument("--online", action="store_true", help="额外打外部接口（消耗额度）")
    ap.add_argument("--json", default="", help="把结果写成 JSON")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    report = Report()
    check_config(report)
    check_data(report)
    if not args.offline:
        check_runtime(report, args.base.rstrip("/"), args.admin_token)
    if args.online:
        check_external(report)

    print(report.render())
    if args.json:
        Path(args.json).write_text(json.dumps(
            [{"group": g, "status": s, "message": m} for g, s, m in report.rows],
            ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
