# ruff: noqa: T201
"""补跑《双城交换杀人》三项 503 失败项：案件设计 / 第3章 / 校对，带重试退避。"""

import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
# Grok 上游 403 风控中（14:06 起全账号被拒）→ 暂切 cpa 备用链路补跑
MODEL = "gpt-oss-120b-medium"
PID = "c49679e9-1d19-4638-bac5-f20640364466"
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


def post_retry(c: httpx.Client, h: dict, path: str, body: dict, tries: int = 6) -> dict:
    """POST 并重试：上游 503（Grok 过载）等 45s 递增退避。"""
    for i in range(tries):
        r = c.post(path, headers=h, json=body)
        if r.status_code == 200:
            return r.json()
        text = r.text[:160]
        print(f"  retry {i + 1}/{tries}: HTTP {r.status_code} {text}")
        if r.status_code in (400, 404, 422):
            return {"error": text}
        time.sleep(45 * (i + 1))
    return {"error": "重试耗尽"}


def main() -> None:
    user, pwd = env("INITIAL_ADMIN_USERNAME"), env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=600, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 1. 补跑案件设计（主编）
    r = post_retry(
        c,
        h,
        f"/story/projects/{PID}/crew",
        {
            "project_id": PID,
            "stage": "director",
            "model": MODEL,
        },
    )
    check(
        "案件设计（主编）",
        "error" not in r and bool(r.get("direction")),
        str(r.get("direction", ""))[:100],
    )

    # 2. 补跑第 3 章生成
    r = post_retry(
        c,
        h,
        "/story/chapters/86a300ef-f165-4da0-ac34-6065939bcaaa/generate",
        {
            "project_id": PID,
            "mode": "narrative",
            "model": MODEL,
            "max_tokens": 1600,
        },
    )
    if "error" in r:
        check("章节3生成（补跑）", False, str(r.get("error"))[:120])
    else:
        check("章节3生成（补跑）", True, f"{r.get('word_count')} 字")

    # 3. 补跑校对（逻辑验证）
    r = post_retry(
        c,
        h,
        f"/story/projects/{PID}/crew",
        {
            "project_id": PID,
            "stage": "editor",
            "model": MODEL,
            "chapter_id": "86a300ef-f165-4da0-ac34-6065939bcaaa",
        },
    )
    if "error" in r:
        check("推理逻辑验证（校对）", False, str(r.get("error"))[:120])
    else:
        check("推理逻辑验证（校对）", True, str(r.get("review", ""))[:100])

    # 4. 重新导出（覆盖含第 3 章的全本）
    r = c.get(f"/story/projects/{PID}/export", headers=h, params={"format": "markdown"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.md").write_text(r.text, encoding="utf-8")
        total = sum(
            ch.get("word_count") or 0
            for ch in c.get(f"/story/projects/{PID}/chapters", headers=h).json().get("items", [])
        )
        check("导出 markdown", True, f"全书 {total} 字")
    else:
        check("导出 markdown", False, r.text[:120])
    r = c.get(f"/story/projects/{PID}/export", headers=h, params={"format": "epub"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.epub").write_bytes(r.content)
        check("导出 epub", True, f"{len(r.content)} bytes")
    else:
        check("导出 epub", False, r.text[:120])

    items = c.get(f"/story/projects/{PID}/chapters", headers=h).json().get("items", [])
    print("\n== 成书目录 ==")
    for ch in sorted(items, key=lambda x: x["chapter_no"]):
        print(f"  第{ch['chapter_no']}章《{ch['title']}》 {ch['status']} {ch['word_count']}字")
    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
