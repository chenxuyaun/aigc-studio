"""kb_batch3 入库脚本：读 token → POST /api/v1/knowledge/documents 批量导入。"""
import json
import os
import sys
import urllib.request

BASE = "http://127.0.0.1:8002/api/v1"
TOKEN = json.loads(
    urllib.request.urlopen(
        urllib.request.Request(
            f"{BASE}/auth/login",
            data=json.dumps({"username": "brother1", "password": os.environ.get("AIGC_DEMO_PASSWORD", "CHANGE_ME")}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        ),
        timeout=30,
    ).read()
)["access_token"]

with open(__file__.rsplit("\\", 1)[0] + "/kb_batch3.json", encoding="utf-8") as f:
    docs = json.load(f)

ok, fail = 0, []
for doc in docs:
    req = urllib.request.Request(
        f"{BASE}/knowledge/documents",
        data=json.dumps(doc).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        has_ai = "AI 精华解读" in data.get("content", "")
        print(f"[OK] {data.get('title')}  id={data.get('id')}  AI解读={has_ai}")
        ok += 1
    except Exception as exc:
        print(f"[FAIL] {doc['title']}: {exc}")
        fail.append(doc["title"])

print(f"\n成功 {ok}/{len(docs)}")
if fail:
    print("失败:", fail)
    sys.exit(1)
