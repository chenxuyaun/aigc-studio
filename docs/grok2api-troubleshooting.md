# grok2api / cpa 上游排障手册

> 维护：2026-08-01（基于真实故障排查过程整理）
> 适用：AIGC Studio 本地 docker 部署（API 容器 → 宿主机 grok2api / cpa）
> **重要**：grok2api 只有本地实例（localhost:8000）。曾有一个远程 grok2api（117.72.89.27:8000，1000+ 账号的推送目标）——**已废弃，不存在云服务器**，勿再引用。

## 1. 架构速览

| 服务 | 容器 | 端口 | 模型 | 用途 |
|---|---|---|---|---|
| grok2api | `grok2api` | 8000 | `grok-chat-fast`（文本）、`grok-imagine-image`（图片） | 图片/文本生成主链路 |
| cpa（cli-proxy-api） | `cli-proxy-api` | 8317 | `gpt-oss-120b-medium` 等 12 个（Codex/CLI 代理） | 文本备用/多模型 |
| FlareSolverr | `flaresolverr` | 8191 | — | 解 grok.com 的 Cloudflare 挑战 |

- AIGC API 容器通过 `host.docker.internal` 访问宿主机上的 grok2api/cpa
- grok2api/cpa 的凭据存于 AIGC `.env`（`OPENAI_COMPATIBLE_API_KEY` 等）与 AIGC 数据库 `provider_configs.encrypted_api_key`
- grok2api 数据在 **named volume** `grok2api_grok2api-data`（`/app/data`，含 backend.db 与账号库），配置挂载 `config.yaml → /run/grok2api/config.yaml`

## 2. 快速诊断（30 秒定位）

```bash
# 1) 服务是否在线
docker ps --filter name=grok2api --filter name=cli-proxy-api --filter name=flaresolverr

# 2) 模型列表（grok2api 需要客户端 API key，从 AIGC .env 取 OPENAI_COMPATIBLE_API_KEY）
curl -H "Authorization: Bearer $G2A_KEY" http://localhost:8000/v1/models
curl -H "Authorization: Bearer $CPA_KEY" http://localhost:8317/v1/models   # cpa 鉴权 key 在 provider_configs.encrypted_api_key

# 3) 最小 chat 探活（grok）
curl -H "Authorization: Bearer $G2A_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/chat/completions \
  -d '{"model":"grok-chat-fast","messages":[{"role":"user","content":"说：在"}],"max_tokens":10}'

# 4) 看 grok2api 最近日志（过滤噪音）
docker logs grok2api --since 5m 2>&1 | grep -v performance_metric
```

## 3. 错误码速查

| 现象 | 含义 | 处理 |
|---|---|---|
| `invalid_api_key` | grok2api 网关鉴权失败 | AIGC `.env` 的 key 与 grok2api 配置不一致；或容器数据卷挂错（backend.db 丢失） |
| `upstream_unavailable` / 503 | 上游 grok.com 调用失败 | 见第 4 节（CF 层 / 账号层二分排查） |
| `"Grok index 返回 403"` | CF 挑战未过 或 出口被风控 | CF 层问题：检查 FlareSolverr 接入 |
| `"Grok Session 接口返回 403"`（`account_initial_identity_sync_failed`） | 账号登录态被 grok.com 拒绝 | 账号层问题：cookie 过期/不全/小号被风控 |
| `Missing API key`（cpa） | cpa 未带鉴权 | 用 `provider_configs.encrypted_api_key` 解密后的 key |

## 4. 403 二分排查：CF 层 vs 账号层

**判据**：看 grok2api 日志里 `web_statsig_refreshed` 是否成功（`/rest/rate-limits`、`/rest/app-chat/conversations/new`）。

- `web_statsig_refreshed` 成功 → **CF 层已通**，问题在账号层（见 4.2）
- `web_statsig_fetch_failed "Grok index 返回 403"` → **CF 层未通**（见 4.1）

### 4.1 CF 层：接入 FlareSolverr

grok.com 对所有非浏览器请求做 Cloudflare 挑战；grok2api 默认 `proxy.clearance.mode = none`（完全不处理）。

```bash
# FlareSolverr 可用性验证（在 grok2api_default 网络内）
docker exec flaresolverr sh -c "curl -s -m 90 -X POST http://localhost:8191/v1 \
  -H 'Content-Type: application/json' \
  -d '{\"cmd\":\"request.get\",\"url\":\"https://grok.com/\",\"maxTimeout\":60000}'"
# 期望：{"status": "ok", "message": "Challenge solved!"}

# grok2api 容器注入 CF 环境变量（本仓库 compose 文件中 FLARESOLVERR_URL 行已注释说明；
# 容器实际由 docker run 管理，重建命令见第 5 节）
FLARESOLVERR_URL=http://flaresolverr:8191
CF_REFRESH_INTERVAL=600
CF_TIMEOUT=60
```

