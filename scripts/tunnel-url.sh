#!/usr/bin/env bash
# 查询当前 cpolar 公网隧道域名（免费版随机域名，重启/重启容器后可能变化）
# 用法：scripts/tunnel-url.sh
set -euo pipefail

if ! docker ps --format '{{.Names}}' | grep -q '^cpolar-tunnel$'; then
  echo "cpolar-tunnel 未运行。启动：docker start cpolar-tunnel" >&2
  exit 1
fi

URL=$(docker exec cpolar-tunnel sh -c \
  'wget -q -O- --timeout=8 http://127.0.0.1:4040/ 2>/dev/null' \
  | grep -oE 'https?://[a-z0-9]+\.r[0-9]+\.cpolar\.[a-z]+' \
  | sort -u | head -1)

if [ -z "$URL" ]; then
  echo "未获取到隧道地址（inspect 面板可能未就绪，稍后重试）" >&2
  exit 1
fi

echo "$URL"
# 顺带验证公网可达
curl -s -o /dev/null -m 15 -w "可达性: %{http_code}\n" "$URL/" || true
