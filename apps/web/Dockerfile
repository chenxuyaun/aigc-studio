FROM node:24-slim AS builder
WORKDIR /app

# workspace 依赖（@aigc/shared-types 等）必须在构建上下文内：复制 workspace 清单 + packages
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY packages/ packages/
COPY apps/web/package.json apps/web/

RUN npm install -g pnpm && pnpm install --frozen-lockfile

COPY apps/web/ apps/web/
RUN pnpm --filter @aigc/web build

FROM nginx:alpine
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html
COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
# 启动前等 api 就绪，避免 nginx 抢先于 uvicorn → 登录 502（详见 deploy/nginx/wait-for-api.sh）
COPY deploy/nginx/wait-for-api.sh /wait-for-api.sh
RUN chmod +x /wait-for-api.sh
EXPOSE 80
CMD ["/wait-for-api.sh"]
