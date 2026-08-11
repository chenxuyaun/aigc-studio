# ruff: noqa: T201 E501
"""
注册批次管理器：轮询注册机状态，挂起检测 + 自动重启，直到批次完成或超时。

注意：注册机 /api/run/status 的 success/failed 是「当前 run」的计数，跨 run 不累计。
本脚本维护 acc（跨 run 累计 success+failed），run 结束/挂起停止时把该 run 计数并入 acc。

用法: python register_watch.py [target=10] [max_wall_min=240]
"""

import json
import sys
import time
import urllib.request

KEY = ""
with open(r"D:\software\code\ideas\list\aigc-studio\.env", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("REGISTER_INTERNAL_KEY="):
            KEY = line.split("=", 1)[1].strip()

BASE = "http://localhost:6657"
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 10
MAX_WALL = int(sys.argv[2]) if len(sys.argv) > 2 else 240  # 分钟
STALL_MIN = 25  # 挂起判定：计数 25 分钟无变化


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("X-Internal-Key", KEY)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    else:
        data = None
    with urllib.request.urlopen(req, data=data, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


acc = 0  # 跨 run 累计 success+failed
current_rid = None  # 当前跟踪的 runId
last_count = None  # 当前 run 的上一次计数快照
stall_since = time.time()
runs_restarted = 0
deadline = time.time() + MAX_WALL * 60

# --- 初始化：若已有 run 在跑则接管（不重复 start） ---
try:
    s0 = api("GET", "/api/run/status")
    if s0.get("phase") == "running" and s0.get("runId"):
        current_rid = s0["runId"]
        # 接管时把该 run 已有计数计入 acc（否则重启 watcher 会丢失历史注册统计）
        acc = (s0.get("success") or 0) + (s0.get("failed") or 0)
        last_count = acc
        log(
            f"接管已运行 run {str(current_rid)[:8]} (success={s0.get('success')} failed={s0.get('failed')}) 累计={acc}"
        )
except Exception:
    pass

log(f"批次监控启动：目标 {TARGET} 个账号，墙钟上限 {MAX_WALL} 分钟，挂起判定 {STALL_MIN} 分钟")

while time.time() < deadline:
    # --- 阶段 1：确保有 run 在跑 ---
    if current_rid is None:
        remain = TARGET - acc
        if remain <= 0:
            log(f"批次完成：累计成功+失败={acc}，重启次数={runs_restarted}")
            break
        try:
            r = api("POST", "/api/run/start", {"runCount": remain})
            log(f"启动 run（剩余 {remain} 个）: {json.dumps(r, ensure_ascii=False)[:120]}")
        except Exception as e:
            log(f"启动失败: {str(e)[:100]}，30s 后重试")
            time.sleep(30)
            continue
        # 等待 status 出现该 run
        for _ in range(10):
            time.sleep(5)
            try:
                s = api("GET", "/api/run/status")
            except Exception:
                continue
            if s.get("runId"):
                current_rid = s["runId"]
                break
        if current_rid is None:
            log("启动后 50s 内未见 runId，重试")
            continue
        log(f"run {str(current_rid)[:8]} 就绪 (phase={s.get('phase')})")
        stall_since = time.time()
        last_count = (s.get("success") or 0) + (s.get("failed") or 0)
        continue

    # --- 阶段 2：轮询当前 run 直到结束或挂起 ---
    time.sleep(60)
    try:
        s = api("GET", "/api/run/status")
    except Exception as e:
        log(f"轮询错误: {str(e)[:80]}")
        continue
    phase = s.get("phase") or ""
    rid = s.get("runId")
    count = (s.get("success") or 0) + (s.get("failed") or 0)
    if last_count is None:
        last_count = count
        stall_since = time.time()
    if rid and rid != current_rid:
        # run 被外部切换（防御）：旧 run 计数已丢，重新绑定
        current_rid = rid
        last_count = count
        stall_since = time.time()
        log(f"检测到外部 run 切换 → {str(rid)[:8]}")
    if count != last_count:
        log(
            f"run {str(current_rid)[:8]} 推进: success={s.get('success')} failed={s.get('failed')} 本 run={count} 累计={acc}"
        )
        last_count = count
        stall_since = time.time()
    if phase in ("idle", "done", "stopped", "killed", "failed", "error"):
        acc += count
        log(
            f"run {str(current_rid)[:8]} 结束 (phase={phase})，本 run 计数={count}，累计={acc}/{TARGET}"
        )
        current_rid = None
        continue
    if phase == "running" and time.time() - stall_since > STALL_MIN * 60:
        log(f"⚠ 挂起：run {str(current_rid)[:8]} 已 {STALL_MIN} 分钟无推进，停止并重启")
        try:
            api("POST", "/api/run/stop")
        except Exception as e:
            log(f"stop 失败: {str(e)[:80]}")
        acc += count  # 挂起 run 已完成的账号并入累计
        current_rid = None
        runs_restarted += 1
        time.sleep(5)

else:
    log(f"超时（{MAX_WALL} 分钟）：累计={acc}/{TARGET}，重启次数={runs_restarted}")

log("监控退出")
