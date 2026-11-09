#!/usr/bin/env bash
# 方式 B 用：代码已经 scp 到 /opt/temple-guide（含 .git 也可以没有），
# 这里只负责「装 docker → 生成 .env → 构建启动」。
#   cd /opt/temple-guide && bash deploy/tencent-cloud/bootstrap-local.sh
set -euo pipefail
APP_DIR=$(cd "$(dirname "$0")/../.." && pwd)
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m[失败] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 运行（sudo -i 后重跑）"

say "1/4 检查 Docker"
if ! command -v docker >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 curl
  elif command -v dnf >/dev/null 2>&1; then dnf install -y docker curl
  elif command -v yum >/dev/null 2>&1; then yum install -y docker curl
  else die "请先安装 docker"; fi
fi
systemctl enable --now docker >/dev/null 2>&1 || true
COMPOSE=""
docker compose version >/dev/null 2>&1 && COMPOSE="docker compose"
[ -z "$COMPOSE" ] && command -v docker-compose >/dev/null 2>&1 && COMPOSE="docker-compose"
[ -n "$COMPOSE" ] || die "缺少 docker compose"

say "2/4 生成 .env"
ENV_FILE="$APP_DIR/deploy/tencent-cloud/.env"
if [ ! -f "$ENV_FILE" ]; then
  SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  HMAC=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  ADMIN=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
  sed -e "s|^AUTH_SECRET=.*|AUTH_SECRET=$SECRET|" \
      -e "s|^HARNESS_ID_HMAC_KEY=.*|HARNESS_ID_HMAC_KEY=$HMAC|" \
      -e "s|^HARNESS_ADMIN_TOKENS=.*|HARNESS_ADMIN_TOKENS=ops:$ADMIN:users:read|" \
      "$APP_DIR/deploy/tencent-cloud/.env.example.server" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "  已生成 $ENV_FILE"
  echo "  管理员令牌：ops:$ADMIN:users:read（记下来）"
else
  echo "  已存在，保留：$ENV_FILE"
fi
mkdir -p "$APP_DIR/deploy/tencent-cloud/data"

say "3/4 构建并启动（首次 3-6 分钟）"
cd "$APP_DIR"
$COMPOSE -f deploy/tencent-cloud/docker-compose.yml up -d --build

say "4/4 健康检查"
for i in $(seq 1 40); do
  curl -fsS http://127.0.0.1:8787/health >/dev/null 2>&1 && { echo "  服务已就绪"; break; }
  sleep 3
done
cat <<TIP

接着做两件事：
1) 填 key：nano $ENV_FILE   然后 docker restart temple-guide
2) 冒烟：bash deploy/tencent-cloud/smoke.sh http://127.0.0.1:8787 <ops token>
⚠️ 腾讯云安全组记得放行 8787（或 80/443）
TIP
