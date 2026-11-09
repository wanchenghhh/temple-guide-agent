# 上线前检查清单（寺庙寻访向导）

> 用法：照着从上往下做，每项都有**可执行的验证命令**。
> 一条命令跑完自动检查：`python scripts/preflight.py --online`

## 0. 一句话判断标准

**能给陌生人用** = ① 数据可核 ② 回答不编 ③ 挂了能降级 ④ 数据不丢 ⑤ 花销有上限。

---

## 1. 密钥与配置（缺一项就别上线）

| 项 | 要求 | 怎么检查 |
| --- | --- | --- |
| `AUTH_SECRET` | ≥32 位随机串；缺失时所有 `/api` 返回 503 | `preflight.py` → 配置组 |
| 模型 Key | `DEEPSEEK_API_KEY` 或 `LLM_*_API_KEY`；否则聊天是占位回复 | 同上（`llm=live`） |
| `DATA_DIR` | 可写；**必须挂持久盘**，否则重启全丢 | 同上 |
| `HARNESS_ADMIN_TOKENS` | `name:token[:scope]`，≥16 位；用于看指标 | `GET /api/admin/temple/metrics` |
| `SECRETS_FERNET_KEY` | 需要「安全输入区」时必填 | 同上 |
| `AMAP_KEY` | 行前路线；没有则只能给直线距离 | `preflight.py --online` |
| `QWEATHER_KEY` + `QWEATHER_HOST` | 天气；Host 是控制台里的专属地址 | 同上 |
| `BOCHA_KEY` + `BOCHA_ENABLED=1` | 评价摘要；关掉就只讲官方资料 | 同上 |
| `CHAT_RATE_PER_MIN` | 建议 30；防止误触循环 | 连发 31 次应出现 429 |
| `AGENT_COST_CAP_FREE_DAILY` | 建议 2 元；防止单用户烧穿 | 环境变量已设 |

**开关与 key 必须配对**：`TRAVEL_ENABLED=1` 却没 `AMAP_KEY`、`BOCHA_ENABLED=1` 却没 key，
会让每一轮都走降级路径——看起来"能用"，其实一直查不到。`preflight.py` 会把这种组合判 FAIL。

## 2. 数据可核

> **进度**：开放状态已核 **22/27**（A 级官方来源 21 座 + C 级网络整理 1 座，从 7 提到 22）；
> 剩余 5 座只能电话（法源寺/天宁寺/广化寺/广济寺/通教寺/云居寺中的 5 座；法源寺属"网络说法矛盾待解"）。
> 核对单：`docs/电话核对单.md`（按 P0/P1/P2 排序）；采纳评估见 `docs/专家核实-采纳评估.md`。
> 打完用一条命令落地，不会手改 JSON：
>
> ```bash
> python scripts/apply_open_info.py --temple 法源寺 --open yes --reservation no \
>     --closure none --ticket 免费 --hours 8:30-15:30 --source <官方链接>
> ```
>
> 没给 `--source` 就只更新开放信息，**不会**把来源升级成"已核实"。

```bash
python scripts/check_links.py --only-due      # 链接抽查（有失败退出码 1）
python scripts/render_temple_checklist.py      # 重生成复核清单
```

| 项 | 门槛 |
| --- | --- |
| 来源可核 | 30/30（任何一条 `unverified` 都要在回答里说"没查到官方出处"） |
| 链接抽查 | 失败 0；**每月跑一次**（可配 cron） |
| 坐标 | ≥28/30；缺的按区县估算并告知用户 |
| 人工抽查 | 从 `docs/eval-baseline.md` 的「人工抽查表」抽 10 条，逐条问"能否回到资料"，**编造一条即不算过关** |

## 3. 回答不编

```bash
python -m app.evals.temple_cli --mode live --sleep 0.4     # 50 条用例
```

