# ruff: noqa: T201
"""自动化创作验证：用真实模型（cpa gpt-oss-120b-medium）完整创作一部作品。

流程：建项目（2 角色卡）→ 大纲 5 章 → 逐章叙事生成 → 剧本模式 1 章
→ 主编剧情方向 → 剧务角色状态 → 导出 markdown。
"""

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
MODEL = "gpt-oss-120b-medium"
ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
OUT_PATH = Path(__file__).resolve().parents[4] / "晨星山物语.md"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(("PASS" if cond else "FAIL"), name, detail[:200] if detail else "")


def get_env(k: str) -> str:
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    raise KeyError(k)


def post(c: httpx.Client, h: dict, path: str, body: dict, retries: int = 3) -> dict:
    """带 429 退避重试的 POST。"""
    for i in range(retries):
        r = c.post(path, headers=h, json=body)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 and i < retries - 1:
            wait = 10 * (i + 1)
            print(f"  429 限流，等待 {wait}s 重试…")
            time.sleep(wait)
            continue
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    return {"error": "重试耗尽"}


def main() -> None:
    user, pwd = get_env("INITIAL_ADMIN_USERNAME"), get_env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=300, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 0. 清理旧项目
    for p in c.get("/story/projects", headers=h).json().get("items", []):
        if p["title"] == "晨星山物语":
            c.delete(f"/story/projects/{p['id']}", headers=h)
            print("已清理旧《晨星山物语》")

    # 1. 建项目（露娜 + 一只会魔法的）
    chars = c.get("/roleplay/characters", headers=h).json()["items"]
    names = [ch.get("name") for ch in chars]
    check("角色卡就绪", len(chars) >= 2, str(names))
    asset_ids = [ch["asset_id"] for ch in chars[:2]]
    r = post(
        c,
        h,
        "/story/projects",
        {
            "title": "晨星山物语",
            "genre": "奇幻冒险",
            "synopsis": (
                "少女露娜是晨星山脚下咖啡店的店主，与黑猫洛根共同生活。"
                "传说晨星山巅的星辉每百年凝聚一次，能实现一个愿望；"
                "本作讲述露娜与洛根登山寻找星辉、揭晓身世之谜的冒险。"
            ),
            "character_asset_ids": asset_ids,
        },
    )
    pid = r["project"]["id"]
    check("项目创建", bool(pid))

    # 2. 大纲 5 章（真实模型）
    r = c.post(f"/story/projects/{pid}/outline?chapters=5&model={MODEL}", headers=h)
    body = r.json()
    chapters = body.get("chapters") or []
    check("大纲生成（真实模型）", r.status_code == 200 and len(chapters) == 5, r.text[:160])
    for ch in chapters[:3]:
        print(f"  大纲 第{ch['chapter_no']}章《{ch['title']}》：{ch['outline'][:60]}")

    # 3. 逐章叙事生成（真实模型）
    for ch in chapters:
        r = post(
            c,
            h,
            f"/story/chapters/{ch['id']}/generate",
            {
                "project_id": pid,
                "mode": "narrative",
                "model": MODEL,
                "max_tokens": 1500,
            },
        )
        if "error" in r:
            check(f"章节{ch['chapter_no']}生成", False, str(r.get("error"))[:120])
            continue
        check(f"章节{ch['chapter_no']}《{ch['title']}》生成", True, f"{r.get('word_count')} 字")
        time.sleep(1)  # 限流缓冲

    # 4. 剧本模式 1 章（群聊引擎，双角色）
    r = c.post(
        f"/story/projects/{pid}/chapters",
        headers=h,
        json={
            "title": "山巅之夜（剧本）",
            "outline": "露娜与洛根在山顶仰望星辉，一场对话揭示彼此的秘密。",
        },
    ).json()
    sid = r["chapter"]["id"]
    r = post(
        c,
        h,
        f"/story/chapters/{sid}/generate",
        {
            "project_id": pid,
            "mode": "script",
            "model": MODEL,
            "rounds": 6,
        },
    )
    if "error" in r:
        check("剧本章节生成", False, str(r.get("error"))[:120])
    else:
        check("剧本章节生成（群聊）", True, f"{r.get('turns')} 轮对话 · {r.get('word_count')} 字")

    # 5. 创作团队：主编 + 剧务（真实模型）
    r = post(
        c,
        h,
        f"/story/projects/{pid}/crew",
        {
            "project_id": pid,
            "stage": "director",
            "model": MODEL,
        },
    )
    check(
        "主编剧情方向",
        "error" not in r and bool(r.get("direction")),
        str(r.get("direction", ""))[:100],
    )
    r = post(
        c,
        h,
        f"/story/projects/{pid}/crew",
        {
            "project_id": pid,
            "stage": "stagehand",
            "model": MODEL,
        },
    )
    check(
        "剧务角色状态", "error" not in r, json.dumps(r.get("states", []), ensure_ascii=False)[:120]
    )

    # 6. 导出 markdown
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "markdown"})
    if r.status_code == 200:
        OUT_PATH.write_text(r.text, encoding="utf-8")
        total = sum(
            ch.get("word_count") or 0
            for ch in c.get(f"/story/projects/{pid}/chapters", headers=h).json().get("items", [])
        )
        check("导出 markdown", True, f"{OUT_PATH} · 全书 {total} 字")
    else:
        check("导出 markdown", False, r.text[:120])

    # 7. 最终书目统计
    items = c.get(f"/story/projects/{pid}/chapters", headers=h).json().get("items", [])
    print("\n== 成书目录 ==")
    for ch in sorted(items, key=lambda x: x["chapter_no"]):
        print(f"  第{ch['chapter_no']}章《{ch['title']}》 {ch['status']} {ch['word_count']}字")
    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
