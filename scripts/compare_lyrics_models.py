"""对比实验：DeepSeek vs grok-4.6 写歌词质量（同一 prompt 同一主题）。"""
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
                        "temperature": 0.9,
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
    prompt = _COMPOSE_PROMPT.format(
        theme=theme,
        style="民谣",
        mood="克制温暖",
        language="中文",
        verse_count=2,
        style_profile=_STYLE_PROFILES["民谣"],
    )

    # DeepSeek（平台默认）：key 从 provider_configs 解密
    import pymysql

    conn = pymysql.connect(
        host="127.0.0.1", port=int(env["MYSQL_PORT"]), user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"], database=env["MYSQL_DATABASE"], charset="utf8mb4",
    )
    cur = conn.cursor()
    cur.execute("SELECT base_url, encrypted_api_key, default_model FROM provider_configs WHERE name='DeepSeek'")
    row = cur.fetchone()
    conn.close()
    from app.core.config import settings
    from app.security.ownership import open_secret

    ds_key = open_secret(row[1]) or "none"
    ds_model = row[2] or "deepseek-v4-pro"

    models = [
        ("DeepSeek", "https://api.deepseek.com/v1", ds_key, ds_model),
        ("Grok-4.6", "http://127.0.0.1:8000", env.get("OPENAI_COMPATIBLE_API_KEY", "none"), "grok-4.6"),
    ]
    for name, base, key, model in models:
        print(f"\n{'='*50}\n### {name} ({model})\n{'='*50}")
        raw = await generate(base, key, model, prompt)
        if raw.startswith("ERROR"):
            print(raw)
            continue
        data = extract_json(raw)
        if data.get("error"):
            print("解析失败:", data["error"])
            continue
        data["lyrics"] = _repair_lyrics(str(data.get("lyrics") or ""))
        checks = _validate_lyrics(str(data.get("lyrics") or ""))
        print(f"歌名《{data.get('title')}》 自检 {len(checks)} 项:")
        for c in checks:
            print("  -", c[:60])
        print((data.get("lyrics") or "")[:1200])


if __name__ == "__main__":
    asyncio.run(main())
