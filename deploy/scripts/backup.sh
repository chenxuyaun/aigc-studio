#!/usr/bin/env bash
# AIGC Studio 数据库 + 媒体备份（服务器上由 cron/systemd timer 每天执行）。
# 用法：
#   REMOTE_DIR=/opt/aigc-studio bash deploy/scripts/backup.sh
#   DOCKER_MYSQL=aigc-studio-mysql-1 REMOTE_DIR=/opt/aigc-studio bash deploy/scripts/backup.sh
# 说明：
#   - MySQL 凭据从 ${REMOTE_DIR}/.env 读取（MYSQL_USER/MYSQL_PASSWORD/MYSQL_DATABASE）
#   - 设置 DOCKER_MYSQL 时用 docker exec mysqldump（compose 部署，宿主机无需 mysqldump）
#   - SQLite 部署直接拷贝 apps/api/aigc_studio.db
#   - 保留最近 14 份，历史自动清理
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE_DIR="${REMOTE_DIR:-/opt/aigc-studio}"
BACKUP_ROOT="${BACKUP_ROOT:-${REMOTE_DIR}/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="${BACKUP_ROOT}/${STAMP}"

ENV_FILE="${REMOTE_DIR}/.env"

echo "==> backup to ${DEST}"

if [[ ! -d "${REMOTE_DIR}" ]]; then
  echo "!! REMOTE_DIR 不存在: ${REMOTE_DIR}" >&2
  exit 1
fi

mkdir -p "${DEST}"

# 1) SQLite 部署：直接拷贝 db 文件
DB_FILE="${REMOTE_DIR}/apps/api/aigc_studio.db"
if [[ -f "${DB_FILE}" ]]; then
  echo "==> backing up sqlite db"
  cp "${DB_FILE}" "${DEST}/aigc_studio.db"
fi

# 2) MySQL 部署：mysqldump（宿主机客户端 或 DOCKER_MYSQL 容器）
if [[ -f "${ENV_FILE}" ]]; then
  MYSQL_DATABASE="$(grep -E '^MYSQL_DATABASE=' "${ENV_FILE}" | cut -d= -f2- | tr -d '"')"
  MYSQL_USER="$(grep -E '^MYSQL_USER=' "${ENV_FILE}" | cut -d= -f2- | tr -d '"')"
  MYSQL_PASSWORD="$(grep -E '^MYSQL_PASSWORD=' "${ENV_FILE}" | cut -d= -f2- | tr -d '"')"
  if [[ -n "${MYSQL_DATABASE:-}" && -n "${MYSQL_USER:-}" && -n "${MYSQL_PASSWORD:-}" ]]; then
    echo "==> backing up mysql database ${MYSQL_DATABASE}"
    if [[ -n "${DOCKER_MYSQL:-}" ]]; then
      docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" "${DOCKER_MYSQL}" \
        mysqldump --single-transaction --quick \
        -u "${MYSQL_USER}" "${MYSQL_DATABASE}" \
        > "${DEST}/mysql.sql" 2>/dev/null \
        || { echo "!! mysqldump(容器) 失败" >&2; rm -f "${DEST}/mysql.sql"; }
    elif command -v mysqldump >/dev/null 2>&1; then
      MYSQL_PWD="${MYSQL_PASSWORD}" mysqldump \
        --single-transaction --quick \
        -u "${MYSQL_USER}" "${MYSQL_DATABASE}" \
        > "${DEST}/mysql.sql" 2>/dev/null \
        || { echo "!! mysqldump 失败" >&2; rm -f "${DEST}/mysql.sql"; }
    else
      echo "warn: 无 mysqldump 且未设置 DOCKER_MYSQL，跳过 MySQL 备份"
    fi
    if [[ -f "${DEST}/mysql.sql" ]]; then
      gzip -f "${DEST}/mysql.sql"
    fi
  fi
fi

# 3) 媒体存储目录
STORAGE_DIR="${REMOTE_DIR}/apps/api/storage"
if [[ -d "${STORAGE_DIR}" ]]; then
  echo "==> backing up storage"
  tar -czf "${DEST}/storage.tar.gz" -C "$(dirname "${STORAGE_DIR}")" "$(basename "${STORAGE_DIR}")"
fi

# 4) 清理过期备份
echo "==> pruning backups older than ${KEEP_DAYS} days"
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${KEEP_DAYS}" -exec rm -rf {} +

echo "==> backup complete: ${DEST}"
ls -lh "${DEST}"
