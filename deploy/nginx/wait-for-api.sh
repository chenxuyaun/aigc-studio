#!/bin/sh
# 等 api 就绪再启动 nginx。
#
# 背景：compose 的 depends_on: condition: service_healthy 只在容器「创建」时生效；
# 容器「重启 / docker start / Docker Desktop 重启」会跳过排序，导致 nginx 抢先于
# uvicorn 启动 —— 首个登录请求撞上 api 还没监听端口 → connect() failed (111) → 502。
# 这里在容器内轮询 api 健康，保证任何启动方式下 nginx 都不会抢跑。
set -e

echo "[frontend] waiting for api to become ready..."
i=0
until wget -q -O /dev/null http://api:8000/api/v1/health/live 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 120 ]; then
    echo "[frontend] api still not ready after 120s; starting nginx anyway"
    break
  fi
  sleep 1
done

echo "[frontend] api ready; starting nginx"
exec nginx -g "daemon off;"
