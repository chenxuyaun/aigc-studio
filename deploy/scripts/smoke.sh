#!/usr/bin/env bash
# 线上冒烟：健康、登录、素材/任务/写真只读路径
# 用法：BASE=http://117.72.89.27:5000 bash deploy/scripts/smoke.sh
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:5000}"
USER_NAME="${SMOKE_USER:-admin}"
PASS="${SMOKE_PASS:-admin123}"

echo "smoke against $BASE"
curl -sf "$BASE/healthz" >/dev/null
curl -sf "$BASE/api/v1/health/live" >/dev/null
READY=$(curl -sf "$BASE/api/v1/health/ready" || true)
echo "ready: $READY"
echo "$READY" | grep -q '"status":"ready"'

TOKEN=$(curl -sf -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER_NAME\",\"password\":\"$PASS\"}" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
AUTH="Authorization: Bearer $TOKEN"

curl -sf "$BASE/api/v1/auth/me" -H "$AUTH" >/dev/null
curl -sf "$BASE/api/v1/prompts/?page=1&page_size=2" -H "$AUTH" >/dev/null
curl -sf "$BASE/api/v1/tasks/?page=1&page_size=2" -H "$AUTH" >/dev/null
curl -sf "$BASE/api/v1/assets/?page=1&page_size=2" -H "$AUTH" >/dev/null
curl -sf "$BASE/api/v1/photography/albums?page=1&page_size=2" -H "$AUTH" >/dev/null

# mock 图片任务
TASK=$(curl -sf -X POST "$BASE/api/v1/generations/image/generate" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"model":"mock","prompt":"smoke deploy","width":256,"height":256}')
TASK_ID=$(echo "$TASK" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "task=$TASK_ID"
for _ in $(seq 1 30); do
  BODY=$(curl -sf "$BASE/api/v1/tasks/$TASK_ID" -H "$AUTH")
  STATUS=$(echo "$BODY" | python -c "import sys,json; print(json.load(sys.stdin)['status'])")
  if [[ "$STATUS" == "succeeded" || "$STATUS" == "failed" ]]; then
    echo "task status=$STATUS"
    break
  fi
  sleep 0.3
done
[[ "$STATUS" == "succeeded" ]]

ASSET_ID=$(echo "$BODY" | python -c "import sys,json; print(json.loads(json.load(sys.stdin)['result'])['asset_id'])")
curl -sf "$BASE/api/v1/assets/$ASSET_ID/access-url" -H "$AUTH" >/dev/null
echo "smoke OK asset=$ASSET_ID"
