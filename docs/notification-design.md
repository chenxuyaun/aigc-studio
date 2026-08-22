# 统一通知系统 · 可落地设计方案

> 目标：把「开奖完成 / 生图完成 / 代理故障 / 每日预测摘要」等事件推送到用户手机/桌面，
> 约束：Ubuntu 24.04 · 2GB RAM · 国内可用 · 尽量不引入额外服务器 · 轻量。

---

## 0. TL;DR

| 决策点 | 结论 |
|---|---|
| 推送渠道 | **企业微信群机器人 Webhook 为主**，Telegram Bot 作为境外/功能增强备选，邮件仅做「每日摘要」兜底 |
| 事件上报 | **事件源内嵌 `notify()` 钩子（webhook 推送）** 为主；Clash 这种 systemd 进程由通知服务**主动轮询** |
| 部署形态 | **独立常驻轻量服务**（Python ~50MB，绑定 `127.0.0.1:8800`，systemd 托管） |
| 去重/合并 | `dedup_key` 幂等去重 + `merge_key` 时间窗合并 + 每渠道令牌桶限流 + 告警状态机（只在状态翻转时发） |
| 配置 | 服务端一个 `config.toml`；事件源各自 `.env` 加 3~4 行 |

---

## 1. 推送渠道选型

### 1.1 对比

| 渠道 | 国内可用性 | 额外服务器 | 接入成本 | 实时性 | 消息能力 | 风险/坑 |
|---|---|---|---|---|---|---|
| **企业微信 Webhook（群机器人）** | ✅ 直连，无需代理 | 无 | 最低：一个 `POST` JSON | 秒级 | text/markdown/图片（4KB 内）、`@` 人 | 单条消息 2048B(text)/4096B(markdown) 上限；需建一个群拉机器人；Webhook URL 即凭据 |
| **Telegram Bot API** | ⚠️ 需代理（服务器已有 Clash 7897，可 `HTTPS_PROXY` 走通） | 无（用官方 API） | 低：`getUpdates` 拿 chat_id 后 `sendMessage` | 秒级 | Markdown/HTML/图片/按钮/编辑消息，能力最强 | 国内收消息需客户端翻墙；首次要拿到个人 `chat_id` |
| **钉钉 Webhook** | ✅ 直连 | 无 | 中：需 `timestamp+secret` 加签 | 秒级 | text/markdown | 必须加签（HMAC-SHA256），比企业微信多一步；同样有消息体上限 |
| **邮件 SMTP** | ✅ | 无（需一个 SMTP 账号） | 中 | 分钟级 | 富文本/附件 | 到达率差（易进垃圾箱）、实时性差；不适合「代理故障」这类即时告警 |

### 1.2 推荐组合

1. **默认启用：企业微信群机器人** —— 国内直连、零服务器、一个 HTTP POST 就完事，是「最简单」的正解。个人系统拉一个「通知群」即可。
2. **备选/增强：Telegram Bot** —— 服务器已有 Clash，加一行 `HTTPS_PROXY=http://127.0.0.1:7897` 就能发；适合人在境外、或想要「点击按钮跳转到生图结果 / 开奖看板」的交互式消息。
3. **兜底：SMTP 邮件** —— 只用于「每日预测摘要」归档，不作为实时告警渠道。

> 设计上所有渠道统一走一个 `ChannelAdapter` 接口，`config.toml` 里勾选启用哪个，互不干扰。

---

## 2. 事件源接入方式（关键：哪些轮询、哪些 webhook）

先确认代码里的**精确挂钩点**（已核实）：

| 事件 | 服务 | 现有挂钩点 | 接入方式 |
|---|---|---|---|
| 开奖完成 / 失败 | lotto（`yc`） | `server/app.py` 的 `_refresh_worker()`（成功设 `_state["last_refresh"]`，失败 `log("refresh failed")`），由 `_daily_scheduler()` 每天 21:45 触发 | **内嵌 `notify()` 钩子（推送）** |
| 每日预测摘要 | lotto | `src/run_all.py` 的 `write_summary()` 已生成 `output/predictions_summary.md` | **内嵌钩子**，把摘要文本塞进事件 `payload` |
| 生图/文本/视频…完成 / 失败 | saiOS（`apps/api`） | `app/services/task_runner.py` 的 `_run_media_task_locked()`：`succeeded`（L714）/ `failed`（L776）终态写库处 | **内嵌 `notify()` 钩子（推送）** |
| 代理故障 / 恢复 | Clash/Mihomo（systemd） | 无主动上报；Mihomo 有 REST API `127.0.0.1:9090/version`（Bearer `CLASH_SECRET`，nginx `/clash/api/` 已反代） | **通知服务定时轮询 + 告警状态机** |
| （可选）writers / searxng 宕机 | writers（Go）· searxng | 各自有 `/healthz`（nginx 已代理） | 通知服务可选轮询探活 |

