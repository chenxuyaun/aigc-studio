"""SQLite → MySQL 全量数据迁移。

背景：本地开发数据在 apps/api/aigc_studio.db（SQLite）；docker 部署后 API 连
MySQL（compose 的 mysql 服务）。本脚本把 SQLite 中除 alembic_version 外的
全部业务表数据搬入 MySQL。

流程：
1. 在目标 MySQL 上跑 `alembic upgrade head` 建表（表结构完全一致）
2. 幂等保护：目标库已有业务数据则中止（防重复导入）
3. 以 FOREIGN_KEY_CHECKS=0 逐表导入（SQLite 的 datetime 统一转 naive UTC）

用法：
    python scripts/migrate_sqlite_to_mysql.py \
        --mysql-url "mysql+aiomysql://aigc:密码@127.0.0.1:3306/aigc_studio" \
        [--sqlite apps/api/aigc_studio.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_API_ROOT = Path(__file__).resolve().parent.parent

_EXCLUDE_TABLES = {"alembic_version"}


async def _ensure_schema(mysql_url: str) -> None:
    """在 MySQL 上执行 alembic upgrade head 建表（表结构由迁移文件保证一致）。"""
    env = {**os.environ, "DATABASE_URL": mysql_url}
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "head",
        cwd=str(_API_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"alembic upgrade head 失败:\n{out.decode('utf-8', 'replace')}")
    print(out.decode("utf-8", "replace").strip() or "alembic upgrade head OK")


async def _table_has_data(engine, table: str) -> bool:
    async with engine.connect() as conn:
        n = (await conn.execute(text(f"SELECT COUNT(*) FROM `{table}`"))).scalar_one()
    return n > 0


async def migrate(sqlite_path: str, mysql_url: str, dry_run: bool = False) -> None:
    sqlite_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    mysql_engine = create_async_engine(mysql_url)

    async with sqlite_engine.connect() as src:
        tables = [
            r[0]
            for r in (
                await src.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    )
                )
            ).all()
        ]
    tables = [t for t in tables if t not in _EXCLUDE_TABLES]
    print(f"SQLite 待迁移表（{len(tables)} 张）: {', '.join(tables)}")

    if not dry_run:
        await _ensure_schema(mysql_url)

        # 幂等保护：任一业务表已有数据就中止
        for probe in ("users", "prompts", "assets"):
            if await _table_has_data(mysql_engine, probe):
                raise SystemExit(
                    f"目标 MySQL 的 `{probe}` 表已有数据，中止迁移（防重复导入）。"
                    "如确需重导，请先清空目标库。"
                )

    total = 0
    async with mysql_engine.begin() as dst:
        await dst.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        for table in tables:
            async with sqlite_engine.connect() as src:
                rows = (await src.execute(text(f'SELECT * FROM "{table}"'))).all()
            if not rows:
                print(f"  {table}: 0 行（跳过）")
                continue
            col_names = list(rows[0]._mapping.keys())
            # SQLite 读出 naive UTC 字符串 → datetime；MySQL DATETIME 存 naive UTC
            values = [
                [
                    v.replace(tzinfo=None)
                    if isinstance(v, datetime)
                    else v
                    for v in row
                ]
                for row in rows
            ]
            if dry_run:
                print(f"  {table}: {len(rows)} 行（dry-run 不写入）")
                total += len(rows)
                continue
            placeholders = ", ".join([":" + c for c in col_names])
            await dst.execute(
                text(f"INSERT INTO `{table}` ({', '.join('`' + c + '`' for c in col_names)}) VALUES ({placeholders})"),
                [dict(zip(col_names, r)) for r in values],
            )
            print(f"  {table}: {len(rows)} 行 ✓")
            total += len(rows)
        await dst.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")

    await sqlite_engine.dispose()
    await mysql_engine.dispose()
    print(f"\n迁移完成，共导入 {total} 行。" + ("（dry-run 未写入）" if dry_run else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite → MySQL 迁移")
    parser.add_argument("--mysql-url", required=True, help="目标 MySQL 连接串")
    parser.add_argument("--sqlite", default=str(_API_ROOT / "aigc_studio.db"))
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()
    asyncio.run(migrate(args.sqlite, args.mysql_url, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
