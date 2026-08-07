#!/usr/bin/env bash
# 备份恢复演练：把最近一次备份恢复到临时库，校验关键表行数与源库一致后清理。
# 用法: bash deploy/scripts/restore_drill.sh
# 说明：
#   - 临时库名 aigc_studio_drill_<stamp>，演练结束自动删除
#   - 校验表：users / story_projects / agentlist_projects / agentlist_articles / generation_tasks
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_ROOT="${ROOT}/backups"
DOCKER_MYSQL="${DOCKER_MYSQL:-aigc-studio-mysql-1}"
SRC_DB="${MYSQL_DATABASE:-aigc_studio}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DRILL_DB="aigc_studio_drill_${STAMP}"
PASS=0
FAIL=0

# 1) 找最近备份
LATEST="$(ls -1dt "${BACKUP_ROOT}"/20* 2>/dev/null | head -1 || true)"
if [[ -z "${LATEST}" || ! -f "${LATEST}/mysql.sql.gz" ]]; then
  echo "!! 未找到备份 (${BACKUP_ROOT}/20*)"
  exit 1
fi
echo "==> 使用备份: ${LATEST}/mysql.sql.gz"

MYSQL_PWD="$(grep -E '^MYSQL_ROOT_PASSWORD=' "${ROOT}/.env" | cut -d= -f2- | tr -d '"')"
mysql_exec() { docker exec -e MYSQL_PWD="${MYSQL_PWD}" "${DOCKER_MYSQL}" mysql -uroot "$@"; }

# 2) 建临时库并恢复
echo "==> 创建临时库 ${DRILL_DB}"
mysql_exec -e "CREATE DATABASE ${DRILL_DB} CHARACTER SET utf8mb4;"
echo "==> 恢复 dump"
if ! gunzip -c "${LATEST}/mysql.sql.gz" | docker exec -i -e MYSQL_PWD="${MYSQL_PWD}" "${DOCKER_MYSQL}" mysql -uroot "${DRILL_DB}"; then
  echo "!! 恢复失败"
  mysql_exec -e "DROP DATABASE ${DRILL_DB};" || true
  exit 1
fi

# 3) 校验关键表行数（临时库 vs 源库）
check_table() {
  local t="$1"
  local src drill
  src="$(mysql_exec -N -e "SELECT COUNT(*) FROM ${SRC_DB}.${t};" 2>/dev/null || echo "N/A")"
  drill="$(mysql_exec -N -e "SELECT COUNT(*) FROM ${DRILL_DB}.${t};" 2>/dev/null || echo "N/A")"
  if [[ "${src}" == "${drill}" && "${src}" != "N/A" ]]; then
    echo "  PASS ${t}: ${src} 行"
    PASS=$((PASS + 1))
  else
    echo "  FAIL ${t}: 源=${src} 恢复=${drill}"
    FAIL=$((FAIL + 1))
  fi
}

echo "==> 校验行数"
for t in users story_projects agentlist_projects agentlist_articles generation_tasks workflow_favorites; do
  check_table "${t}"
done

# 4) 清理临时库
echo "==> 清理临时库"
mysql_exec -e "DROP DATABASE ${DRILL_DB};"

echo ""
echo "== 恢复演练: ${PASS} passed, ${FAIL} failed =="
exit $((FAIL > 0 ? 1 : 0))
