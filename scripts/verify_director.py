import json
import os, urllib.request, urllib.error, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8002"

def call(path, payload=None, token=None, timeout=240):
    req = urllib.request.Request(BASE + path, method="POST" if payload is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    try:
        with urllib.request.urlopen(req, body, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

st, raw = call("/api/v1/auth/login", {"username": "brother1", "password": os.environ.get("AIGC_DEMO_PASSWORD", "CHANGE_ME")})
tok = raw["access_token"]
st0, chats = call("/api/v1/roleplay/chats", token=tok)
room = next(c for c in chats.get("items", []) if c.get("is_room"))
char_ids = json.loads(room["character_asset_ids"]) if isinstance(room.get("character_asset_ids"), str) else room.get("character_asset_ids", [])

# ② 按导演指令演一场（群聊共创，AI 角色入戏）
scene = "（第1场）雨夜，草棚里，子衿为墨尘裹伤。笑莲撑伞闯入，俏皮道：雨夜里偷戏，谁敢不收？"
st2, r2 = call("/api/v1/roleplay/chat", {
    "character_asset_ids": char_ids, "session_id": room["id"], "group": True, "author": "旁白",
    "messages": [{"role": "user", "content": scene}],
}, token=tok, timeout=240)
print("② 演出:", st2, "|", str(r2.get("reply") or r2.get("message") or "")[:150].replace("\n", " / "))

# ③ @AI 导演：总结 → 剧本段落
st3, r3 = call("/api/v1/roleplay/chat", {
    "character_asset_ids": char_ids, "session_id": room["id"], "group": True, "author": "旁白",
    "messages": [{"role": "user", "content": "@AI 导演：总结"}],
}, token=tok, timeout=240)
print("③ 总结:", st3, "| director:", r3.get("director"))
print(r3.get("reply", "")[:350].replace("\n", " / "))

# ④ 落库检查
st4, detail = call(f"/api/v1/roleplay/chats/{room['id']}", token=tok)
msgs = detail.get("messages", [])
print("④ 落库消息数:", len(msgs), "| 最后2条:", [m["role"] for m in msgs[-2:]])