| 指标 | 门槛 |
| --- | --- |
| 通过率 | 50/50 |
| **来源可追溯率** | **100%**（低于 100% 先查是哪条） |
| p95 时延 | ≤ 10 秒 |
| 红线 | 灵验分 / 排行榜 / 成功率 / 代订票 / 代发帖 全部拒绝 |

## 4. 挂了能降级

逐项确认（都可以手工触发）：

| 场景 | 期望 |
| --- | --- |
| 高德/和风挂或额度用完 | 回答里直接说查不到，**不给估算数字** |
| 博查挂或额度用完 | 只讲资料库内容，说"没找到相关分享" |
| 模型限流 | 网关重试后降级，用户看到明确提示而不是空回复 |
| 数据缺失（如云居寺无坐标） | 说"没有坐标，算不了距离" |
| 冲突写入 | 整轮 fail closed，用户看到 `E_NODE_FAILED`，数据不被覆盖 |

## 5. 数据不丢

```bash
python scripts/backup_data.py --keep 7        # 生成 data/backups/*.tar.gz
```

| 项 | 要求 |
| --- | --- |
| 持久盘 | Render 免费实例**没有盘**，必须换付费实例并挂 `disk`（见 `render.yaml` 注释） |
| 每日备份 | cron 跑 `backup_data.py`，并把 `data/backups` 同步到别处 |
| 恢复演练 | 最少做一次：解包 → 放回 DATA_DIR → 启动 → 记忆还在 |

## 6. 花销与容量

| 项 | 建议 |
| --- | --- |
| 单用户日/月上限 | 2 元 / 30 元（`AGENT_COST_CAP_*`） |
| LLM 并发 | `LLM_MAX_CONCURRENCY=8`（超出排队 10 秒后放弃） |
| 外部接口额度 | 地图天气 300/天、博查 200/天；看 `data/travel_usage.json`、`data/bocha_usage.json` |
| 压测 | `python scripts/load_chat.py -c 8 -n 34` 看 p95 与错误率 |

## 7. 隐私与告知

| 项 | 状态 |
| --- | --- |
| 首屏一次性告知（会记住心愿/出发地，可查看可删除） | ✅ 已内置（`privacyBanner`） |
| 记忆卡可查看 / 修改 / 删除 | ✅ `/api/memory/{uid}/card` |
| 不索取病史、婚姻状况等隐私 | ✅ 提示词红线 + 求子不替代医疗 |
| 不保存聊天里的密码 | ✅ 隐私门拦在进图之前 |
| 数据纠错入口 | ✅ 卡片「资料有误？」→ `POST /api/temple/report` |

## 8. 上线动作（按顺序）

1. `python scripts/preflight.py --online` → **0 项失败**
2. 打 tag、构建镜像：`docker build -t temple-guide .`
3. 配好 `render.yaml` 的环境变量（或目标平台的等价配置），**挂持久盘**
4. 部署后跑一遍：`python scripts/preflight.py --base https://你的域名 --online`
5. 用手机无痕窗口走一遍：首屏告知 → 问"我想求姻缘，从国贸出发" → 看卡片 → 点来源链接
6. 建立每日备份 cron + 每月链接抽查提醒
7. 一周后看指标：`python -m app.agent.temple_metrics --days 7`

## 9. 上线后每周只看三个数

| 指标 | 在哪看 | 变差意味着 |
| --- | --- | --- |
| 来源可追溯率 | `/api/admin/temple/metrics` | 模型开始编，或资料来源坏了 |
| 降级率 | 同上 | 外部接口挂了 / 额度用完了 / 数据缺失变多 |
| p95 时延 | 同上 | 下游变慢或数据量上涨 |

---

## 附：常用命令速查

```bash
python scripts/preflight.py --online                 # 上线自检
python scripts/check_links.py --only-due             # 链接抽查
python scripts/backup_data.py --keep 7               # 备份
python -m app.evals.temple_cli --mode live --sleep 0.4
python -m app.agent.temple_metrics --days 7          # 指标
python scripts/prune_eval_data.py --yes              # 清理评测残留（仅本地）
```