### 2.1 原则：能推送就不轮询

- **saiOS 生图**：任务完成是**事件驱动**（随时发生），必须用**内嵌钩子**——在 `task_runner.py` 两个终态分支后各加一行 `await notify(event)`（fire-and-forget，失败静默降级，绝不影响生图主流程）。轮询 DB 的方式要每 15s 扫 `generation_tasks`，2GB 机器上纯属浪费且不实时。
- **lotto 开奖**：同样用**内嵌钩子**——`_refresh_worker()` 成功/失败处调用 `notify()`。它本来就是每天 21:45 定时跑一次，事件天然稀疏，无需轮询。
- **Clash 代理故障**：systemd 进程自己不会上报，**只能由通知服务主动轮询**（这是唯一合理的轮询场景），且用「连续失败 N 次才报警 + 恢复再报一次」的状态机避免抖动刷屏。

### 2.2 各源接入细节

**① saiOS 生图（`apps/api/app/services/task_runner.py`）**

```python
# 成功分支（原 L714 task.status = "succeeded" 之后）
await notify_event({
    "source": "saios",
    "type": "saios.generation.succeeded",
    "severity": "success",
    "dedup_key": f"saios:task:{task.id}",        # 每任务唯一，天然幂等
    "merge_key": f"saios:{task.task_type}",      # 同类任务合并
    "payload": {
        "task_id": task.id, "task_type": task.task_type,
        "model": model_name, "is_real": used_real,
        "asset_id": asset.id, "url": sign_content_url(str(asset.id)),
    },
})
# 失败分支（原 L776 task.status = "failed" 之后）同理，severity="error"，type="saios.generation.failed"
```

`notify_event()` 是一个共享小工具：读 `NOTIFY_WEBHOOK_URL`，`httpx` 异步 POST 到通知服务，超时 2s，任何异常 `log + swallow`。

**② lotto 开奖 + 摘要（`yc/server/app.py` 的 `_refresh_worker`）**

```python
def _refresh_worker(do_fetch):
    try:
        payload = run_pipeline(do_fetch=do_fetch, log=log)   # 改为接收返回值
        _state["last_refresh"] = ...
        notify_event({"source": "lotto", "type": "lotto.draw.completed",
                      "severity": "success", "dedup_key": "lotto:draw:ok",
                      "merge_key": "lotto:draw", ...})
        # 每日摘要：payload 里直接带 write_summary 已生成的 markdown（截断）
        summary = open(OUT_DIR + "/predictions_summary.md", encoding="utf-8").read()
        notify_event({"source": "lotto", "type": "lotto.prediction.daily",
                      "severity": "info", "dedup_key": "lotto:summary:" + date,
                      "merge_key": "lotto:summary",
                      "payload": {"markdown": summary[:3800]}})  # 截断适配渠道上限
    except Exception as e:
        notify_event({"source": "lotto", "type": "lotto.draw.failed",
                      "severity": "error", "dedup_key": "lotto:draw:err",
                      "payload": {"error": str(e)}})
```

> `predictions_summary.md` 已经由 `write_summary()` 每天生成（含各彩种集成预测 + 推荐注 + 奖级模拟 ROI），是现成的摘要内容，无需另算。

**③ Clash 代理故障（通知服务内置探测器）**

通知服务每 60s 探一次 `GET http://127.0.0.1:9090/version`（带 `Authorization: Bearer $CLASH_SECRET`），
或更严格地「走代理抓一个外网 URL」（如 `HTTPS_PROXY=http://127.0.0.1:7897 curl api.x.ai`）。
维护状态机：`OK → (连续 3 次失败) → DOWN`、`DOWN → (1 次成功) → OK`，只在状态翻转时发事件
（`clash.proxy.down` / `clash.proxy.recovered`）。

---

## 3. 统一事件 JSON Schema

所有事件源发往通知服务的唯一契约（envelope + 事件特定 `payload`）：

