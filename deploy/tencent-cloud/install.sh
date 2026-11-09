#!/usr/bin/env bash
# 腾讯云一键部署（Ubuntu / Debian / CentOS / TencentOS 均可）
#
# 在服务器上以 root 执行：
#   curl -fsSL https://raw.githubusercontent.com/<你>/<仓库>/main/deploy/tencent-cloud/install.sh -o install.sh
#   bash install.sh
#
# 或者先把仓库放上去（私有仓库需要 token）：
#   REPO_URL=https://<token>@github.com/wanchenghhh/temple-guide-agent.git bash install.sh
#
# 做四件事：装 Docker → 拉代码到 /opt/temple-guide → 生成 .env（缺的留空下次填）→ 起服务
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/temple-guide}
REPO_URL=${REPO_URL:-}
PORT=${PORT:-8787}
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[注意] %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m[失败] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 运行（sudo -i 后重跑）"

say "1/5 检查系统与 Docker"
if ! command -v docker >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 git curl || \
    DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose git curl
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y docker git curl
  elif command -v yum >/dev/null 2>&1; then
    yum install -y docker git curl
  else
    die "没识别到包管理器，请手动安装 docker 后重跑"
  fi
fi
systemctl enable --now docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
COMPOSE=""
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose";
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose";
else die "缺少 docker compose，请先安装"; fi
echo "  docker: $(docker --version | head -1)"
echo "  compose: $COMPOSE"

say "2/5 准备代码目录 $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --all -q && git -C "$APP_DIR" reset --hard origin/main -q
  echo "  已更新到 origin/main"
else
  [ -n "$REPO_URL" ] || die "首次安装需要 REPO_URL（私有仓库要带 token）：
  REPO_URL=https://<token>@github.com/wanchenghhh/temple-guide-agent.git bash install.sh"
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

say "3/5 生成 .env（缺的项留空，稍后填）"
ENV_FILE="$APP_DIR/deploy/tencent-cloud/.env"
if [ ! -f "$ENV_FILE" ]; then
  SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  HMAC=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  ADMIN=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
  sed -e "s|^AUTH_SECRET=.*|AUTH_SECRET=$SECRET|" \
      -e "s|^HARNESS_ID_HMAC_KEY=.*|HARNESS_ID_HMAC_KEY=$HMAC|" \
      -e "s|^HARNESS_ADMIN_TOKENS=.*|HARNESS_ADMIN_TOKENS=ops:$ADMIN:users:read|" \
      "$APP_DIR/deploy/tencent-cloud/.env.example.server" > "$ENV_FILE"
# ===== 必填 =====
AUTH_SECRET=$SECRET
HARNESS_ID_HMAC_KEY=$HMAC
HARNESS_ADMIN_TOKENS=ops:$ADMIN:users:read
DEEPSEEK_API_KEY=

# ===== 寺庙向导外部服务 =====
AMAP_KEY=
QWEATHER_KEY=
QWEATHER_HOST=
TRAVEL_ENABLED=1
TRAVEL_DAILY_CAP=300
BOCHA_API_KEY=
BOCHA_ENABLED=1
BOCHA_DAILY_CAP=200

# ===== 成本与限流 =====
AGENT_COST_CAP_FREE_DAILY=2
AGENT_COST_CAP_FREE_MONTHLY=30
CHAT_RATE_PER_MIN=30
PROACTIVE_TZ=Asia/Shanghai
DATA_DIR=/app/data
ENVEOF
  chmod 600 "$ENV_FILE"
  echo "  已生成：$ENV_FILE"
  echo "  管理员令牌（记下来，查指标用）：ops:$ADMIN:users:read"
else
  echo "  已存在，保留不覆盖：$ENV_FILE"
fi
mkdir -p "$APP_DIR/deploy/tencent-cloud/data"

say "4/5 构建并启动（首次 3-6 分钟）"
$COMPOSE -f deploy/tencent-cloud/docker-compose.yml up -d --build

say "5/5 等待健康检查"
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "  服务已就绪"
    break
  fi
  sleep 3
  [ "$i" = "40" ] && warn "健康检查没通过，看日志：docker logs -f temple-guide"
done

cat <<TIP

================ 部署完成 ================
本地自检： curl -s http://127.0.0.1:$PORT/health | head -c 300
查看日志： docker logs -f temple-guide
配置文件： $ENV_FILE  （填好 key 后： docker restart temple-guide）
数据目录： $APP_DIR/deploy/tencent-cloud/data  （务必备份）

⚠️ 腾讯云控制台「安全组」要放行端口 $PORT（或用 nginx 时放行 80/443），否则外网访问不到。
⚠️ 大陆服务器绑定域名需要 ICP 备案；没备案就先用 http://<公网IP>:$PORT。

每天备份（加到 root 的 crontab）：
  0 4 * * * cd $APP_DIR && docker run --rm -v \$PWD/deploy/tencent-cloud/data:/data -v \$PWD/deploy/tencent-cloud/backups:/backups alpine tar czf /backups/pa-\$(date +\\%F).tar.gz -C /data .
==========================================

TIP
