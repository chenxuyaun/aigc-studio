# AIGC Studio 云服务器部署指南

把本地 Windows + Docker Desktop 的整套环境迁移到公共云服务器（Ubuntu + Docker Compose），
**全新开始**（不迁移本地数据，云上重新初始化）。

## 一、服务器要求

| 项 | 建议 | 最低 |
|---|---|---|
| 系统 | Ubuntu 24.04 LTS | 22.04 |
| CPU/内存 | 4C 8G | 2C 4G |
| 磁盘 | 100G SSD | 50G（镜像 ~20G + 数据卷会涨） |
| 带宽 | 5Mbps+ | — |
| 域名 | 有（HTTPS 自动证书需要） | 无域名可先 HTTP |

安全组只开放：**22（SSH）、80、443**。其余端口（8000/6657/8317/8001 等）一律不开。

## 二、上传清单

```bash
# 1. 代码（排除 .env/日志/备份/临时文件）
rsync -av --exclude={.git,.zcode,node_modules,*.log,.env,backups,双城交换杀人*,雪山列车*,*.png,*.json,*.md} \
  ./ user@SERVER:/opt/aigc-studio/

# 2. 外部服务配置目录（grok2api/注册机/cpa 的配置文件，含密钥，勿进 git）
rsync -av ~/.meituan-catpaw/5667331509/desk_default_workspace/grok-register/ \
  user@SERVER:/opt/aigc-studio/deploy/cloud/grok-register/

# 3. SillyTavern 数据（可选，本地角色卡/会话在 MySQL，全新开始可跳过）
```

> 第 1 条里 `双城交换杀人*` 等是本地小说文件，按需保留。
> 注意 `node_modules`、`.env`、`backups/`、`TencentDB-Agent-Memory/`（仅构建参考）可不上传；
> `apps/web/pnpm-lock.yaml` 必须上传（构建依赖）。

## 三、部署步骤

```bash
ssh user@SERVER
cd /opt/aigc-studio/deploy/cloud

# 生成 .env 并填写全部密钥（MYSQL/Redis/APP_SECRET/JWT/管理员密码/grok key/TDAI key）
cp .env.cloud.example .env
vi .env          # 必改项见文件内注释；生成密钥：openssl rand -hex 32

# 一键部署（域名作为参数）
bash deploy.sh your-domain.com
```

脚本会：装 Docker → 校验 .env → 写入域名到 Caddyfile/.env → 构建启动全部服务。

## 四、启动后的检查

```bash
docker compose -f compose.cloud.yaml ps          # 全部 Up (healthy)
curl https://your-domain.com/api/v1/health/ready # {"status":"ready",...}
# 首次登录：.env 的 INITIAL_ADMIN_USERNAME/PASSWORD
# 记忆系统：POST /api/v1/memory/distill 触发一次蒸馏即验证 memory-core 链路
```

## 五、架构与端口说明

```
公网 → 安全组(22/80/443) → Caddy(自动 HTTPS) → frontend:80
                                        └→ /api/v1 → api:8000（nginx 代理）
容器内网互访：mysql/redis/api/worker/frontend/memory-core
外部服务（端口映射到宿主，云安全组不开放，仅容器内经 host.docker.internal 访问）：
  grok2api:8000（LLM 网关）  cpa:8317（gpt-oss）  注册机:6657  turnstile  flaresolverr
sillytavern:8001（浏览器直连，需要时安全组单独开放）
```

| 端口 | 用途 | 公网 |
|---|---|---|
| 80/443 | Caddy HTTPS | ✅ |
| 22 | SSH | ✅（建议改密钥登录） |
| 8001 | SillyTavern 界面 | 按需 |
| 8000/8317 | grok2api/cpa 模型网关 | ❌（安全组关闭） |
| 6657 等 | 注册机（本地运行） | 不上云 |

## 六、常见问题

- **grok2api 起不来**：`grok-register/grok2api/config.yaml` 未上传或格式不对 → 看日志
  `docker compose -f compose.cloud.yaml logs grok2api`
- **平台健康但登录失败**：api 容器可能因依赖未就绪没起来 → `docker compose logs api`
- **证书申请失败**：域名未解析到本机 IP / 80 端口被占用 → `docker compose logs caddy`
- **CORS 报错**：`.env` 的 `CORS_ALLOWED_ORIGINS` 与访问域名不一致
- **记忆系统不工作**：`TDAI_MEMORY_API_KEY` 与 `memory-core` 的 `TDAI_GATEWAY_API_KEY` 必须一致
- **Redis 密码变更**：改 `.env` 后 `docker compose -f compose.cloud.yaml up -d`（api/worker 自动拼接）

## 七、日常维护

```bash
# 备份（worker 每日 03:00 自动写 ./backups/，保留 14 天；建议加异地同步）
docker compose -f compose.cloud.yaml exec worker ls /app/backups/

# 更新代码后
rsync ... && cd deploy/cloud && docker compose -f compose.cloud.yaml up -d --build

# 磁盘清理（镜像重建会累积悬空）
docker image prune -a -f && docker builder prune -a -f
```
