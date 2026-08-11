# ruff: noqa: T201
"""Grok 账号导入 + 验证脚本（用户导出 cookie 后运行）。

用法：
  python grok_import.py <cookie文件>
    cookie 文件格式（任一）：
      - 逐行  email | password | sso_token     （grok 官方扩展导出格式）
      - JSON 数组 / JSONL（字段 sso_token）
      - 浏览器 F12 复制的完整 cookie（grok.com 域名，分号分隔）

流程：登录 grok2api 管理 API → multipart 导入 → 查询账号状态 → 实测 grok-chat-fast。
"""

import sys
import time
from pathlib import Path

import httpx

ADMIN = "http://localhost:8000/api/admin/v1"
WORKBENCH = "http://localhost:5000/api/v1"


def admin_token() -> str:
    r = httpx.post(
        f"{ADMIN}/auth/login",
        json={"username": "admin", "password": "grok2api_local_2026"},
        timeout=15,
    )
    return r.json()["data"]["tokens"]["accessToken"]


def normalize(raw: str) -> str:
    """把浏览器 cookie 字符串转成逐行 email | password | sso 格式（尽力而为）。"""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    # 已是 email|password|sso 格式
    if lines and "|" in lines[0] and "@" in lines[0].split("|")[0]:
        return raw
    # 浏览器 cookie（name=value; ...）：尝试提取 sso / sso_rw / session cookie
    cookies = {}
    for pair in raw.replace("\n", ";").split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies[k.strip()] = v.strip()
    sso = (
        cookies.get("sso")
        or cookies.get("sso_rw")
        or cookies.get("session")
        or cookies.get("accessToken")
    )
    if sso:
        # 无 email 时用占位邮箱（grok2api 以 name 为主）
        return f"browser-import@local | placeholder | {sso}"
    # 原样返回（可能是 JSON）
    return raw


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python grok_import.py <cookie文件>")
        return 1
    raw = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    text = normalize(raw)

    tok = admin_token()
    h = {"Authorization": f"Bearer {tok}"}
    r = httpx.post(
        f"{ADMIN}/accounts/import",
        headers=h,
        files={"file": ("grok-tokens.txt", text.encode(), "text/plain")},
        timeout=300,
    )
    print("导入响应:", r.text[:200])

    # 查询账号状态
    time.sleep(3)
    acc = httpx.get(f"{ADMIN}/accounts?pageSize=2100", headers=h, timeout=60).json()["data"]
    items = acc.get("items", [])
    ok = [a for a in items if (a.get("quota") or {}).get("remaining", 0) > 0]
    print(f"账号总数: {acc.get('total')} | quota>0: {len(ok)}")
    for a in ok[:5]:
        q = a.get("quota") or {}
        print("  ", a["name"], "| quota:", q.get("remaining"))

    # 实测 grok-chat-fast
    if ok:
        r2 = httpx.post(
            f"{WORKBENCH}/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=30,
        )
        wh = {"Authorization": f"Bearer {r2.json()['access_token']}"}
        items2 = httpx.get(f"{WORKBENCH}/roleplay/characters", headers=wh, timeout=30).json()[
            "items"
        ]
        aid = items2[0]["asset_id"]
        r3 = httpx.post(
            f"{WORKBENCH}/roleplay/chat",
            headers=wh,
            json={
                "character_asset_ids": [aid],
                "messages": [{"role": "user", "content": "你好"}],
                "model": "grok-chat-fast",
            },
            timeout=120,
        )
        resp = r3.json()
        if resp.get("error"):
            print("grok 通道仍失败:", resp["error"][:120])
            return 2
        print("grok-chat-fast 恢复 ✅ 回复:", resp.get("reply", "")[:60])
        return 0

    print("暂无可配额账号（导入的 token 可能已过期或缺少有效会话）")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
