#!/usr/bin/env python3
"""将 local 媒体对象迁移到 R2/S3 兼容私有桶（幂等、可断点、可 dry-run）。

用法示例：
  cd apps/api
  python -m scripts.migrate_media_storage --dry-run --limit 20
  python -m scripts.migrate_media_storage --limit 100 --target r2
  python -m scripts.migrate_media_storage --resume-from <asset_or_photo_id>

注意：
- 至少保留 local 源文件 7 天，本脚本默认不删除 local。
- 需要完整 STORAGE_* 私有桶配置；STORAGE_PUBLIC_BASE_URL 必须为空。
- 仅迁移 storage_backend=local 的行。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from datetime import UTC, datetime

from app.core.database import AsyncSessionLocal
from app.models.asset import Asset
from app.models.photo import Photo
from app.storage import get_storage, normalize_backend
from sqlalchemy import select, update


async def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _migrate_one(
    *,
    kind: str,
    row_id: str,
    storage_key: str,
    mime: str,
    expected_sha: str | None,
    expected_size: int | None,
    target: str,
    dry_run: bool,
    delete_local: bool,
) -> str:
    local = get_storage("local")
    remote = get_storage(target)

    try:
        data = await local.get(storage_key)
    except FileNotFoundError:
        return f"SKIP {kind}:{row_id} local missing key={storage_key}"
    except Exception as exc:
        return f"FAIL {kind}:{row_id} local read: {exc}"

    if expected_size is not None and len(data) != expected_size:
        return (
            f"FAIL {kind}:{row_id} size mismatch local={len(data)} db={expected_size}"
        )
    digest = await _sha256(data)
    if expected_sha and expected_sha != digest:
        return f"FAIL {kind}:{row_id} sha256 mismatch"

    if dry_run:
        return f"DRY  {kind}:{row_id} would put {len(data)}B → {target}:{storage_key}"

    try:
        await remote.put(storage_key, data, mime or "application/octet-stream")
        # 读回校验（可选，小对象）
        if len(data) <= 5 * 1024 * 1024:
            back = await remote.get(storage_key)
            if hashlib.sha256(back).hexdigest() != digest:
                await remote.delete(storage_key)
                return f"FAIL {kind}:{row_id} remote checksum mismatch, rolled back object"
    except Exception as exc:
        return f"FAIL {kind}:{row_id} remote put: {exc}"

    async with AsyncSessionLocal() as db:
        model = Asset if kind == "asset" else Photo
        await db.execute(
            update(model)
            .where(model.id == row_id, model.storage_backend == "local")
            .values(storage_backend=target)
        )
        await db.commit()

    if delete_local:
        try:
            await local.delete(storage_key)
        except Exception as exc:
            return f"OK   {kind}:{row_id} migrated but local delete failed: {exc}"

    return f"OK   {kind}:{row_id} → {target}"


async def run(args: argparse.Namespace) -> int:
    target = normalize_backend(args.target)
    if target == "local":
        print("target 不能是 local", file=sys.stderr)
        return 2

    # 提前校验远程配置
    _ = get_storage(target)

    stats = {"ok": 0, "fail": 0, "skip": 0, "dry": 0}
    processed = 0

    async with AsyncSessionLocal() as db:
        asset_q = select(Asset).where(Asset.storage_backend == "local").order_by(Asset.created_at.asc())
        photo_q = select(Photo).where(Photo.storage_backend == "local").order_by(Photo.created_at.asc())
        if args.resume_from:
            # 简化：按 id 字符串比较跳过更早的（UUID 无序，仅作手动断点提示）
            pass
        assets = (await db.execute(asset_q)).scalars().all()
        photos = (await db.execute(photo_q)).scalars().all()

    rows: list[tuple[str, object]] = [("asset", a) for a in assets] + [
        ("photo", p) for p in photos
    ]
    if args.resume_from:
        started = False
        filtered = []
        for kind, row in rows:
            if row.id == args.resume_from:
                started = True
            if started:
                filtered.append((kind, row))
        rows = filtered

    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    print(
        f"[{datetime.now(UTC).isoformat()}] migrate local→{target} "
        f"candidates={len(rows)} dry_run={args.dry_run} delete_local={args.delete_local}"
    )

    for kind, row in rows:
        msg = await _migrate_one(
            kind=kind,
            row_id=row.id,
            storage_key=row.storage_key,
            mime=getattr(row, "mime_type", None) or "application/octet-stream",
            expected_sha=getattr(row, "sha256", None),
            expected_size=getattr(row, "size_bytes", None),
            target=target,
            dry_run=args.dry_run,
            delete_local=args.delete_local and not args.dry_run,
        )
        print(msg)
        processed += 1
        if msg.startswith("OK"):
            stats["ok"] += 1
        elif msg.startswith("DRY"):
            stats["dry"] += 1
        elif msg.startswith("SKIP"):
            stats["skip"] += 1
        else:
            stats["fail"] += 1
            if args.fail_fast:
                break

    print(f"done processed={processed} stats={stats}")
    return 1 if stats["fail"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local media to R2/S3")
    parser.add_argument("--target", default="r2", help="目标 backend（默认 r2）")
    parser.add_argument("--limit", type=int, default=0, help="最多迁移条数，0=不限")
    parser.add_argument("--dry-run", action="store_true", help="只读校验，不写远程/不改库")
    parser.add_argument(
        "--delete-local",
        action="store_true",
        help="迁移成功后删除 local 源（默认保留 ≥7 天，不建议立刻开）",
    )
    parser.add_argument("--resume-from", default="", help="从该 asset/photo id 起继续")
    parser.add_argument("--fail-fast", action="store_true", help="首个失败即停止")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
