#!/usr/bin/env bash
# AIGC Studio 云服务器一键部署脚本（Ubuntu 24.04 + Docker Compose）
# 用法：
#   1. 上传代码到服务器：rsync -av --exclude={.git,node_modules,*.log,.env,backups} ./ user@server:/opt/aigc-studio/
#   2. 上传外部服务配置目录：rsync -av ~/.meituan-catpaw/*/grok-register/ user@server:/opt/aigc-studio/deploy/cloud/grok-register/
#   3. ssh 登录服务器执行：cd /opt/aigc-studio/deploy/cloud && bash deploy.sh your-domain.com
set -euo pipefail

DOMAIN="${1:-aigc.example.com}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "==> [1/5] 检查 Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "    安装 Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || { echo "需要 Docker Compose v2"; exit 1; }

echo "==> [2/5] 准备 .env"
if [ ! -f .env ]; then
  cp .env.cloud.example .env
  echo "    ⚠️  已生成 .env，请先编辑填写密钥（MYSQL/Redis/APP_SECRET/JWT/API_KEY/TDAI_MEMORY_API_KEY）"
  echo "    完成后重新运行本脚本"
  exit 1
fi
# 校验必填项
for key in MYSQL_PASSWORD MYSQL_ROOT_PASSWORD REDIS_PASSWORD APP_SECRET_KEY JWT_SECRET_KEY INITIAL_ADMIN_PASSWORD TDAI_MEMORY_API_KEY OPENAI_COMPATIBLE_API_KEY; do
  val="$(grep -E "^${key}=" .env | head -1 | cut -d= -f2-)"
  if [ -z "$val" ] || [[ "$val" == *"改我"* ]]; then
    echo "    ❌ .env 缺少 $key（或仍是占位符）"
    exit 1
  fi
done

echo "==> [3/5] 域名与 Caddyfile"
if [ "$DOMAIN" != "aigc.example.com" ]; then
  sed -i "s/^aigc\.example\.com/$DOMAIN/" Caddyfile
  sed -i "s|^APP_BASE_URL=.*|APP_BASE_URL=https://$DOMAIN|" .env
  sed -i "s|^CORS_ALLOWED_ORIGINS=.*|CORS_ALLOWED_ORIGINS=https://$DOMAIN|" .env
fi

echo "==> [4/5] 外部服务配置目录检查"
if [ ! -d grok-register ] || [ ! -f grok-register/grok2api/config.yaml ]; then
  echo "    ⚠️  未找到 grok-register/ 配置目录（grok2api/注册机/cpa 会启动失败）"
  echo "    请上传：rsync -av ~/.meituan-catpaw/*/grok-register/ ./grok-register/"
  echo "    继续启动平台核心..."
fi

echo "==> [5/5] 构建并启动"
docker compose -f compose.cloud.yaml up -d --build

echo ""
echo "✅ 部署完成：https://$DOMAIN"
echo "   平台健康检查：curl https://$DOMAIN/api/v1/health/ready"
echo "   首次启动：api 容器会自动执行 alembic 迁移并创建管理员（.env 的 INITIAL_ADMIN_*）"
echo "   查看日志：docker compose -f compose.cloud.yaml logs -f api"
