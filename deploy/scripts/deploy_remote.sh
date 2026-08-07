#!/usr/bin/env bash
# 混合部署同步：本机 → 117 服务器（rsync + 远端 migrate/restart/smoke）
# 用法：
#   bash deploy/scripts/deploy_remote.sh
#   bash deploy/scripts/deploy_remote.sh --skip-web
#   REMOTE=root@117.72.89.27 bash deploy/scripts/deploy_remote.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${REMOTE:-root@117.72.89.27}"
REMOTE_DIR="${REMOTE_DIR:-/opt/aigc-studio}"
SKIP_WEB=0
SKIP_TEST=0

for arg in "$@"; do
  case "$arg" in
    --skip-web) SKIP_WEB=1 ;;
    --skip-test) SKIP_TEST=1 ;;
    -h|--help)
      echo "Usage: $0 [--skip-web] [--skip-test]"
      exit 0
      ;;
  esac
done

echo "==> root: $ROOT"
echo "==> remote: $REMOTE:$REMOTE_DIR"

if [[ "$SKIP_TEST" -eq 0 ]]; then
  echo "==> local api tests"
  (
    cd "$ROOT/apps/api"
    if [[ -x .venv/Scripts/python.exe ]]; then
      .venv/Scripts/python.exe -m pytest -q
    elif [[ -x .venv/bin/python ]]; then
      .venv/bin/python -m pytest -q
    else
      echo "warn: no local venv, skip pytest (use --skip-test to silence)"
    fi
  )
fi

RSYNC_EXCLUDES=(
  --exclude '.venv'
  --exclude 'node_modules'
  --exclude '__pycache__'
  --exclude '.pytest_cache'
  --exclude '.ruff_cache'
  --exclude 'storage'
  --exclude 'aigc_studio.db'
  --exclude 'dist'
  --exclude 'web-dist'
  --exclude '.env'
  --exclude '.git'
  --exclude '*.pyc'
  --exclude '.ace-tool'
)

echo "==> rsync code"
rsync -az --delete \
  "${RSYNC_EXCLUDES[@]}" \
  "$ROOT/apps" "$ROOT/packages" "$ROOT/deploy" \
  "$ROOT/compose.yaml" "$ROOT/compose.prod.yaml" "$ROOT/compose.dev.yaml" \
  "$ROOT/Makefile" "$ROOT/package.json" "$ROOT/pnpm-workspace.yaml" \
  "$ROOT/.env.example" \
  "$REMOTE:$REMOTE_DIR/"

if [[ "$SKIP_WEB" -eq 0 ]]; then
  echo "==> build web"
  (
    cd "$ROOT"
    if command -v pnpm >/dev/null 2>&1; then
      pnpm --filter @aigc/web build
    else
      echo "error: pnpm not found; pass --skip-web or install pnpm"
      exit 1
    fi
  )
  WEB_DIST="$ROOT/apps/web/dist"
  if [[ ! -d "$WEB_DIST" ]]; then
    echo "error: web dist missing at $WEB_DIST"
    exit 1
  fi
  echo "==> rsync web dist"
  ssh "$REMOTE" "mkdir -p $REMOTE_DIR/web-dist && rm -rf $REMOTE_DIR/web-dist/dist.bak-latest && \
    if [ -d $REMOTE_DIR/web-dist/dist ]; then mv $REMOTE_DIR/web-dist/dist $REMOTE_DIR/web-dist/dist.bak-latest; fi"
  rsync -az --delete "$WEB_DIST/" "$REMOTE:$REMOTE_DIR/web-dist/dist/"
fi

echo "==> remote migrate + restart + smoke"
ssh "$REMOTE" "bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
cd /opt/aigc-studio/apps/api
export PYTHONPATH=/opt/aigc-studio/apps/api
# 缩短 binlog 保留，降低磁盘再次写满风险（30天→3天）
docker exec aigc-mysql mysql -uroot -paigc2026 -e \
  "SET PERSIST binlog_expire_logs_seconds=259200; PURGE BINARY LOGS BEFORE NOW() - INTERVAL 2 DAY;" \
  2>/dev/null || true

if [[ -x .venv/bin/alembic ]]; then
  # Alembic 走 env.py 读取 DATABASE_URL；systemd 单元的覆盖不会进 ssh 环境，
  # 所以显式注入与线上 aigc-api.service 一致的 MySQL 地址，避免误连本地 sqlite。
  if [[ -z "${DATABASE_URL:-}" ]]; then
    export DATABASE_URL="mysql+aiomysql://aigc:aigc2026@127.0.0.1:13306/aigc_studio"
  fi
  .venv/bin/alembic upgrade head
else
  echo "warn: alembic missing in venv"
fi

systemctl restart aigc-api
sleep 2
systemctl is-active aigc-api

# nginx 健康别名（幂等）
if [[ -f /etc/nginx/sites-available/aigc-studio ]]; then
  if ! grep -q 'api/v1/health/live' /etc/nginx/sites-available/aigc-studio; then
    cat > /etc/nginx/sites-available/aigc-studio <<'NGINX'
server {
    listen 5000;
    server_name _;
    root /opt/aigc-studio/web-dist/dist;
    index index.html;

    client_max_body_size 50m;

    location /api/ {
        proxy_pass http://127.0.0.1:8800/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location = /health {
        proxy_pass http://127.0.0.1:8800/api/v1/health/live;
    }
    location = /health/live {
        proxy_pass http://127.0.0.1:8800/api/v1/health/live;
    }
    location = /health/ready {
        proxy_pass http://127.0.0.1:8800/api/v1/health/ready;
    }
    location /healthz {
        proxy_pass http://127.0.0.1:8800/healthz;
    }

    # 私有媒体禁止 nginx 直出：统一走 /api/v1/assets/{id}/content（应用内鉴权）。
    # location /storage/ {
    #     alias /opt/aigc-studio/storage/;
    #     deny all;
    # }

    location / {
        try_files $uri $uri/ /index.html;
    }

    add_header X-Content-Type-Options "nosniff";
    add_header X-Frame-Options "SAMEORIGIN";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
}
NGINX
    ln -sfn /etc/nginx/sites-available/aigc-studio /etc/nginx/sites-enabled/aigc-studio
    nginx -t && systemctl reload nginx
  fi
fi

echo "-- smoke --"
curl -sf http://127.0.0.1:8800/api/v1/health/live | head -c 200; echo
curl -sf http://127.0.0.1:8800/api/v1/health/ready | head -c 400; echo
curl -sf http://127.0.0.1:5000/healthz | head -c 200; echo
curl -sf http://127.0.0.1:5000/api/v1/health/live | head -c 200; echo
TOKEN=$(curl -sf -X POST http://127.0.0.1:8800/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" || true)
if [[ -n "${TOKEN:-}" ]]; then
  curl -sf http://127.0.0.1:8800/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | head -c 300; echo
  curl -sf "http://127.0.0.1:8800/api/v1/prompts/?page=1&page_size=1" -H "Authorization: Bearer $TOKEN" | head -c 200; echo
  echo "login/me/prompts OK"
else
  echo "warn: login smoke failed"
  exit 1
fi
df -h / | tail -1
echo "deploy OK"
REMOTE_SCRIPT

echo "==> all done"