注意：**不要在 config.yaml 加 `proxy:` 顶层段** —— 本版本（ghcr.io/chenyme/grok2api）的 Go 配置结构没有该字段，会启动崩溃报 `field proxy not found in type config.Config`。CF 配置只能走环境变量。

### 4.2 账号层：登录态失效

`account_initial_identity_sync_failed ... "Grok Session 接口返回 403"` 表示导入的 cookie 快照被 grok.com 拒绝。

管理面板账号字段判读（`/api/admin/v1/accounts`，需 admin token）：

| 字段 | 含义 | 健康值 |
|---|---|---|
| `authStatus` | active = 管理面板视角可用 | `active` |
| `refreshable` | 是否有 refresh token 可续期；**false = SSO 一次性登录态，过期即废** | 期望 true；批量注册小号通常 false |
| `cloudflareCookieConfigured` | 是否绑定 cf_clearance | 期望 true |
| `quota.remaining` | 当日剩余配额 | > 0 |

处理：
1. 在浏览器登录 grok.com，确认**该账号浏览器里能正常聊天**（能 = cookie 抓取不全；不能 = 号已废）
2. F12 → Application → Cookies → 复制 grok.com 域名下**全部** cookie → grok2api 管理面板重新导入
3. 优先导入能刷新（`refreshable: true`）的主账号，而不是一次性小号

## 5. grok2api 容器重建（关键命令）

容器由 `docker run` 管理（**不要用该项目 docker-compose.yml 重建** —— 该 compose 不含 config.yaml 挂载，重建会丢失配置导致 crash loop）。

```bash
# 前置检查：确认原容器挂载（named volume + config.yaml）
docker inspect grok2api --format '{{json .HostConfig.Binds}}'

docker rm -f grok2api
MSYS_NO_PATHCONV=1 docker run -d --name grok2api \
  --network grok2api_default \
  -p 8000:8000 \
  -e TZ=Asia/Shanghai -e LOG_LEVEL=INFO -e SERVER_HOST=0.0.0.0 -e SERVER_PORT=8000 -e SERVER_WORKERS=1 \
  -e ACCOUNT_STORAGE=local -e ACCOUNT_LOCAL_PATH=data/accounts.db \
  -e ACCOUNT_REDIS_URL= -e ACCOUNT_MYSQL_URL= -e ACCOUNT_POSTGRESQL_URL= \
  -e FLARESOLVERR_URL=http://flaresolverr:8191 -e CF_REFRESH_INTERVAL=600 -e CF_TIMEOUT=60 \
  -e GROK2API_CONFIG_SOURCE=/run/grok2api/config.yaml \
  -v grok2api_grok2api-data:/app/data \
  -v "C:/Users/yuesh/.meituan-catpaw/5667331509/desk_default_workspace/grok-register/grok2api/config.yaml:/run/grok2api/config.yaml" \
  --restart unless-stopped \
  ghcr.io/chenyme/grok2api:latest
```

> **Git Bash 陷阱**：容器内路径（`/run/grok2api/config.yaml`）会被 MSYS 转成 `C:/Program Files/Git/...`，docker run/exec/cp 一律加 `MSYS_NO_PATHCONV=1`。
> **数据卷陷阱**：数据在 named volume `grok2api_grok2api-data`，误挂成目录（如 `D:/.../grok2api/data`）会导致 backend.db 丢失 → API key 校验失败（`invalid_api_key`）。

## 6. 历史故障时间线（2026-08-01 实况）

1. 账号导入后 `account_initial_identity_sync_failed`（Session 403）+ `web_statsig_fetch_failed`（index 403）
2. 排查：curl 直连 grok.com 无鉴权不可比；管理 API 显示账号 `authStatus=active` 但 `refreshable=false`、`cloudflareCookieConfigured=false`
3. 修复 CF 层：注入 FlareSolverr 环境变量 + 重建容器 → statsig 全部转成功
4. 遗留：wdb.pub 批量小号登录态仍 403（cookie 快照被拒），需导入浏览器可用账号的完整 cookie

## 7. 相关文件

