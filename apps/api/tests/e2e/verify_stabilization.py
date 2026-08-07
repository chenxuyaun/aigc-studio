# ruff: noqa: T201 E501
"""稳定化升级线上验证（httpx 实现，避免 urllib 偶发卡死）。"""
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
ENV_PATH = Path(r"D:\software\code\ideas\list\aigc-studio\.env")
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(("PASS" if cond else "FAIL"), name, detail[:120])


def env(k: str) -> str:
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    raise KeyError(k)


def main() -> None:
    c = httpx.Client(timeout=60, base_url=BASE)
    token = c.post("/auth/login", json={
        "username": env("INITIAL_ADMIN_USERNAME"), "password": env("INITIAL_ADMIN_PASSWORD"),
    }).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 1. worker 模式：image 任务（mock，走 celery worker 执行）
    r = c.post("/generations/image/generate", headers=h,
               json={"model": "mock", "prompt": "星夜猫", "width": 512, "height": 512}).json()
    tid = r["id"]
    st = ""
    for _ in range(240):
        r = c.get(f"/tasks/{tid}", headers=h).json()
        st = r.get("status") or ""
        if st in ("succeeded", "failed"):
            break
        time.sleep(2)
    check("image 任务由 worker 执行", st == "succeeded", f"status={st}")

    # 2. chapter 任务走 worker
    r = c.post("/story/projects", headers=h, json={"title": "稳定化验证", "genre": "测试"}).json()
    pid = r["project"]["id"]
    cid = c.post(f"/story/projects/{pid}/chapters", headers=h, json={"title": "第一章"}).json()["chapter"]["id"]
    rt = c.post(f"/story/chapters/{cid}/generate/task", headers=h,
                json={"project_id": pid, "mode": "narrative"}).json()
    st = ""
    for _ in range(240):
        r = c.get(f"/tasks/{rt['task']['id']}", headers=h).json()
        st = r.get("status") or ""
        if st in ("succeeded", "failed"):
            break
        time.sleep(2)
    check("chapter 任务由 worker 执行", st == "succeeded", f"status={st}")

    # 3. bible 摘要（content 截断）
    b = c.get(f"/story/projects/{pid}/bible", headers=h).json()
    chs = b["chapters"]
    check("bible 摘要列表", len(chs) == 1 and chs[0].get("content_truncated") is False)
    full = c.get(f"/story/chapters/{cid}", headers=h).json()["chapter"]
    check("章节详情含全文", len(full.get("content") or "") > 50)

    # 4. EPUB 导出
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "epub"})
    check("EPUB 导出", r.status_code == 200 and r.content[:4] == b"PK\x03\x04",
          f"{len(r.content)} bytes")

    # 5. catalog health 字段
    r = c.get("/providers/catalog", headers=h)
    items = r.json() if isinstance(r.json(), list) else []
    check("catalog healthy 字段", all("healthy" in p for p in items),
          str([(p["id"][:8], p.get("healthy")) for p in items[:3]]))

    # 6. 级联删 lore
    c.post("/roleplay/lore", headers=h, json={
        "project_id": pid, "keywords": ["测试"], "content": "t", "selective": True,
    })
    c.delete(f"/story/projects/{pid}", headers=h)
    left = c.get(f"/roleplay/lore?project_id={pid}", headers=h).json()["items"]
    check("删项目级联删 lore", len(left) == 0, f"残留 {len(left)} 条")

    # 7. 流式生成（SSE）正常完成并定稿
    rp = c.post("/story/projects", headers=h, json={"title": "流式验证", "genre": "测试"}).json()
    pid2 = rp["project"]["id"]
    cid2 = c.post(f"/story/projects/{pid2}/chapters", headers=h, json={"title": "流式章"}).json()["chapter"]["id"]
    with c.stream("POST", f"/story/chapters/{cid2}/generate/stream", headers=h,
                  json={"project_id": pid2, "mode": "narrative"}) as sr:
        sse = "".join(sr.iter_text())
    check("流式生成完成", '"type": "done"' in sse, sse[:80])
    full2 = c.get(f"/story/chapters/{cid2}", headers=h).json()["chapter"]
    check("流式结果落库", full2["status"] == "done" and len(full2.get("content") or "") > 20)
    c.delete(f"/story/projects/{pid2}", headers=h)

    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
