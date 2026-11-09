#!/usr/bin/env bash
# 部署后冒烟：健康 → 会话 → 一次寺庙对话 → 卡片 → 指标
# 用法：bash smoke.sh [http://127.0.0.1:8787] [admin-token]
set -uo pipefail
BASE=${1:-http://127.0.0.1:8787}
ADMIN=${2:-}
pass=0; fail=0
ok()  { echo "  ✓ $*"; pass=$((pass+1)); }
bad() { echo "  ✗ $*"; fail=$((fail+1)); }

echo "== 1. /health =="
H=$(curl -fsS "$BASE/health" 2>/dev/null)
if [ -z "$H" ]; then bad "/health 无响应"; else
  echo "$H" | grep -q '"ok":true' && ok "/health ok" || bad "/health 内容异常"
  echo "$H" | grep -q '"llm":"live"' && ok "模型 live" || bad "模型是 mock（检查 DEEPSEEK_API_KEY）"
fi

echo "== 2. 会话 =="
JAR=$(mktemp)
S=$(curl -fsS -c "$JAR" -X POST "$BASE/api/session" 2>/dev/null)
echo "$S" | grep -q '"status":"session"' && ok "会话签发" || bad "会话签发失败"

echo "== 3. 寺庙对话 =="
R=$(curl -fsS -b "$JAR" -X POST "$BASE/api/chat" -H 'Content-Type: application/json' \
     -d '{"message":"我想求姻缘，从国贸出发"}' 2>/dev/null)
if echo "$R" | grep -q '"temple_card"'; then ok "返回了推荐卡片"; else bad "没有推荐卡片"; fi
echo "$R" | grep -qE '"error":"E_[A-Z_]+"' && bad "出现错误码" || ok "无错误码"
echo "$R" | grep -q '灵验分' && bad "回答出现灵验分" || ok "无灵验分"

echo "== 4. 指标接口 =="
if [ -n "$ADMIN" ]; then
  M=$(curl -fsS -H "Authorization: Bearer $ADMIN" "$BASE/api/admin/temple/metrics?days=1" 2>/dev/null)
  echo "$M" | grep -q '"turns"' && ok "指标可读" || bad "指标接口异常（检查令牌 scope）"
else
  echo "  - 跳过（没给管理员令牌）"
fi

rm -f "$JAR"
echo
echo "结果：$pass 通过，$fail 失败"
[ "$fail" = "0" ] || exit 1
