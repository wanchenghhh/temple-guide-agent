# 腾讯云部署（寺庙寻访向导）

> **第一次用腾讯云？** 先看手把手：`docs/腾讯云开通-手把手.md`（注册/实名/免费试用/放行端口/上传/验证，全流程带截图位置说明）

> 目标：一台轻量应用服务器（2核2G 起）+ Docker，30 分钟内跑起来。
> **没备案也能内测**：先用 `http://公网IP:8787`，备案下来再上域名 + HTTPS。

---

## 一、买机器与放行端口

1. **轻量应用服务器**（推荐）或 CVM：
   - 配置：**2 核 2G**（1G 内存也能跑，但构建镜像容易 OOM，建议 2G）
   - 系统：**Ubuntu 22.04 / 24.04**（Debian 12、TencentOS 也行）
   - 地域：**北京/上海/广州**（离高德、和风、博查都近，延迟低）
   - 磁盘：40G 起（数据很小，主要给 Docker 镜像）
2. 控制台 → **防火墙/安全组** 放行：
   - 内测阶段：**TCP 8787**
   - 有 nginx/域名时：**TCP 80、443**（8787 可以关掉）

> ⚠️ 大陆服务器绑域名需要 **ICP 备案**（未备案的域名指向 80/443 会被拦）。
> 所以内测阶段直接用 IP:8787，最快。

---

## 二、把代码放上服务器（二选一）

### 方式 A：用 GitHub token 直接拉（推荐）

1. GitHub → Settings → Developer settings → **Personal access tokens (fine-grained)**
   → 生成一个只读、只授权 `temple-guide-agent` 仓库的 token（有效期 30 天）
2. SSH 登录服务器，执行：

```bash
sudo -i
REPO_URL=https://<token>@github.com/wanchenghhh/temple-guide-agent.git \
  bash <(curl -fsSL https://raw.githubusercontent.com/wanchenghhh/temple-guide-agent/main/deploy/tencent-cloud/install.sh)
```

> 私有仓库不能用匿名 `curl install.sh`，所以上面的写法是「先有 token 才能拉」。
> 更简单的做法见方式 B。

### 方式 B：从你的 Mac 直接传（不用 token）

```bash
# 在你的 Mac 上，项目目录里执行
tar --exclude='.venv' --exclude='data' --exclude='.git' --exclude='__pycache__' \
    -czf /tmp/temple-guide.tgz .
scp /tmp/temple-guide.tgz root@<公网IP>:/root/

# 服务器上
sudo -i
mkdir -p /opt/temple-guide && tar xzf /root/temple-guide.tgz -C /opt/temple-guide
cd /opt/temple-guide
# 生成 .env 并构建
bash deploy/tencent-cloud/bootstrap-local.sh
```

---

## 三、填 4 个 key（唯一需要你手动做的事）

```bash
nano /opt/temple-guide/deploy/tencent-cloud/.env
```

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `AUTH_SECRET` | ✅ 已自动生成 | 不要改（改了所有人会话失效） |
| `DEEPSEEK_API_KEY` | ✅ | 不填则聊天是占位回复 |
| `AMAP_KEY` | 建议 | 不填则行前只能给直线距离 |
| `QWEATHER_KEY` + `QWEATHER_HOST` | 建议 | Host 必须带 `https://` |
| `BOCHA_API_KEY` | 建议 | 不填则不做公开评价摘要 |

改完重启：

```bash
cd /opt/temple-guide && docker compose -f deploy/tencent-cloud/docker-compose.yml up -d
```

---

## 四、自检（必须全绿再发内测）

```bash
# 本地冒烟（6 项）
bash /opt/temple-guide/deploy/tencent-cloud/smoke.sh http://127.0.0.1:8787 <ops token>

# 完整自检（21 项；--online 会消耗少量外部额度）
docker exec -it temple-guide python scripts/preflight.py \
    --base http://127.0.0.1:8787 --online --admin-token <ops token>
```

> `<ops token>` 在 `install.sh` 的输出里（`ops:xxxx:users:read`），也可以打开 `.env` 看 `HARNESS_ADMIN_TOKENS`。

---

## 五、日常运维（三条命令）

```bash
# 看日志
docker logs -f --tail 100 temple-guide

# 更新到最新代码（备份 → 拉取 → 重建）
cd /opt/temple-guide && git pull && \
docker compose -f deploy/tencent-cloud/docker-compose.yml up -d --build

# 数据在宿主机（不要删）
ls -lh /opt/temple-guide/deploy/tencent-cloud/data
```

### 每日备份（加一次 crontab 就行）

```bash
crontab -e
# 每天 04:00 备份，保留 14 天
0 4 * * * cd /opt/temple-guide && docker run --rm \
  -v /opt/temple-guide/deploy/tencent-cloud/data:/data:ro \
  -v /opt/temple-guide/backups:/backups alpine \
  tar czf /backups/pa-$(date +\%F).tar.gz -C /data . && \
  find /backups -name 'pa-*.tar.gz' -mtime +14 -delete
```

> 建议再把 `/opt/temple-guide/backups` 同步到腾讯云 COS（`coscli cp -r`），
> 机器挂了才不至于全丢。

---

## 六、要上域名 + HTTPS 时

1. 域名解析 `A` 记录到公网 IP
2. **完成 ICP 备案**（腾讯云控制台有备案入口，1–2 周）
3. 装 nginx 与证书：

```bash
apt-get install -y nginx certbot python3-certbot-nginx
cp /opt/temple-guide/deploy/tencent-cloud/nginx.conf /etc/nginx/conf.d/temple-guide.conf
sed -i 's/your-domain.com/你的域名/' /etc/nginx/conf.d/temple-guide.conf
nginx -t && systemctl reload nginx
certbot --nginx -d 你的域名 --agree-tos -m 你的邮箱 --redirect
```

4. 把 compose 里的端口改回 `127.0.0.1:8787`（已经是），安全组关掉 8787。

---

## 七、常见问题

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| 外网打不开但服务器上 curl 正常 | 安全组没放行 | 控制台放行 8787（或 80/443） |
| `/health` 里 `llm: mock` | 没填 `DEEPSEEK_API_KEY` | 填上后 `docker restart temple-guide` |
| 行前总说"查不到" | `QWEATHER_HOST` 少了 `https://`，或 `AMAP_KEY` 没填 | 改 `.env` 后重启 |
| 构建时内存不足被 kill | 1G 内存太小 | 加 swap（`fallocate -l 2G /swapfile`）或升配 |
| 重启后记忆没了 | `data` 目录没挂到宿主机 | 检查 compose 的 `volumes: ./data:/app/data` |
| 上传/对话 502 | nginx 超时太短 | `proxy_read_timeout 120s`（模板已含） |
