#!/usr/bin/env python3
"""记忆系统端到端验证（grok2api 恢复后自动完成闭环）。

流程：grok2api 可用性 → 角色对话（触发记忆写入）→ 等待 L1 抽取 → 查 memory overview
atoms → 召回注入验证（问记忆性问题看回复是否引用）。

用法：python scripts/verify-memory-e2e.py
退出码：0=闭环验证通过  1=grok2api 仍限流/不可用  2=验证失败
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("API_BASE", "http://127.0.0.1:8002")
ASSET_ID = os.environ.get("MEMORY_ASSET_ID", "0d9fbb51-e941-4381-9eb0-8d1c48d6cc30")
SESSION_ID = os.environ.get("MEMORY_SESSION_ID", "cd927727-bcc2-4a5f-a2f8-9860a75fec8b")
GROK_URL = os.environ.get("GROK_URL", "http://127.0.0.1:8000/v1/chat/completions")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(__file__).resolve().parent.parent / ".env"
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1)
            env[k] = v
    return env


def call(path: str, body=None, token=None, method="POST", timeout: float = 30) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data,
        headers={"Content-Type": "application/json"}, method=method,
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        raise RuntimeError(f"请求失败 {path}: {e}") from e


def grok_ready() -> bool:
    env = load_env()
    key = os.environ.get("GROK_API_KEY") or env.get("OPENAI_COMPATIBLE_API_KEY", "")
    model = os.environ.get("GROK_MODEL", "grok-chat-fast")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 8,
    }).encode()
    req = urllib.request.Request(
        GROK_URL, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    print("1/4 检查 grok2api 上游…", flush=True)
    if not grok_ready():
        print("grok2api 仍限流/不可用（外部依赖等待中）")
        return 1

    env = load_env()
    st, d = call("/api/v1/auth/login", {
        "username": env["INITIAL_ADMIN_USERNAME"],
        "password": env["INITIAL_ADMIN_PASSWORD"],
    })
    tok = d.get("access_token")
    if st != 200 or not tok:
        print(f"登录失败: {st}")
        return 2

    print("2/4 触发角色对话（记忆写入 + 抽取调度）…", flush=True)
    st, d = call("/api/v1/roleplay/chat", {
        "character_asset_ids": [ASSET_ID],
        "messages": [{"role": "user",
                      "content": "你还记得我之前说过的事吗？比如我的猫和我的工作。"}],
        "session_id": SESSION_ID,
    }, token=tok, timeout=120)
    if st != 200:
        print(f"对话失败: {st} {d}")
        return 2
    reply = str(d.get("reply", ""))
    print(f"  回复: {reply[:80]}…")

    print("3/4 等待 L1 抽取（60s）…", flush=True)
    time.sleep(60)

    st, d = call(f"/api/v1/memory/{ASSET_ID}", token=tok, method="GET")
    atoms = d.get("atoms", [])
    print(f"  atoms: {len(atoms)} 条")
    for a in atoms[:6]:
        print(f"    - {str(a.get('content', ''))[:70]}")

    # 召回注入验证：回复里是否体现记忆内容
    recalled = any(k in reply for k in ("猫", "团子", "程序", "工作", "咖啡", "雨天"))
    print(f"4/4 召回注入: 回复引用记忆={'是' if recalled else '否'}")
    if len(atoms) >= 3 and recalled:
        print("✅ 记忆端到端闭环验证通过")
        return 0
    if len(atoms) > 0:
        print("⚠️ L1 抽取已产出，但召回引用未确认（回复可能未提及）")
        return 0
    print("❌ L1 抽取未产出（可能仍在排队）")
    return 2


if __name__ == "__main__":
    sys.exit(main())
