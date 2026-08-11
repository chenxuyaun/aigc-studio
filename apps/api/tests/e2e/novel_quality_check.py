# ruff: noqa: T201 E501
"""小说质检流水线：一致性检查 → 按报告自动修订 → 读者终评。

流程（真实模型 cpa）：
1. crew consistency：全书一致性检查（角色名/时间线/事实物品/伏笔）
2. 让模型把报告拆成「每章修订指令」（结构化 JSON）
3. 逐章 revise 落地修订
4. 重新导出 md/epub
5. 读者视角终评（复评打分）
用法: python novel_quality_check.py [project_title]
"""

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
MODEL = "gpt-oss-120b-medium"
ENV_PATH = Path(r"D:\software\code\ideas\list\aigc-studio\.env")
OUT_DIR = Path(r"D:\software\code\ideas\list\aigc-studio")
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(("PASS" if cond else "FAIL"), name, detail[:150] if detail else "")


def env(k: str) -> str:
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    raise KeyError(k)


def main() -> None:
    title = sys.argv[1] if len(sys.argv) > 1 else "双城交换杀人"
    user, pwd = env("INITIAL_ADMIN_USERNAME"), env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=600, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 0. 找项目
    items = c.get("/story/projects", headers=h).json().get("items", [])
    proj = next((p for p in items if p["title"] == title), None)
    if proj is None:
        print("项目未找到:", title, "| 现有:", [p["title"] for p in items][:8])
        sys.exit(1)
    pid = proj["id"]
    print(f"项目: {title} ({pid[:8]})")

    # 1. 一致性检查
    r = c.post(
        f"/story/projects/{pid}/crew",
        headers=h,
        json={
            "project_id": pid,
            "stage": "consistency",
            "model": MODEL,
        },
    )
    if r.status_code != 200 or "error" in r.json():
        check("一致性检查", False, r.text[:150])
        sys.exit(1)
    report = r.json()["report"]
    check("一致性检查", True, f"{len(report)} 字符报告")
    print("--- 一致性报告摘要 ---")
    print(report[:1200])

    # 2. 让模型把报告拆成每章修订指令（带一次重试）
    plan = ""
    for attempt in range(2):
        r = c.post(
            "http://localhost:8002/v1/chat/completions",
            headers=h,
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": '你是推理小说修订编排器。把一致性审查报告转换为「每章修订指令」列表。只输出 JSON：{"chapters": [{"chapter_no": 1, "instruction": "..."}]}。没有问题的章节不要列出。',
                    },
                    {"role": "user", "content": f"报告：\n{report}"},
                ],
                "max_tokens": 1200,
                "temperature": 0.3,
            },
        )
        body = r.json()
        if r.status_code == 200 and "choices" in body:
            plan = body["choices"][0]["message"]["content"]
            break
        print(f"  chat retry {attempt + 1}: {r.status_code} {str(body)[:120]}")
        time.sleep(3)
    if not plan:
        check("修订计划生成", False, "模型未返回")
        sys.exit(1)
    plan_json = plan[plan.find("{") : plan.rfind("}") + 1]
    try:
        plan_data = json.loads(plan_json)
        rev_plan = plan_data.get("chapters") or []
    except Exception:
        rev_plan = []
        check("修订计划解析", False, plan[:150])
    check("修订计划解析", bool(rev_plan), f"{len(rev_plan)} 章待修订")
    print("修订计划:", json.dumps(rev_plan, ensure_ascii=False)[:400])

    # 3. 逐章修订
    chs = c.get(f"/story/projects/{pid}/chapters", headers=h).json().get("items", [])
    by_no = {ch["chapter_no"]: ch for ch in chs}
    for item in rev_plan:
        no = int(item.get("chapter_no") or 0)
        inst = str(item.get("instruction") or "").strip()
        ch = by_no.get(no)
        if ch is None or not inst:
            continue
        url = f"/story/chapters/{ch['id']}/revise"
        rr = c.post(url, headers=h, params={"instruction": inst, "model": MODEL})
        if rr.status_code == 200:
            check(f"第{no}章修订", True, f"{rr.json().get('word_count')} 字")
        else:
            check(f"第{no}章修订", False, rr.text[:120])
        time.sleep(1)

    # 4. 重新导出
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "markdown"})
    if r.status_code == 200:
        (OUT_DIR / f"{title}.md").write_text(r.text, encoding="utf-8")
        check("导出 markdown", True, f"{len(r.text)} chars")
    else:
        check("导出 markdown", False, r.text[:120])
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "epub"})
    if r.status_code == 200:
        (OUT_DIR / f"{title}.epub").write_bytes(r.content)
        check("导出 epub", True, f"{len(r.content)} bytes")
    else:
        check("导出 epub", False, r.text[:120])

    # 5. 读者终评（修订后核心章节复评）
    picked = [c for c in chs if c["chapter_no"] in (1, 4, 6, 8, 9)]
    book = "".join(
        f"\n\n========== 第{c['chapter_no']}章《{c['title']}》 ==========\n{c.get('content') or ''}"
        for c in sorted(picked, key=lambda x: x["chapter_no"])
    )
    r = c.post(
        "http://localhost:8002/v1/chat/completions",
        headers=h,
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "你是阅读过两千部推理小说的资深读者。你之前给《双城交换杀人》初稿打过 2.5 分，修订后打过 8.3 分。现在作者又做了全书一致性修订。请复核并给出终评：总分（10 分制）+ 一句话总评 + 是否仍存在未修复的一致性矛盾（有则列出）。",
                },
                {"role": "user", "content": f"修订后的核心章节（第1/4/6/8/9章）：\n{book}"},
            ],
            "max_tokens": 1200,
            "temperature": 0.6,
        },
    )
    final = r.json()["choices"][0]["message"]["content"]
    check("读者终评", bool(final), final[:100])
    print("--- 读者终评 ---")
    print(final[:1500])
    (OUT_DIR / f"{title}_终评.md").write_text(final, encoding="utf-8")

    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
