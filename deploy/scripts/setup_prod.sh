#!/usr/bin/env bash
# 生产首次部署引导（compose 架构，新服务器入口）。
# 用法（服务器上，项目目录内）：
#   bash deploy/scripts/setup_prod.sh
#
# 做的事情：
#   1. .env 不存在时从 .env.example 创建
#   2. 自动生成强随机密钥/密码（仅替换占位符，不覆盖已配置值）
#   3. docker compose up -d --build 全栈启动
#   4. smoke 验证（健康检查 + 管理员登录）
#   5. 安装每日备份 cron（docker exec mysqldump）
# 后续（手动）：TLS 见 docs/deployment-checklist.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ENV_FILE="${ROOT}/.env"

echo "==> AIGC Studio 生产部署引导 (root: ${ROOT})"

# ── 1. .env ─────────────────────────────────────────────────────────
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "==> 创建 .env（从 .env.example）"
  cp .env.example "${ENV_FILE}"
else
  echo "==> .env 已存在，保留现有配置"
fi

# ── 2. 强随机密钥（仅替换占位符）────────────────────────────────────
gen_hex() { openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

GEN_ADMIN_PASS=""
for KEY in APP_SECRET_KEY JWT_SECRET_KEY INITIAL_ADMIN_PASSWORD MYSQL_PASSWORD MYSQL_ROOT_PASSWORD; do
  CUR="$(grep -E "^${KEY}=" "${ENV_FILE}" | cut -d= -f2- || true)"
  if [[ "${CUR}" == "change-me"* || "${CUR}" == "changeme"* || "${CUR}" == "dev-"* || -z "${CUR}" ]]; then
    NEW="$(gen_hex)"
    if [[ "${KEY}" == "INITIAL_ADMIN_PASSWORD" ]]; then
      GEN_ADMIN_PASS="${NEW}"
    fi
    # macOS sed 与 GNU sed 语法差异
    if [[ "$(uname)" == "Darwin" ]]; then
      sed -i '' "s|^${KEY}=.*|${KEY}=${NEW}|" "${ENV_FILE}"
    else
      sed -i "s|^${KEY}=.*|${KEY}=${NEW}|" "${ENV_FILE}"
    fi
    echo "  ${KEY}: 已生成强随机值"
  else
    echo "  ${KEY}: 使用现有值"
  fi
done

if [[ -n "${GEN_ADMIN_PASS}" ]]; then
  echo ""
  echo "!! 初始管理员密码已生成（仅显示这一次，请立即保存）:"
  echo "    ${GEN_ADMIN_PASS}"
  echo "!! 用户名: $(grep -E '^INITIAL_ADMIN_USERNAME=' "${ENV_FILE}" | cut -d= -f2-)"
  echo ""
fi

# ── 3. 检查 Docker ──────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  echo "error: 未安装 docker（Ubuntu: apt install docker.io docker-compose-plugin）" >&2
  exit 1
fi
docker compose version >/dev/null 2>&1 || {
  echo "error: 未安装 compose 插件" >&2
  exit 1
}

# ── 4. 构建并启动 ───────────────────────────────────────────────────
echo "==> docker compose up -d --build（首次构建约 5-10 分钟）"
docker compose up -d --build

# ── 5. smoke 验证 ───────────────────────────────────────────────────
echo "==> 等待服务健康"
API_PORT="$(grep -E '^API_INTERNAL_PORT=' "${ENV_FILE}" | cut -d= -f2- || echo 8002)"
for i in $(seq 1 60); do
  if curl -sf -m 3 "http://127.0.0.1:${API_PORT}/api/v1/health/live" >/dev/null 2>&1; then
    break
  fi
  sleep 2
  [[ "$i" == 60 ]] && { echo "error: API ${API_PORT} 未在超时内就绪" >&2; exit 1; }
done
echo "  API live: OK (127.0.0.1:${API_PORT})"

ADMIN_USER="$(grep -E '^INITIAL_ADMIN_USERNAME=' "${ENV_FILE}" | cut -d= -f2-)"
ADMIN_PASS="$(grep -E '^INITIAL_ADMIN_PASSWORD=' "${ENV_FILE}" | cut -d= -f2-)"
LOGIN_CODE="$(curl -s -m 10 -o /dev/null -w '%{http_code}' -X POST \
  "http://127.0.0.1:${API_PORT}/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}")"
if [[ "${LOGIN_CODE}" == "200" ]]; then
  echo "  管理员登录: OK"
else
  echo "warn: 登录返回 ${LOGIN_CODE}（初始密码可能已被改，可忽略）"
fi

echo "  前端: http://127.0.0.1:$(grep -E '^FRONTEND_PORT=' "${ENV_FILE}" | cut -d= -f2- || echo 5000)"

# ── 6. 每日备份 cron ───────────────────────────────────────────────
MYSQL_CONTAINER="$(docker compose ps -q mysql 2>/dev/null || true)"
if [[ -n "${MYSQL_CONTAINER}" ]]; then
  CRON_LINE="30 3 * * * cd ${ROOT} && DOCKER_MYSQL=${MYSQL_CONTAINER} REMOTE_DIR=${ROOT} bash deploy/scripts/backup.sh >> ${ROOT}/backups/backup.log 2>&1"
  if crontab -l 2>/dev/null | grep -qF "deploy/scripts/backup.sh"; then
    echo "  备份 cron 已存在，跳过"
  else
    ( crontab -l 2>/dev/null; echo "${CRON_LINE}" ) | crontab -
    echo "  已安装每日 03:30 备份 cron（保留 14 份）"
  fi
else
  echo "warn: 未找到 mysql 容器，跳过备份 cron（请手工配置）"
fi

echo ""
echo "==> 部署完成"
echo "   下一步（可选）：TLS 与安全基线见 docs/deployment-checklist.md"
