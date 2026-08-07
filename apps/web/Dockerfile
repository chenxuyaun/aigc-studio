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
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
