# ruff: noqa: T201 E501
"""Story Forge 创作引擎真实 E2E：项目→大纲→章节→剧本→团队→连载→导出→流式。

BASE 指向线上 8002（nginx 代理 api），使用 .env 的 INITIAL_ADMIN 凭据。
"""
import json
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(("PASS" if cond else "FAIL"), name, detail[:160] if detail else "")


def get_env(k: str) -> str:
    with open(_ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    raise KeyError(k)


def main() -> None:
    user, pwd = get_env("INITIAL_ADMIN_USERNAME"), get_env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=120, base_url=BASE)
    r = c.post("/auth/login", json={"username": user, "password": pwd})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 1. 项目创建（带两张角色卡：露娜 + 一只会魔法的）
    chars = c.get("/roleplay/characters", headers=h).json()["items"]
    check("characters ready", len(chars) >= 2, f"count={len(chars)}")
    asset_ids = [ch["asset_id"] for ch in chars[:2]]
    r = c.post("/story/projects", headers=h, json={
        "title": "晨星山物语（E2E）",
        "genre": "奇幻冒险",
        "synopsis": "少女露娜与黑猫洛根登上晨星山，揭开星辉的秘密。",
        "character_asset_ids": asset_ids,
    })
    pid = r.json()["project"]["id"]
    check("project created", bool(pid) and r.json()["project"]["status"] == "drafting")

    # 2. 生成大纲（3 章）
    r = c.post(f"/story/projects/{pid}/outline", headers=h, params={"chapters": 3})
    body = r.json()
    chapters = body.get("chapters") or []
    check("outline generated", r.status_code == 200 and len(chapters) == 3, r.text[:120])
    cid1 = chapters[0]["id"]
    check("outline has titles", bool(chapters[0].get("title")))  # mock 模式下 outline 内容可能为空

    # 3. 叙事模式生成章节（mock provider：快速验证链路）
    r = c.post(f"/story/chapters/{cid1}/generate", headers=h, json={
        "project_id": pid, "mode": "narrative", "model": "",
    })
    gen = r.json()
    check("narrative chapter generated", "error" not in gen and gen.get("status") == "done", r.text[:120])
    check("chapter content saved", bool(gen.get("content")), f"words={gen.get('word_count')}")

    # 4. 剧本模式生成（群聊引擎，多角色）
    r = c.post(f"/story/projects/{pid}/chapters", headers=h, json={"title": "山顶夜话", "outline": "两位角色在山顶相遇"})
    cid2 = r.json()["chapter"]["id"]
    r = c.post(f"/story/chapters/{cid2}/generate", headers=h, json={
        "project_id": pid, "mode": "script", "rounds": 4, "model": "",
    })
    script = r.json()
    check("script chapter generated", "error" not in script and script.get("turns", 0) >= 1, r.text[:120])
    names = [ch.get("name") for ch in chars[:2]]
    has_both = all(n in (script.get("content") or "") for n in names if n)
    check("script has both speakers", has_both, script.get("content", "")[:80])

    # 5. 修订
    r = c.post(f"/story/chapters/{cid1}/revise", headers=h,
               params={"instruction": "把开头改为夜晚场景", "model": ""})
    check("chapter revised", r.status_code == 200 and bool(r.json().get("content")), r.text[:100])

    # 6. 创作团队：主编 → 剧务
    r = c.post(f"/story/projects/{pid}/crew", headers=h, json={"project_id": pid, "stage": "director"})
    check("crew director", r.status_code == 200 and bool(r.json().get("direction")), r.text[:100])
    r = c.post(f"/story/projects/{pid}/crew", headers=h, json={"project_id": pid, "stage": "stagehand"})
    check("crew stagehand", r.status_code == 200, r.text[:100])
    bible = c.get(f"/story/projects/{pid}/bible", headers=h).json()
    check("bible aggregate", len(bible["chapters"]) >= 3 and len(bible["characters"]) >= 1)

    # 7. 流式生成（SSE）
    r3 = c.post(f"/story/projects/{pid}/chapters", headers=h, json={"title": "流式章"})
    cid3 = r3.json()["chapter"]["id"]
    with c.stream("POST", f"/story/chapters/{cid3}/generate/stream", headers=h,
                  json={"project_id": pid, "mode": "narrative"}) as sr:
        sse = "".join(sr.iter_text())
    has_chunk = '"type": "chunk"' in sse
    has_done = '"type": "done"' in sse
    check("stream chunks + done", has_chunk and has_done, sse[:100])

    # 8. 连载调度 + tick（在 worker 容器内直接触发 beat 任务）
    r = c.post(f"/story/projects/{pid}/schedules", headers=h, json={
        "interval_minutes": 30, "batch_size": 1, "mode": "narrative",
    })
    check("schedule created", r.status_code == 200, r.text[:100])
    import subprocess

    # 把 next_run_at 拨到过去，验证 tick 真的会生成下一章
    # （注意：async def 不能跟在分号后，用换行分隔语句）
    backdate = (
        "import asyncio\n"
        "from datetime import UTC, datetime, timedelta\n"
        "from sqlalchemy import update\n"
        "from app.models.serial_schedule import SerialSchedule\n"
        "from app.core.database import AsyncSessionLocal\n"
        "async def m():\n"
        "    async with AsyncSessionLocal() as db:\n"
        "        await db.execute(update(SerialSchedule).values("
        "next_run_at=datetime.now(UTC)-timedelta(minutes=1)))\n"
        "        await db.commit()\n"
        "asyncio.run(m())"
    )
    subprocess.run(
        ["docker", "exec", "aigc-studio-worker-1", "python", "-c", backdate],
        capture_output=True, text=True, timeout=60, check=True,
    )
    out = subprocess.run(
        ["docker", "exec", "aigc-studio-worker-1", "python", "-c",
         "from app.tasks.story_tasks import serial_tick; print(serial_tick())"],
        capture_output=True, text=True, timeout=120,
    )
    tick = out.stdout.strip()
    check("serial tick ran", "created" in tick, tick[:100])
    r = c.get(f"/story/projects/{pid}/schedules", headers=h)
    sched = r.json()["items"][0]
    check("schedule chapter_count advanced", sched["chapter_count"] >= 1, json.dumps(sched)[:120])

    # 9. 导出
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "markdown"})
    check("export markdown", r.status_code == 200 and "晨星山物语" in r.text, r.text[:60])
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "jsonl"})
    check("export jsonl", r.status_code == 200 and r.text.splitlines()[0].startswith("{"))
    cd = r.headers.get("content-disposition", "")
    check("export filename RFC5987", "filename*=" in cd, cd[:80])

    # 10. 项目级世界书
    r = c.post("/roleplay/lore", headers=h, json={
        "project_id": pid, "keywords": ["晨星山"], "content": "晨星山由星辉凝结而成。",
        "selective": True,
    })
    check("project lore created", r.status_code == 200, r.text[:80])
    r = c.get(f"/roleplay/lore?project_id={pid}", headers=h)
    check("project lore filtered", len(r.json()["items"]) == 1)
    r = c.get("/roleplay/lore", headers=h)
    check("lore default excludes project", all(i.get("project_id") != pid for i in r.json()["items"]))

    # 11. 任务化章节生成（后台任务 → 终态）
    r = c.post(f"/story/projects/{pid}/chapters", headers=h, json={"title": "任务化章"})
    cid4 = r.json()["chapter"]["id"]
    r = c.post(f"/story/chapters/{cid4}/generate/task", headers=h, json={
        "project_id": pid, "mode": "narrative", "model": "",
    })
    task_id = r.json()["task"]["id"]
    import time

    status = "queued"
    for _ in range(40):
        r = c.get(f"/tasks/{task_id}", headers=h)
        status = r.json().get("status") or ""
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    check("taskized chapter terminal", status in ("succeeded", "failed"), f"status={status}")

    # 清理
    c.delete(f"/story/projects/{pid}", headers=h)
    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
