import json, os, urllib.request
BASE = "http://127.0.0.1:8002/api/v1"
TOKEN = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"{BASE}/auth/login",
    data=json.dumps({"username": "brother1", "password": os.environ.get("AIGC_DEMO_PASSWORD", "rXtuHkab")}).encode(),
    headers={"Content-Type": "application/json"}, method="POST"), timeout=30).read())["access_token"]
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# 1) 跑一个大概率部分失败的 mission（触发教训沉淀）
body = json.dumps({"goal": "写一首关于老手艺人的歌，检索一下传统手艺失传的现状"}, ensure_ascii=False).encode()
req = urllib.request.Request(f"{BASE}/mission", data=body, headers=H, method="POST")
try:
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    print("=== Mission 结果 ===")
    for p in r.get("plan", []):
        print(f" 步{p['step']}: {p.get('kind')} — {p.get('title')}")
    for res in r.get("results", []):
        print(f" [{res['step']}] {res.get('kind')} {'✅' if res.get('ok') else '❌'}")
    print("汇总:", r.get("summary"))
except Exception as e:
    print("Mission 失败:", e)

# 2) 查教训历史
req = urllib.request.Request(f"{BASE}/mission/history", headers=H)
h = json.loads(urllib.request.urlopen(req, timeout=30).read())
print("\n=== 沉淀的教训 ===")
for l in h.get("lessons", []):
    print(" -", l.get("lesson"))
if not h.get("lessons"):
    print("（暂无教训——本场全成功或教训提炼未触发）")