```jsonc
{
  "schema_version": "1.0",
  "event_id": "7f3c1a2e-...-uuid",        // 服务端生成；事件源可留空
  "source": "lotto | saios | clash | writers | searxng | notify",   // 事件来源服务
  "type": "saios.generation.succeeded",     // <source>.<domain>.<action> 三段式
  "severity": "info | success | warning | error",
  "timestamp": "2026-08-19T21:46:02+08:00", // ISO 8601 带时区
  "title": "双色球开奖已更新",               // 通知标题（空则由服务端按 type 生成）
  "message": "第 2026096 期预测已存档",       // 正文（markdown 可带换行）
  "dedup_key": "lotto:draw:20260819",       // 幂等去重键（同 key 窗口内只发一次）
  "merge_key": "lotto:draw",                // 合并键（同 key 窗口内合并成一条）
  "priority": "high | normal | low",        // high 不合并；low 合并
  "payload": { }                            // 事件特定字段，见下
}
```

### 3.1 四类事件的 `type` 与 `payload` 示例

**① 开奖完成**
```json
{ "source":"lotto", "type":"lotto.draw.completed", "severity":"success",
  "priority":"high", "dedup_key":"lotto:draw:20260819", "merge_key":"lotto:draw",
  "payload": { "generated_at":"2026-08-19 21:46:02", "games":["ssq","dlt","kl8","qxc","pl5"] } }
```

**② 生图完成**
```json
{ "source":"saios", "type":"saios.generation.succeeded", "severity":"success",
  "priority":"low", "dedup_key":"saios:task:1a2b3c", "merge_key":"saios:image",
  "payload": { "task_id":"1a2b3c","task_type":"image","model":"grok-imagine-image",
               "asset_id":"9f8e7d","url":"/api/v1/assets/9f8e7d/access-url","is_real":true } }
```

**③ 代理故障 / 恢复**
```json
{ "source":"clash", "type":"clash.proxy.down", "severity":"error",
  "priority":"high", "dedup_key":"clash:down:1", "merge_key":"clash:proxy",
  "payload": { "failures":3, "since":"2026-08-19 22:10:00", "target":"https://api.x.ai" } }
```

**④ 每日预测摘要**
```json
{ "source":"lotto", "type":"lotto.prediction.daily", "severity":"info",
  "priority":"normal", "dedup_key":"lotto:summary:20260819", "merge_key":"lotto:summary",
  "payload": { "markdown":"# 预测摘要 · ...", "issue":"2026096", "games":["ssq","dlt"] } }
```

### 3.2 建议统一 `type` 清单（第一阶段）

| type | 含义 | 优先级 |
|---|---|---|
| `lotto.draw.completed` / `lotto.draw.failed` | 开奖数据更新成功/失败 | high |
| `lotto.prediction.daily` | 每日预测摘要 | normal |
| `saios.generation.succeeded` / `saios.generation.failed` | 生成任务成功/失败（image/text/video/audio/music/comic 用 `payload.task_type` 区分） | low |
| `clash.proxy.down` / `clash.proxy.recovered` | 代理故障/恢复 | high |
| `notify.health` | 通知服务自身心跳（可选，用于确认链路通） | low |

---

## 4. 推送服务部署（2GB 内存约束）

### 4.1 形态结论：独立常驻轻量服务

- **为什么独立**：四个事件源跨进程（lotto=FastAPI、saiOS=FastAPI+Celery、clash=systemd、writers=Go），需要一个**中立的聚合点**。并进 saiOS 会让「saiOS 挂了通知也没了」，且生图钩子跑在 saiOS 里、开奖钩子又跑在 lotto 里，仍需要一个统一收口做去重/限流。
- **为什么常驻（而非 cron 脚本）**：saiOS 生图完成是事件驱动、随时发生，需要常驻 HTTP 端点收 webhook；Clash 探测也需要常驻定时器。纯 cron 脚本接不住「生图完成」这类推送。

### 4.2 技术选型（刻意轻）

```
notify/                         # 独立小目录，跟 aigc-studio 平级部署
├── notify.py                   # 单文件即可：asyncio + httpx + http.server（或 FastAPI）
├── config.toml                 # 渠道 + 路由 + 限流 + 探测配置
├── requirements.txt            # httpx（如需 FastAPI 则加 fastapi/uvicorn）
└── notify.service              # systemd unit
```

