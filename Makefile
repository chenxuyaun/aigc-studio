.PHONY: install dev build test lint format up down logs migrate seed smoke deploy remote-smoke

install:
	cd apps/web && npm install -g pnpm && pnpm install
	cd apps/api && pip install -e ".[dev]"

dev:
	cd apps/web && pnpm dev

build:
	cd apps/web && pnpm build

test:
	cd apps/web && pnpm test:run
	cd apps/api && python -m pytest

lint:
	cd apps/web && pnpm lint
	cd apps/api && ruff check .

format:
	cd apps/web && pnpm format
	cd apps/api && ruff format .

up:
	docker compose -f compose.yaml -f compose.prod.yaml up -d --build

down:
	docker compose -f compose.yaml -f compose.prod.yaml down

logs:
	docker compose logs -f

migrate:
	cd apps/api && alembic upgrade head

seed:
	cd apps/api && python -m seed_data

smoke:
	bash deploy/scripts/smoke.sh

remote-smoke:
	BASE=http://117.72.89.27:5000 bash deploy/scripts/smoke.sh

# 同步代码+前端到 117 并重启 aigc-api
deploy:
	bash deploy/scripts/deploy_remote.sh

deploy-api:
	bash deploy/scripts/deploy_remote.sh --skip-web
