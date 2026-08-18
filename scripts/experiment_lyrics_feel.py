"""实验 2：DeepSeek + 歌词感强化 prompt（few-shot 范例 + 韵律/句长硬约束）。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "apps/api"))

from app.api.v1.generations.music import (  # noqa: E402
    _COMPOSE_PROMPT,
    _STYLE_PROFILES,
    _repair_lyrics,
    _validate_lyrics,
)

_LYRICS_FEEL_BLOCK = """
【歌词感铁律】（这是"歌"，不是分行散文——检验标准是能否跟着拍子哼唱）
1. 句长：每句 5-12 字为主，单句禁超 15 字；长句拆短（超过就是散文，不是歌词）
2. 押韵：每段至少 2 处句尾押韵；副歌句句押或隔句押，句尾字各不相同（禁整段押同一个字）；押不上就自然断句，禁硬凑单字
3. 副歌 4 句：第 1-2 句是最抓耳的 hook（能独立反复跟唱），第 3-4 句收束；两遍副歌内容一致（第二遍可微调）
4. 节奏：读出来有呼吸感，像人说话有轻重缓急；禁止一句塞多个并列信息
5. 韵律范例（模仿其节奏与押韵结构，禁止照抄内容）：
   - 「和我在成都的街头走一走 / 直到所有的灯都熄灭了也不停留」（10字+12字，走/留押韵）
   - 「越过山丘 / 才发现无人等候」（4字+7字，丘/候押韵）
   - 「我曾经跨过山和大海 / 也穿过人山人海」（11字+8字，海/海重复=双关收束）
6. 写完后自我检验：每段能跟着拍子哼出来吗？句尾能押上吗？不能就重写这段
"""


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


async def generate(base_url: str, api_key: str, model: str, prompt: str) -> str:
    endpoint = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
    async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
        for attempt in range(3):
            try:
                r = await client.post(
                    f"{endpoint}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.85,
                    },
                )
                if r.status_code in (429, 502, 503) and attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                if attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))
                else:
                    return f"ERROR: {exc}"
    return "ERROR"


def extract_json(text: str) -> dict:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"error": "parse_fail", "raw": text[:200]}


async def main() -> None:
    env = _load_env()
    theme = "深夜十二点，便利店值班的店员给上夜班的姑娘留了一杯关东煮，杯子底下压了张字条"
    base_prompt = _COMPOSE_PROMPT.format(
        theme=theme,
        style="民谣",
        mood="克制温暖",
        language="中文",
        verse_count=2,
        style_profile=_STYLE_PROFILES["民谣"],
    )
    prompt = base_prompt + _LYRICS_FEEL_BLOCK

    import pymysql

    conn = pymysql.connect(
        host="127.0.0.1", port=int(env["MYSQL_PORT"]), user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"], database=env["MYSQL_DATABASE"], charset="utf8mb4",
    )
    cur = conn.cursor()
    cur.execute("SELECT encrypted_api_key, default_model FROM provider_configs WHERE name='DeepSeek'")
    row = cur.fetchone()
    conn.close()
    from app.security.ownership import open_secret

    ds_key = open_secret(row[0]) or "none"
    ds_model = row[1] or "deepseek-v4-pro"

    raw = await generate("https://api.deepseek.com/v1", ds_key, ds_model, prompt)
    if raw.startswith("ERROR"):
        print(raw)
        return
    data = extract_json(raw)
    if data.get("error"):
        print("解析失败:", data["error"])
        return
    data["lyrics"] = _repair_lyrics(str(data.get("lyrics") or ""))
    checks = _validate_lyrics(str(data.get("lyrics") or ""))
    print(f"DeepSeek + 歌词感强化 歌名《{data.get('title')}》 自检 {len(checks)} 项:")
    for c in checks:
        print("  -", c[:60])
    print()
    print((data.get("lyrics") or "")[:1400])


if __name__ == "__main__":
    asyncio.run(main())
