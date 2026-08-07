# 生产部署清单（上线前逐项核对）

> 服务器目标：`117.72.89.27`（systemd 混合部署）或任意 compose 主机。
> 执行入口：`bash deploy/scripts/deploy_remote.sh`（rsync 同步 + 远端 migrate/restart/smoke）。

## 1. 安全基线（必须）

- [ ] `.env` 配置强随机 `JWT_SECRET_KEY` / `APP_SECRET_KEY`（≥32 位随机），**禁用** `dev-*` 与 `change-me` 占位符
  - 生产启动校验已生效：默认密钥直接拒绝启动（`APP_ENV=production`）
- [ ] 修改初始管理员密码（当前 `admin123`），部署后登录改密
- [ ] `deploy_remote.sh` 内硬编码的 MySQL 密码（`aigc2026`）改为从服务器私有文件读取
- [ ] `TRUST_PROXY=true`（nginx 反代场景），确认 nginx 覆盖客户端 XFF

## 2. 传输与暴露面

- [ ] **TLS**：nginx 配置 443 + Let's Encrypt（certbot），HTTP 301 跳转 HTTPS，加 HSTS
  - `.env` 的 `APP_BASE_URL` / `CORS_ALLOWED_ORIGINS` 同步改 `https://`
- [ ] 确认 nginx 无 `/storage/` 公开直出（已注释，私有媒体走鉴权接口）
- [ ] MySQL/Redis 端口仅绑定 127.0.0.1（compose 场景）或防火墙限制

## 3. 数据

- [ ] 部署 `deploy/systemd/aigc-backup.service` + `.timer`（每日 03:30）
  - 或 compose 场景在宿主机 cron 执行 `deploy/scripts/backup.sh`
- [ ] 首次备份 + 恢复演练（`mysql.sql.gz` 能成功导入）

## 4. 应用配置

- [ ] `DATABASE_URL` 指向 MySQL（生产不建议 SQLite）
- [ ] `STORAGE_PROVIDER=local` 或 `r2`（R2 需配 `STORAGE_*` 凭据）
- [ ] 模型 Provider：`OPENAI_COMPATIBLE_BASE_URL` 指向本机 grok2api/cpa（或管理端已注册）
- [ ] `USER_STORAGE_QUOTA_BYTES` 按需开启（0=不限）
- [ ] `APP_DEBUG=false`（自动关闭 /docs、SQL echo）

## 5. 部署步骤

### compose 架构（新服务器，推荐）

```bash
# 上传代码后，一键引导：生成强密钥 → 构建启动 → smoke → 装每日备份 cron
bash deploy/scripts/setup_prod.sh

# 后续更新
git pull  # 或 rsync 同步
docker compose up -d --build
```

### systemd 混合架构（旧服务器）

```bash
# 本机：测试 + lint 通过后同步
make test && make lint
bash deploy/scripts/deploy_remote.sh

# 服务器：核对清单 1-4 后
systemctl daemon-reload
systemctl enable --now aigc-backup.timer
systemctl restart aigc-api
bash /opt/aigc-studio/deploy/scripts/smoke.sh   # 冒烟（含登录）
```

## 5.1 本地 SQLite → 服务器 MySQL 数据迁移（可选）

本地开发数据在 SQLite，服务器用 MySQL；`apps/api/scripts/migrate_sqlite_to_mysql.py` 可全量搬迁：

```bash
cd apps/api && .venv/bin/python scripts/migrate_sqlite_to_mysql.py \
  --mysql-url "mysql+aiomysql://aigc:密码@服务器IP:3306/aigc_studio"
```

脚本会先 `alembic upgrade head` 建表，再逐表导入（幂等保护：目标库已有数据即中止）。

## 5.2 部署已知坑（均已修复，改配置时勿回退）

- `API_INTERNAL_PORT` 不要用 8000（与 grok2api 冲突）——默认 8002
- compose 的 api/worker 必须注入 `DATABASE_URL`（指向 `mysql` 服务名），否则容器内悄悄用空 SQLite
- 必须保留 `.dockerignore`（排除 node_modules）：Windows 的 node_modules 是符号链接，拷进 Linux 容器会破坏依赖
- API 镜像用 `python:3.14-slim`（代码依赖 PEP 649 延迟注解求值，3.12 会启动失败）
- 容器内访问宿主机 grok2api/cpa：Provider base_url 用 `http://host.docker.internal:8000/v1`（compose 已配 `extra_hosts`）
- MySQL 拒绝 `TEXT 列 DEFAULT ''`：迁移文件已去掉该 server_default

## 6. 上线后验证

- [ ] `curl https://<host>/api/v1/health/live` 200
- [ ] 登录 → 文本生成（GPT/Grok）→ 图片生成（Grok）真实出图
- [ ] 管理端「运行日志」能看到 Provider 调用记录
- [ ] 备份目录出现当日备份文件