- **推荐单文件 + 标准库 `asyncio` + `http.server`**（或 FastAPI，二选一都行）。不用数据库、不用 Redis——去重/合并状态用内存 `dict + TTL`，个人系统重启丢状态可接受。
- 内存占用 ~**40–60MB**，2GB 机器完全无感。
- 端口选 **`127.0.0.1:8800`**（已占用端口：5000/8000/8001/8002/8003/8011/8081/8300/8317/8420/8600/8891/9090/5433/7897/4000，8800 空闲）。
- **只绑 127.0.0.1，不暴露公网**（与现有服务一致）。

### 4.3 对外接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST /notify` | 收事件 | 事件源推送统一事件 envelope；服务端做去重/合并/限流后路由到渠道 |
| `POST /admin/reload` | 重载配置 | 改 `config.toml` 后热加载（免重启） |
| `GET /healthz` | 探活 | 返回 `{"ok":true,"channels":["wecom","telegram"]}` |
| `GET /admin/state` | 调试 | 查看当前去重表/限流桶/告警状态机快照 |

### 4.4 systemd

```ini
[Unit]
Description=Unified Notification Service
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/notify
ExecStart=/home/ubuntu/notify/.venv/bin/python notify.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### 4.5 内嵌 `notify_event()` 共享工具（给各事件源复用）

一个约 40 行的小函数，可复制进 lotto 与 saiOS（各自项目独立，避免跨项目 import）：

```python
async def notify_event(event: dict) -> None:
    if not (url := os.environ.get("NOTIFY_WEBHOOK_URL")):
        return                                   # 未配置即关闭
    event.setdefault("timestamp", datetime.now(UTC).isoformat())
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            await c.post(url, json=event)
    except Exception:
        pass                                     # 通知失败绝不影响主流程
```

---

## 5. 去重 / 合并 / 频率限制

### 5.1 三层管道（事件进来按顺序过）

```
事件 → [1 去重] → [2 合并] → [3 限流] → [4 渠道路由] → 发送
```

**① 幂等去重（防重复推送）**
- 按 `dedup_key` 维护 `dict[key] = timestamp`，TTL 默认 24h。
- 同 `dedup_key` 在 TTL 内重复到达 → 直接丢弃。
- 例：saiOS 的 `drain_queued_tasks` 与 Celery worker 可能对同一 `task_id` 双执行，`dedup_key = "saios:task:<id>"` 天然挡住重复通知。

**② 时间窗合并（防刷屏）**
- 按 `merge_key` 维护「未发送的待发桶」，窗口默认 60s（可配置）。
- 窗口内同类事件累积，到期发一条合并消息：「✅ 3 张图片生成完成、1 个失败」。
- 规则：`priority == "high"` **不合并**（开奖、代理故障立即发）；`low`（生图）**合并**；`normal` 按配置。

**③ 令牌桶限流（每渠道硬上限）**
- 每渠道独立：`rate_per_minute`（默认 20）、`rate_per_day`（默认 200）。
- 溢出事件：高优先级入「死信」，每日 23:59 汇总成一条「今日被限流 N 条」发出；低优先级直接丢。
- 目的：渠道异常/事件风暴时绝不把机器人/邮箱打爆。

### 5.2 告警状态机（代理故障专用）

```
OK ──连续失败≥3次──▶ DOWN（发 clash.proxy.down）
DOWN ──1次成功──▶ OK（发 clash.proxy.recovered）
```

只在**状态翻转**时发消息，避免每 60s 一条「代理还是挂的」刷屏。

### 5.3 发送失败重试

- 发送失败指数退避重试最多 3 次（1s/2s/4s），仍失败 → 记本地日志 + 进死信。
- 死信在下次任意事件到达时搭车重发一次，避免个人系统静默丢事件。

---

## 6. 配置方式（用户改哪里）

### 6.1 通知服务端：`/home/ubuntu/notify/config.toml`

```toml
[channels.wecom]                      # 企业微信（默认主渠道）
enabled = true
webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=XXX"   # 密钥，600 权限
kind = "wecom"

[channels.telegram]                   # 备选（走 Clash 代理）
enabled = false
bot_token = "123456:ABC..."
chat_id = "-100123456789"
proxy = "http://127.0.0.1:7897"