| 路径 | 说明 |
|---|---|
| `D:\software\code\ideas\list\grok2api\config.defaults.toml` | grok2api 默认配置（clearance 默认 none） |
| `...\grok-register\grok2api\config.yaml` | grok2api 运行时配置（挂载进容器），备份为 `config.yaml.bak-20260801` |
| `D:\software\code\ideas\list\grok2api\docker-compose.yml` | 官方 compose（不含 config.yaml 挂载，勿直接用于重建） |
| AIGC `.env` | `OPENAI_COMPATIBLE_API_KEY`（grok2api 客户端 key） |
| AIGC `provider_configs` 表 | grok2api/cpa 的 base_url、加密 key、默认模型 |

## 8. 注册机（grok-register-agent）故障排查

> 容器 `grok-register-agent`（:6657），SSO 注册链路。宿主机源码：`C:\Users\yuesh\.meituan-catpaw\5667331509\desk_default_workspace\grok-register\GrokRegisterAgent\register`（bind 到容器 `/opt/register-host`，容器重启时 entrypoint 自动 rsync 到 `/app/register`）。

### 8.1 症状：run 秒失败，日志停在"浏览器版本(启动前)"

- WebUI / `POST /api/run/start` 返回 runId，但 1 分钟内 `phase: error`、`success: 0`
- `/app/register/logs/run_*.log` 只有 3 行（日志文件/运行环境/浏览器版本），**无 traceback**（真异常走 stderr 进 WebUI job 日志，run_*.log 只记录 `_emit` 行，所以看起来"静默死亡"）
- 容器内直跑 `python3 -u DrissionPage_example.py --count 1` 能看到完整根因：
  `DrissionPage.errors.BrowserConnectError: 127.0.0.1:9222浏览器连接失败`（提示无界面系统需 `--no-sandbox`/`--headless`）

### 8.2 根因：Xvfb 死亡 + stale socket 误判（2026-08-01 实锤）

```
entrypoint 启动 Xvfb :99（仅容器启动时，后台进程，无守护）
        ↓ Xvfb 进程中途死亡（16:49 后某刻）
        ↓ /tmp/.X11-unix/X99 stale socket 残留 + /tmp/.X99-lock 残留
_display_is_usable(":99") 只 os.path.exists(socket) → 误判"可用"
        ↓ 脚本跳过 Xvfb 重启 → chromium 连不上 X server → 启动即崩
```

- 此前误以为是 "server spawn 差异/代理注入"，实际 spawn 参数完全正常，**问题在 DISPLAY 层**
- 容器 restart 不解决：`/tmp` 保留，entrypoint 起 Xvfb 时 `Server is already active for display 99`（stale lock），且 entrypoint 打印 `Xvfb ready` 前不校验进程是否真起来

### 8.3 修复（2026-08-01 已改宿主机源码）

`DrissionPage_example.py`：
1. `_display_is_usable()`：socket 文件存在 + **AF_UNIX connect 实测**（stale socket connect 必失败）
2. 新增 `_cleanup_stale_display_files()`：清理 `/tmp/.X*-lock` + `/tmp/.X11-unix/X*`
3. `_ensure_virtual_display()`：检测到 DISPLAY 不可用 → 先清 stale 再重建

自愈链路（无需人工）：Xvfb 死亡 → 下轮 run 模块 import 时实测失败 → 清 stale → 拉起 Xvfb → 正常注册。

### 8.4 手动急救命令

```bash
docker exec grok-register-agent sh -c "rm -f /tmp/.X99-lock /tmp/.X11-unix/X99; \
  nohup Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 & \
  sleep 1; ls /tmp/.X11-unix/"
```

### 8.5 C 档整合速览（2026-08-01 完成）

| 项 | 说明 |
|---|---|
| 统一编排 | 全部 10 容器 `restart: unless-stopped`（compose.yaml 修正：restart 放 image/build 之后） |
| 上游状态页 | AIGC `GET /api/v1/upstream/status` → 前端「上游状态」页（grok 池/注册机/grok 图片/cpa 4 卡片 + 立即注册按钮） |
| 注册批次调度 | `POST /api/v1/upstream/register` 建 `GenerationTask(type=register)` + 进程内调度；celery beat 每 4h 自动一批（`REGISTER_BATCH_INTERVAL_HOURS`/`COUNT`） |
| 账号健康 | celery beat 每 30min 检查，bad 账号（failureCount≥10 或 authStatus≠active）禁用 |
| 重启陷阱 | **代码改动必须 `docker compose build` 再 recreate**（restart/force-recreate 不重载代码） |
