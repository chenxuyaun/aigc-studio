"""每日自动备份任务（beat 02:00）：纯 Python 逻辑备份（pymysql 直出标准 SQL）
+ storage tar 到 /app/backups（host 挂载），保留 14 天。

不依赖 mysqldump 客户端：逐表 SHOW CREATE TABLE + SELECT 生成标准 SQL，
host 侧 mysql 客户端（restore_drill.sh）可直接执行恢复。
"""

from __future__ import annotations

import gzip
import io
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pymysql

from app.core.config import settings
from app.tasks.celery_app import celery_app
from app.tasks.generation_tasks import _RETRYABLE

BACKUP_ROOT = Path("/app/backups")
KEEP_DAYS = 14


def _sql_escape(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def _dump_database() -> bytes:
    """全库逻辑备份 → 标准 SQL bytes（含建表 + 数据）。"""
    conn = pymysql.connect(
        host="mysql",
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset="utf8mb4",
        connect_timeout=15,
    )
    buf = io.StringIO()
    try:
        with conn.cursor() as cur:
            cur.execute("SET NAMES utf8mb4")
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]
            buf.write("-- AIGC Studio logical backup (python)\n")
            buf.write("SET NAMES utf8mb4;\n")
            buf.write("SET FOREIGN_KEY_CHECKS=0;\n")
            for t in tables:
                cur.execute(f"SHOW CREATE TABLE `{t}`")
                create_sql = cur.fetchone()[1]
                buf.write(f"\nDROP TABLE IF EXISTS `{t}`;\n")
                buf.write(create_sql + ";\n")
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                (total,) = cur.fetchone()
                if total == 0:
                    continue
                cur.execute(f"SELECT * FROM `{t}`")
                cols = [d[0] for d in cur.description]
                batch: list[str] = []
                while True:
                    rows = cur.fetchmany(5000)
                    if not rows:
                        break
                    for row in rows:
                        vals = ", ".join(_sql_escape(v) for v in row)
                        batch.append(f"({vals})")
                        if len(batch) >= 200:
                            buf.write(
                                f"INSERT INTO `{t}` (`{'`,`'.join(cols)}`) VALUES\n"
                                + ",\n".join(batch)
                                + ";\n"
                            )
                            batch = []
                if batch:
                    buf.write(
                        f"INSERT INTO `{t}` (`{'`,`'.join(cols)}`) VALUES\n"
                        + ",\n".join(batch)
                        + ";\n"
                    )
        buf.write("SET FOREIGN_KEY_CHECKS=1;\n")
    finally:
        conn.close()
    return buf.getvalue().encode("utf-8")


def _backup_now() -> dict[str, object]:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_ROOT / stamp
    dest.mkdir(parents=True, exist_ok=True)

    # 1) MySQL 逻辑备份
    try:
        sql = _dump_database()
    except Exception as exc:
        if isinstance(exc, _RETRYABLE):
            raise  # DB 抖动自动重试
        return {"ok": False, "error": f"dump: {str(exc)[:200]}"}
    with gzip.open(dest / "mysql.sql.gz", "wb") as f:
        f.write(sql)

    # 2) storage
    storage = Path("/app/storage")
    if storage.is_dir():
        subprocess.run(
            ["tar", "-czf", str(dest / "storage.tar.gz"), "-C", "/app", "storage"],
            capture_output=True,
            timeout=600,
        )

    # 3) 清理过期
    cutoff = datetime.now(UTC) - timedelta(days=KEEP_DAYS)
    for d in BACKUP_ROOT.iterdir():
        if d.is_dir() and d.name[:8].isdigit():
            try:
                mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    return {"ok": True, "backup": dest.name, "sql_bytes": len(sql)}


@celery_app.task(  # type: ignore[untyped-decorator]
    name="daily_backup",
    max_retries=2,
    autoretry_for=_RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def daily_backup() -> dict[str, object]:
    """每日备份（beat 02:00）：逻辑 SQL + storage，保留 14 天。"""
    return _backup_now()