[channels.smtp]                       # 兜底（仅摘要归档）
enabled = false
host = "smtp.example.com"
port = 465
user = "notify@example.com"
password = "..."                      # 或走 .env 注入
to = ["me@example.com"]

[routing]                             # type 前缀 → 渠道（未命中走 default）
default = ["wecom"]
"lotto.prediction.daily" = ["wecom", "smtp"]
"clash.proxy." = ["wecom", "telegram"]
"saios.generation.succeeded" = ["wecom"]

[rate_limit]
per_minute = 20
per_day = 200
merge_window_seconds = 60

[probe.clash]                         # 代理故障探测
enabled = true
interval_seconds = 60
fail_threshold = 3
version_url = "http://127.0.0.1:9090/version"
secret_env = "CLASH_SECRET"           # 从环境变量读，不落盘明文
```

> 密钥（webhook_url / bot_token / smtp 密码 / CLASH_SECRET）**不要写进 config.toml 明文**：
> 统一放服务器 `/home/ubuntu/.deploy-env`（600 权限），由 systemd 的 `EnvironmentFile` 注入，
> `config.toml` 里只写引用名（如 `secret_env = "CLASH_SECRET"`）。

### 6.2 事件源侧：各项目 `.env`（3~4 行）

**saiOS `apps/api/.env`**（`config.py` 的 `Settings` 加 2 个字段即可）：
```bash
NOTIFY_ENABLED=1
NOTIFY_WEBHOOK_URL=http://127.0.0.1:8800/notify
```

**lotto `yc/` 项目**（docker-compose.yml 的 `environment` 段加两行）：
```yaml
environment:
  - NOTIFY_ENABLED=1
  - NOTIFY_WEBHOOK_URL=http://host.docker.internal:8800/notify   # 容器内回环需走 host.docker.internal
```

> ⚠️ 容器内访问宿主机 `127.0.0.1` 不可达（AGENTS.md 已记的坑），lotto 是 docker 部署，必须用
> `host.docker.internal:8800`；saiOS 的 api 容器同理。若通知服务与 saiOS 挂同一 docker 网络，
> 可用容器名 `notify:8800` 直连。

### 6.3 改配置后生效

- 通知服务：改 `config.toml` 后 `curl -X POST 127.0.0.1:8800/admin/reload` 热加载（或 `systemctl restart notify`）。
- 事件源：改 `.env` 后需重启对应服务（saiOS 需 `docker compose up -d --build api worker`；lotto 需 `docker compose restart`）。

---

## 7. 分阶段落地清单

| 阶段 | 内容 | 改动面 |
|---|---|---|
| **P0（半天）** | 通知服务骨架：`/notify` 端点 + 企业微信 channel + 去重/限流 + systemd | 新增 `notify/` 目录，零侵入现有服务 |
| **P1** | lotto 开奖 + 每日摘要钩子（`_refresh_worker` 两处 + 收 `run_pipeline` 返回值） | `yc/server/app.py`、`yc/src/run_all.py` |
| **P2** | saiOS 生图钩子（`task_runner.py` 两终态 + `notify_event` 工具 + `config.py` 加字段） | `apps/api/app/services/task_runner.py`、`app/core/config.py` |
| **P3** | Clash 代理故障探测 + 告警状态机（通知服务内） | `notify/notify.py` |
| **P4（可选）** | Telegram 渠道、writers/searxng 探活、死信汇总 | `notify/` |

每阶段独立可上线、可回滚，P0 无任何现有服务风险。

---

## 附：关键源码锚点（便于实施时定位）

| 文件 | 行号 | 用途 |
|---|---|---|
| `yc/server/app.py` | L48–61 `_refresh_worker`、L74–85 `_daily_scheduler` | 开奖完成/失败钩子 |
| `yc/src/run_all.py` | L118 `run_pipeline`、L159 `write_summary` | 摘要来源 + 返回 payload |
| `yc/src/lotto/ledger.py` | L74 `settle_and_record` | 预测留痕/中奖核对（可作「预测命中」事件源） |
| `apps/api/app/services/task_runner.py` | L714 `succeeded`、L776 `failed` | 生图成功/失败钩子 |
| `apps/api/app/core/config.py` | `Settings`（pydantic-settings） | 加 `NOTIFY_*` 配置字段 |
| `deploy/yuncai-site/nginx-yuncai.conf` | L379–385 `/clash/api/` | Clash API 反代（Bearer 注入），探测可直连 9090 |
