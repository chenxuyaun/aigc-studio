# ruff: noqa: T201 E501
"""第二轮质检修订：针对读者终评发现的 3 个问题定向修订 → 重导出 → 终评复评。

问题清单：
1. 死因冲突（硬伤）：第1章法医报告「致命性脑出血+颅骨45°手术切口」vs 第8章贺青自白「刀背割喉」
2. 凶器使用方式：手术钢刀应为开颅手法，与前文医学鉴定统一
3. 白鷉身份：磁带标签人物 → 第9章实体登场缺铺垫
"""

import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
CHAT = "http://localhost:8002/v1/chat/completions"
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
    user, pwd = env("INITIAL_ADMIN_USERNAME"), env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=600, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    items = c.get("/story/projects", headers=h).json().get("items", [])
    proj = next((p for p in items if p["title"] == "双城交换杀人"), None)
    if proj is None:
        print("项目未找到")
        sys.exit(1)
    pid = proj["id"]
    chs = c.get(f"/story/projects/{pid}/chapters", headers=h).json().get("items", [])
    by_no = {ch["chapter_no"]: ch for ch in chs}

    # 定向修订指令（终评问题的权威修复方案）
    instructions = {
        8: (
            "修订本章的凶案描述，消除与法医报告的死因冲突（终评硬伤）：\n"
            "1. 贺青的自白改为：他用那把手术钢刀，以当年在 Z 城矿工医院学到的开颅手法"
            "（45° 弧线切口）结束了陈启明与魏延之的生命——与第 1 章法医报告"
            "『致命性脑出血、颅骨 45° 手术切口』完全一致；删除『刀背割喉』『血液喷洒』等喉部创口描写。\n"
            "2. 保留自白的情感张力与心理转折（矿难遗孤、复仇、规则），只改死法描述。\n"
            "3. 若文中提到凶器用法与『手术』相关的其他段落，一并统一为开颅手法。"
        ),
        1: (
            "修订本章法医报告的表述，为后续真相统一留出接口：\n"
            "1. 保持『致命性脑出血、颅骨 45° 手术切口、凶器为手术钢刀（同批次 Z 城器械）』的鉴定结论；\n"
            "2. 在法医报告的结尾补一句伏笔：『创口角度与某种专业手术路径高度一致』——"
            "暗示凶手具备医学背景，为第 8 章贺青的自白（开颅手法）做铺垫；\n"
            "3. 不改动其他内容与时间戳。"
        ),
        9: (
            "修订本章白鷉的登场方式，消除『磁带标签 vs 实体人物』的身份模糊：\n"
            "1. 白鷉登场前，秦澜或顾之南先交代一句：『白鷉此前只存在于磁带与信件里——"
            "现在他本人站在这里』，明确读者认知：匿名投稿人第一次以实体出现；\n"
            "2. 白鷉递信的细节保留，但加上他『始终戴着旧式灰大衣兜帽』的描写，"
            "与第 1 章电梯监控的灰大衣呼应（暗示其与案发夜有关联）；\n"
            "3. 其他内容不变。"
        ),
    }

    for no, inst in sorted(instructions.items()):
        ch = by_no.get(no)
        if ch is None:
            check(f"第{no}章修订", False, "章节不存在")
            continue
        r = c.post(
            f"/story/chapters/{ch['id']}/revise",
            headers=h,
            params={"instruction": inst, "model": MODEL},
        )
        if r.status_code == 200:
            check(f"第{no}章修订", True, f"{r.json().get('word_count')} 字")
        else:
            check(f"第{no}章修订", False, r.text[:150])
        time.sleep(1)

    # 重导出
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "markdown"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.md").write_text(r.text, encoding="utf-8")
        check("导出 markdown", True, f"{len(r.text)} chars")
    else:
        check("导出 markdown", False, r.text[:120])
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "epub"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.epub").write_bytes(r.content)
        check("导出 epub", True, f"{len(r.content)} bytes")
    else:
        check("导出 epub", False, r.text[:120])

    # 终评复评
    picked = [c for c in chs if c["chapter_no"] in (1, 4, 6, 8, 9)]
    book = "".join(
        f"\n\n========== 第{c['chapter_no']}章《{c['title']}》 ==========\n{c.get('content') or ''}"
        for c in sorted(picked, key=lambda x: x["chapter_no"])
    )
    r = c.post(
        CHAT,
        headers=h,
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "你是阅读过两千部推理小说的资深读者。上轮终评你给了 7.9 分并指出三个问题：①死因冲突（脑出血+颅骨切口 vs 刀背割喉）②凶器使用方式 ③白鷉身份模糊。作者已按你的意见修订第 1/8/9 章。请复核：三个问题是否修复？总分（10 分制）？一句话总评？是否还有新的硬伤？",
                },
                {"role": "user", "content": f"修订后的核心章节（第1/4/6/8/9章）：\n{book}"},
            ],
            "max_tokens": 1200,
            "temperature": 0.6,
        },
    )
    final = r.json()["choices"][0]["message"]["content"]
    check("读者终评", bool(final), final[:100])
    print("--- 读者终评（第二轮） ---")
    print(final[:1600])
    (OUT_DIR / "双城交换杀人_终评2.md").write_text(final, encoding="utf-8")

    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
