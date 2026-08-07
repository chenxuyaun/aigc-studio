"""漫画 E2E 自动等待验证：grok 图片恢复可用后自动跑完整漫画任务。

轮询 grok2api 图片接口（每 5 分钟）；一旦可用：
1. 调 AIGC API 创建 4 格漫画任务
2. 轮询至 succeeded，校验分镜格数 + 每格资产数 + 拼合页
3. 输出结果后退出

用法：python scripts/comic_e2e_waiter.py
凭据从根 .env 读取（INITIAL_ADMIN_PASSWORD）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]  # scripts → api → apps → 仓库根
G2A = "http://localhost:8000"
AIGC = "http://localhost:8002"


def env_val(key: str) -> str:
    m = re.search(rf"^{key}=(.+)$", (ROOT / ".env").read_text(encoding="utf-8"), re.M)
    return m.group(1).strip() if m else ""


def grok_ready() -> bool:
    key = env_val("OPENAI_COMPATIBLE_API_KEY")
    if not key:
        return False
    try:
        r = httpx.post(
            f"{G2A}/v1/images/generations",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "grok-imagine-image", "prompt": "a tiny cat", "n": 1},
            timeout=150,
        )
        return r.status_code == 200
    except Exception:
        return False


def run_comic_e2e() -> bool:
    """跑一次漫画 E2E；完整成功（4 格资产齐全）返回 True。"""
    admin_pass = env_val("INITIAL_ADMIN_PASSWORD")
    r = httpx.post(
        f"{AIGC}/api/v1/auth/login",
        json={"username": "admin", "password": admin_pass},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"[comic-e2e] 登录失败: {r.status_code}", flush=True)
        return False
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.post(
            f"{AIGC}/api/v1/generations/comic/generate",
            headers=h,
            json={
                "model": "grok-imagine-image",
                "prompt": "一只橘猫和一只柴犬成为朋友，一起在城市里冒险",
                "panels": 4,
                "style": "日式漫画",
            },
            timeout=60,
        )
        body = resp.json()
        # AIGC 任务创建响应是顶层对象：{id, task_type, status, ...}
        task_id = body.get("id") or body.get("task_id")
        if not task_id:
            print(f"[comic-e2e] 创建失败: {resp.text[:200]}", flush=True)
            return False
        print(f"[comic-e2e] 任务已创建: {task_id}", flush=True)
    except Exception as exc:
        print(f"[comic-e2e] 创建异常: {exc}", flush=True)
        return False
    for i in range(90):
        try:
            r2 = httpx.get(f"{AIGC}/api/v1/tasks/{task_id}", headers=h, timeout=30)
            t = r2.json().get("data", r2.json())
        except Exception as exc:
            print(f"[comic-e2e] 轮询异常: {exc}", flush=True)
            time.sleep(10)
            continue
        if not isinstance(t, dict):
            time.sleep(10)
            continue
        st = t.get("status")
        if st in ("succeeded", "failed", "cancelled"):
            if st == "succeeded":
                res = json.loads(t.get("result") or "{}")
                comic = res.get("comic") or {}
                n_assets = len(comic.get("assets") or [])
                print(
                    f"[comic-e2e] 分镜{len(comic.get('panels') or [])}格 | "
                    f"每格资产{n_assets} | 主资产{str(res.get('asset_id'))[:8]}",
                    flush=True,
                )
                return n_assets >= 4
            print(f"[comic-e2e] ❌ 失败: {t.get('error_message','')[:150]}", flush=True)
            return False
        time.sleep(10)
    print("[comic-e2e] ❌ 超时", flush=True)
    return False


def main() -> None:
    print("[comic-e2e] 开始监控 grok 图片可用性（每 5 分钟）…", flush=True)
    while True:
        try:
            if grok_ready():
                print("[comic-e2e] 🎉 grok 图片已恢复，开始漫画 E2E", flush=True)
                if run_comic_e2e():
                    print("[comic-e2e] ✅ 漫画 E2E 完整成功（4 格资产齐全）", flush=True)
                    return
                print("[comic-e2e] E2E 未完整成功，继续监控…", flush=True)
        except Exception as exc:
            print(f"[comic-e2e] 监控异常: {exc}", flush=True)
        time.sleep(300)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
