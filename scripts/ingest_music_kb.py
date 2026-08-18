# -*- coding: utf-8 -*-
"""MySQL 检查 text_documents 表结构 + 入库 music 知识。"""
import pymysql
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

env = {}
for line in open("D:/software/code/ideas/list/aigc-studio/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

conn = pymysql.connect(
    host="127.0.0.1", port=int(env["MYSQL_PORT"]), user=env["MYSQL_USER"],
    password=env["MYSQL_PASSWORD"], database=env["MYSQL_DATABASE"], charset="utf8mb4",
)
cur = conn.cursor()
cur.execute("SHOW COLUMNS FROM text_documents")
print("columns:", [c[0] for c in cur.fetchall()])

if "--check" in sys.argv:
    cur.execute("SELECT COUNT(*) FROM text_documents WHERE user_id='admin' AND status='confirmed'")
    print("admin confirmed docs:", cur.fetchone()[0])
    conn.close()
    sys.exit(0)

# 入库（检索按登录用户隔离 → 同时入库给常见账号）
import uuid

ADMIN_UID = "18787a25-2fb6-415e-93e6-3b2f08c9e4ad"  # admin
BROTHER_UID = "f3a90ae3-2c79-40e0-82c6-721e1cf15702"  # brother1

kb_dir = Path("D:/software/code/ideas/list/aigc-studio/knowledge/music")
for uid, label in ((ADMIN_UID, "admin"), (BROTHER_UID, "brother1")):
    for f in sorted(kb_dir.glob("*.md")):
        content = f.read_text(encoding="utf-8").strip()
        title = f"创作技法·{f.stem}"
        cur.execute(
            "SELECT id FROM text_documents WHERE user_id=%s AND title=%s LIMIT 1",
            (uid, title),
        )
        if cur.fetchone():
            print(f"skip ({label}, exists): {f.stem}")
            continue
        cur.execute(
            "INSERT INTO text_documents (id, title, content, task_id, user_id, status, created_at, updated_at) "
            "VALUES (%s,%s,%s,NULL,%s,'confirmed',NOW(),NOW())",
            (str(uuid.uuid4()), title, content, uid),
        )
        print(f"ingested ({label}): {title} ({len(content)} chars)")
conn.commit()
conn.close()
print("done")
