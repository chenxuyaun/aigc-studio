# ruff: noqa: T201
"""
Grok 恢复探测：每 10 分钟探测一次 grok-chat-fast；一旦恢复（200）则重启注册机补号。
用法: python grok_probe.py [max_hours=12]
"""

import json
import sys
import time
import urllib.request


def env(k: str) -> str:
    with open(r"D:\software\code\ideas\list\aigc-studio\.env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    return ""


BASE = "http://localhost:8002"


def call(method, path, body=None, token=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except Exception as e:
        return -1, {"_err": str(e)[:120]}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


MAX_HOURS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
deadline = time.time() + MAX_HOURS * 3600
probes = 0
log(f"Grok 恢复探测启动：每 10 分钟，最长 {MAX_HOURS} 小时")

while time.time() < deadline:
    probes += 1
    st, d = call(
        "POST",
        "/api/v1/auth/login",
        {
            "username": env("INITIAL_ADMIN_USERNAME"),
            "password": env("INITIAL_ADMIN_PASSWORD"),
        },
    )
    if st != 200:
        log(f"[{probes}] API 登录失败 {st}，30 分钟后重试")
        time.sleep(1800)
        continue
    token = d["access_token"]
    st, r = call(
        "POST",
        "/v1/chat/completions",
        {
            "model": "grok-chat-fast",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        },
        token=token,
        timeout=60,
    )
    if st == 200:
        log(f"[{probes}] ✅ Grok 已恢复（200）——重启注册机补号")
        try:
            key = env("REGISTER_INTERNAL_KEY")
            req = urllib.request.Request("http://localhost:6657/api/run/start", method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("X-Internal-Key", key)
            with urllib.request.urlopen(
                req, data=json.dumps({"runCount": 9}).encode(), timeout=20
            ) as resp:
                log("注册机启动: " + resp.read().decode()[:120])
        except Exception as e:
            log(f"注册机启动失败: {str(e)[:120]}")
        break
    else:
        err = r.get("error", {}).get("message", str(r)[:80])
        log(f"[{probes}] Grok 未恢复: {st} {err[:80]}")
    time.sleep(600)

log("探测退出")
