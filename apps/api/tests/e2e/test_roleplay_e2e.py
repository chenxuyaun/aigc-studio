# ruff: noqa: T201 E501
"""角色扮演（SillyTavern 功能融入）真实 E2E：会话/流式/角色卡/世界书/正则/persona/快捷回复。"""
import json
import sys

import httpx

BASE = "http://localhost:5000/api/v1"
PASSED = []
FAILED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS" if cond else "FAIL"), name, detail[:200] if detail else "")


def main():
    c = httpx.Client(timeout=180, base_url=BASE)
    r = c.post("/auth/login", json={"username": "admin", "password": "admin123"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 1. 角色卡列表 + 详情
    chars = c.get("/roleplay/characters", headers=h).json()["items"]
    check("characters list", len(chars) >= 2, f"count={len(chars)}")
    aid = chars[0]["asset_id"]
    detail = c.get(f"/roleplay/characters/{aid}", headers=h).json()["asset"]
    check("character detail", bool(detail.get("name")), detail.get("name", ""))
    check("character has V2 fields", "description" in detail and "first_mes" in detail)

    # 2. 编辑角色卡（追加 PHI）
    r = c.put(
        f"/roleplay/characters/{aid}",
        headers=h,
        json={"post_history_instructions": "对话结束时提醒对方注意安全。"},
    )
    check("character update", r.json().get("ok") is True, r.text[:100])
    detail2 = c.get(f"/roleplay/characters/{aid}", headers=h).json()["asset"]
    check("character update persisted", "注意安全" in detail2.get("post_history_instructions", ""))

    # 3. 导出/导入角色卡
    r = c.get(f"/roleplay/characters/{aid}/export", headers=h, params={"format": "json"})
    check("character export json", r.status_code == 200 and "chara_card_v2" in r.text, r.text[:80])
    r = c.get(f"/roleplay/characters/{aid}/export", headers=h, params={"format": "png"})
    check("character export png", r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n")
    r = c.post(
        "/roleplay/characters/import",
        headers=h,
        files={"file": ("imported.json", r.content, "image/png")},
    )
    imported = r.json()
    check("character import", imported.get("ok") is True and bool(imported.get("asset_id")), r.text[:120])

    # 4. 会话 CRUD
    r = c.post("/roleplay/chats", headers=h, json={
        "title": "E2E 会话", "character_asset_ids": [aid], "group": False,
        "model": "gpt-oss-120b-medium", "temperature": 0.7, "max_tokens": 512,
    })
    chat = r.json()["chat"]
    sid = chat["id"]
    check("chat create", bool(sid) and chat["message_count"] == 0, r.text[:100])
    r = c.put(f"/roleplay/chats/{sid}", headers=h, json={"title": "E2E 改名"})
    check("chat rename", r.json().get("ok") is True)
    chats = c.get("/roleplay/chats", headers=h).json()["items"]
    check("chat list contains", any(x["id"] == sid for x in chats))

    # 5. 流式聊天（真实模型 cpa）
    msgs = [{"role": "user", "content": "你好！介绍一下你自己。"}]
    chunks = []
    done = None
    with c.stream("POST", "/roleplay/chat/stream", headers=h, json={
        "character_asset_ids": [aid], "messages": msgs, "model": "gpt-oss-120b-medium",
        "session_id": sid, "temperature": 0.7, "max_tokens": 512,
    }) as resp:
        check("stream status 200", resp.status_code == 200, str(resp.status_code))
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            ev = json.loads(line[6:])
            if ev.get("type") == "chunk":
                chunks.append(ev.get("content", ""))
            elif ev.get("type") == "done":
                done = ev
    reply = "".join(chunks)
    check("stream chunks non-empty", len(reply) > 10, reply[:80])
    check("stream done event", done is not None and bool(done.get("reply")))
    check("stream mood", done is not None and done.get("mood", "") != "", str(done.get("mood", "")) if done else "")
    check("stream mood_delta int", done is not None and isinstance(done.get("mood_delta"), int))
    # 会话已落库
    chat2 = c.get(f"/roleplay/chats/{sid}", headers=h).json()
    check("chat persisted messages", len(chat2["messages"]) == 2, f"count={len(chat2['messages'])}")
    check("chat mood persisted", bool(chat2["messages"][1].get("mood")))

    # 6. 会话导出 JSONL + 导入
    r = c.get(f"/roleplay/chats/{sid}/export", headers=h)
    jsonl = r.text
    check("chat export jsonl", r.status_code == 200 and len(jsonl.splitlines()) == 3, jsonl[:80])
    r = c.post("/roleplay/chats/import", headers=h, files={"file": ("c.jsonl", jsonl.encode(), "application/x-ndjson")})
    check("chat import", r.json().get("ok") is True, r.text[:100])

    # 7. 世界书全字段 CRUD
    r = c.post("/roleplay/lore", headers=h, json={
        "character_name": detail.get("name"), "keywords": ["月亮石"],
        "content": "月亮石是这个世界魔法的源头，月亮升起时魔力最强。",
        "constant": False, "position": "before", "order_value": 100,
        "probability": 100, "enabled": True, "selective": True, "selective_logic": "AND_ANY",
    })
    lid = r.json().get("id")
    check("lore create", bool(lid), r.text[:100])
    r = c.put(f"/roleplay/lore/{lid}", headers=h, json={
        "keywords": ["月亮石", "月石"], "content": "月亮石是魔法的源头（已编辑）。",
        "position": "after", "constant": True, "order_value": 50,
        "probability": 100, "enabled": True, "selective": False,
    })
    check("lore update", r.json().get("ok") is True)
    lore = c.get("/roleplay/lore", headers=h).json()["items"]
    target = next((e for e in lore if e["id"] == lid), None)
    check("lore updated fields", target and target["constant"] is True and target["position"] == "after" and "月石" in target["keywords"], str(target)[:120] if target else "missing")
    check("lore delete", c.delete(f"/roleplay/lore/{lid}", headers=h).json().get("ok") is True)

    # 8. regex 脚本 + 应用到回复
    r = c.post("/roleplay/regex-scripts", headers=h, json={
        "name": "清理星号", "pattern": r"\*", "replacement": "【】", "placement": "ai_output",
        "enabled": True, "scope": "global",
    })
    rid = r.json().get("id")
    check("regex create", bool(rid))
    r = c.post("/roleplay/chat", headers=h, json={
        "character_asset_ids": [aid],
        "messages": [{"role": "user", "content": "用星号强调一个词试试：魔法"}],
        "model": "gpt-oss-120b-medium",
    })
    resp = r.json()
    check("chat non-stream 200", r.status_code == 200 and bool(resp.get("reply")), resp.get("error", ""))
    check("regex applied (no asterisks)", "*" not in resp.get("reply", ""), resp.get("reply", "")[:80])
    check("regex delete", c.delete(f"/roleplay/regex-scripts/{rid}", headers=h).json().get("ok") is True)

    # 9. persona
    r = c.post("/roleplay/personas", headers=h, json={"name": "艾拉", "description": "一位来自深海的探险家。"})
    pid = r.json().get("id")
    check("persona create", bool(pid))
    r = c.post("/roleplay/chat", headers=h, json={
        "character_asset_ids": [aid],
        "messages": [{"role": "user", "content": "还记得我们上次的冒险吗？"}],
        "model": "gpt-oss-120b-medium", "persona_id": pid,
    })
    check("chat with persona", r.status_code == 200 and bool(r.json().get("reply")))
    personas = c.get("/roleplay/personas", headers=h).json()["items"]
    check("persona list", any(p["id"] == pid for p in personas))
    check("persona delete", c.delete(f"/roleplay/personas/{pid}", headers=h).json().get("ok") is True)

    # 10. 快捷回复
    r = c.post("/roleplay/quick-replies", headers=h, json={
        "label": "回忆冒险", "message": "还记得我们上次的冒险吗？{{char}}", "scope": "global",
    })
    qid = r.json().get("id")
    check("quick reply create", bool(qid))
    qs = c.get("/roleplay/quick-replies", headers=h).json()["items"]
    check("quick reply list", any(q["id"] == qid for q in qs))
    check("quick reply delete", c.delete(f"/roleplay/quick-replies/{qid}", headers=h).json().get("ok") is True)

    # 清理：删除 E2E 会话与导入的角色卡
    c.delete(f"/roleplay/chats/{sid}", headers=h)
    if imported.get("ok"):
        c.delete(f"/roleplay/characters/{imported['asset_id']}", headers=h)

    print(f"\n===== {len(PASSED)} passed, {len(FAILED)} failed =====")
    if FAILED:
        print("FAILED:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
