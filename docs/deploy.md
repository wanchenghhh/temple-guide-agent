# 部署到 Render（GitHub 一键）

本服务是 **FastAPI**，不能用 GitHub Pages。推荐用 Render 免费 Web Service，从本仓库一键拉起。

## 一键部署

打开（需已登录 Render，并授权 GitHub 仓库）：

**https://render.com/deploy?repo=https://github.com/wanchenghhh/temple-guide-agent**

会读取根目录 `render.yaml` Blueprint，创建 Docker Web Service（free）。

也可在 Render Dashboard → **New** → **Blueprint** → 选本仓库。

## 必须配置的密钥（Environment）

在 Render 服务的 **Environment** 里填写（`sync: false` 的项不会从 Blueprint 自动带值）：

| 变量 | 说明 |
|------|------|
| `AUTH_SECRET` | **必填**，Blueprint 自动生成（`generateValue`）。缺失时所有 `/api` 返回 503 |
| `HARNESS_ID_HMAC_KEY` | Blueprint 自动生成。轨迹里的用户假名密钥，保持不变才能前后对得上 |
| `SECRETS_FERNET_KEY` | 安全输入区加密密钥（Fernet）。生成：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HARNESS_ADMIN_TOKENS` | 可选。管理接口令牌（`name:token[:scope]`，≥16 位），不填则管理接口关闭 |
| `KIMI_API_KEY` | **建议必填**。Moonshot/Kimi Key，用于真机对话 |
| `LLM_FAST_API_KEY` / `LLM_STRONG_API_KEY` | 可选；空则回退用 `KIMI_API_KEY` / `MOONSHOT_API_KEY` |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 可选。飞书通道；公网部署建议先关长连接（Blueprint 默认 `FEISHU_WS_ENABLED=0`） |
| `OPENCLAW_*` | 可选。微信 OpenClaw 桥 |

Blueprint 已预置：FAST/STRONG 都走 Kimi（`kimi-k2.6` / `kimi-k3`）、`CORS_ALLOW_ORIGINS=*`、`DATA_DIR=/app/data`。

不填任何 LLM Key 也能启动，但聊天走 **mock**（草稿为离线占位稿），仅便于冒烟。

## 寺庙向导专属变量（本仓新增）

| 变量 | 说明 |
| --- | --- |
| `AMAP_KEY` | 高德开放平台 Key：地理编码 + 路径规划（行前路线） |
| `QWEATHER_KEY` / `QWEATHER_HOST` | 和风天气 Key + **专属 API Host**（控制台可见，形如 `https://xxxx.re.qweatherapi.com`） |
| `TRAVEL_ENABLED` / `TRAVEL_DAILY_CAP` | 行前数据开关与每日额度（默认 1 / 300） |
| `BOCHA_API_KEY` / `BOCHA_ENABLED` / `BOCHA_DAILY_CAP` | 公开分享搜索（评价摘要）开关与额度（默认 0 / 200） |
| `CHAT_RATE_PER_MIN` | 每会话每分钟提问上限（建议 30，0=不限） |
| `AGENT_COST_CAP_FREE_DAILY` / `_MONTHLY` | 单用户费用上限（建议 2 / 30 元） |

> **开关和 key 必须配对**：开着 `TRAVEL_ENABLED=1` 却没配 `AMAP_KEY`，每一轮都会降级成"查不到"——
> `scripts/preflight.py` 会把这种组合判 FAIL。

## 上线前必读

完整清单在 **[pre-launch-checklist.md](pre-launch-checklist.md)**，一条命令自检：

```bash
python scripts/preflight.py --online
```

其中两条最容易被忽略：

1. **Render 免费实例没有持久盘**：`DATA_DIR`（记忆、指标、评测）重启即清空。
   真正给人用必须换付费实例并挂盘：`disk: {name: data, mountPath: /app/data, sizeGB: 1}`。
2. **每日备份**：`python scripts/backup_data.py --keep 7`（SQLite 热备份，不锁库），
   并把 `data/backups` 同步到对象存储或网盘。

## 部署完成后

1. Render 给一个 `https://xxx.onrender.com` 地址  
2. 浏览器打开根路径 `/` → 对话页；`/health` → 健康检查  
3. Mac 直接用该 HTTPS 地址即可聊（同域 API，无需额外 CORS）

免费实例**冷启动**可能要等几十秒。

> ⚠️ **免费套餐只适合演示**：磁盘非持久，每次重新部署或重启，`DATA_DIR` 里的全部数据（用户档案、对话、记忆、定时任务）都会清空。要给真实用户用，需升级到付费套餐并加 Disk 挂到 `/app/data`（`render.yaml` 里有注释示例）。

## 本地 Docker 自检（可选）

```bash
docker build -t temple-guide .
docker run --rm -p 8787:8787 -e DEEPSEEK_API_KEY=你的key temple-guide
# 打开 http://127.0.0.1:8787/
```

## GitHub Actions（必需）

部署必须通过门禁工作流 `.github/workflows/deploy-render.yml`，并在仓库 Secrets 中配置 `RENDER_API_KEY`（以及可选 `RENDER_SERVICE_ID`）。

## 相关文件

- `Dockerfile` — 生产镜像  
- `render.yaml` — Render Blueprint  
- `.dockerignore` — 排除 `.venv` / `data` / `.env`  
