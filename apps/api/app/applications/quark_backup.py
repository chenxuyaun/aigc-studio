"""saiOS → 夸克 WebDAV 备份脚本
- 扫未备份 asset
- PUT 到 webdav (http://127.0.0.1:8080)
- 写 asset_quark_backups 表
用法: python -m app.services.quark_backup [limit=20]
"""
import asyncio
import os
import sys
import time

import requests
from sqlalchemy import text

from app.core.database import engine

DAV = os.environ.get("QUARK_WEBDAV_URL", "http://host.docker.internal:8080")
DAV_USER = os.environ.get("QUARK_WEBDAV_USER", "admin")
DAV_PASS = os.environ.get("QUARK_WEBDAV_PASS", "admin888")
STORAGE = os.environ.get("STORAGE_LOCAL_PATH", "/app/storage")
ROOT_DIR = "saios-backup"  # 夸克上的子目录


async def main(limit: int = 20):
    async with engine.connect() as co:
        # 建表（如果不存在）
        await co.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_quark_backups (
                asset_id VARCHAR(36) PRIMARY KEY,
                quark_path VARCHAR(500) NOT NULL,
                uploaded_bytes INT NOT NULL DEFAULT 0,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # 索引
        try:
            await co.execute(text("CREATE INDEX ix_aqb_uploaded_at ON asset_quark_backups (uploaded_at)"))
        except Exception:
            pass
        await co.commit()
        # 查未备份的 asset
        r = await co.execute(text("""
            SELECT a.id, a.filename, a.storage_key, a.mime_type, a.size_bytes
            FROM assets a
            LEFT JOIN asset_quark_backups b ON b.asset_id = a.id
            WHERE b.asset_id IS NULL
            ORDER BY a.created_at DESC
            LIMIT :lim
        """), {"lim": limit})
        rows = list(r)
        print(f"[未备份总数] {len(rows)} 条待处理")
        ok = 0
        fail = 0
        for row in rows:
            asset_id, filename, storage_key, mime, size = row
            local_path = os.path.join(STORAGE, storage_key)
            if not os.path.exists(local_path):
                print(f"[缺文件] {asset_id} {local_path}")
                fail += 1
                continue
            # 夸克路径：saios-backup/<user_id>/<yyyy>/<mm>/<filename>
            yyyymm = time.strftime("%Y/%m")
            user_id = asset_id.split("-")[0]  # 简略用 id 前缀
            # 实际更准应该查 user_id，这里先简化按年/月
            # 从 storage_key 推断 user：key 是 e82d6f24-.../2026/08/...
            parts = storage_key.split("/")
            user_dir = parts[0] if parts else "unknown"
            quark_rel = f"{ROOT_DIR}/{user_dir}/{yyyymm}/{filename}"
            dav_url = f"{DAV}/{quark_rel}"
            # 确保父目录（WebDAV 自动创建不靠谱，先建）
            parent = "/".join(quark_rel.split("/")[:-1])
            for d in [ROOT_DIR, f"{ROOT_DIR}/{user_dir}",
                      f"{ROOT_DIR}/{user_dir}/{yyyymm.split('/')[0]}",
                      f"{ROOT_DIR}/{user_dir}/{yyyymm}"]:
                try:
                    requests.request("MKCOL", f"{DAV}/{d}", auth=(DAV_USER, DAV_PASS), timeout=20)
                except Exception:
                    pass
            # 上传
            try:
                with open(local_path, "rb") as f:
                    r2 = requests.put(dav_url, data=f.read(), auth=(DAV_USER, DAV_PASS), timeout=120)
                if r2.status_code in (200, 201, 204):
                    sz = os.path.getsize(local_path)
                    await co.execute(text("""
                        INSERT INTO asset_quark_backups(asset_id, quark_path, uploaded_bytes)
                        VALUES(:aid, :qp, :sz)
                    """), {"aid": asset_id, "qp": quark_rel, "sz": sz})
                    await co.commit()
                    print(f"[OK] {filename} ({sz} bytes) -> {quark_rel}")
                    ok += 1
                else:
                    print(f"[FAIL] {filename} {r2.status_code} {r2.text[:80]}")
                    fail += 1
            except Exception as e:
                print(f"[EXC] {filename} {type(e).__name__}: {e}")
                fail += 1
        print(f"\n[完成] ok={ok} fail={fail}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    asyncio.run(main(n))
