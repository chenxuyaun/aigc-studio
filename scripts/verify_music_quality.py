"""实测验证：新歌词质量闭环（compose 链路）——真实调用 grok2api。

用法：uv run --project apps/api python ../scripts/verify_music_quality.py
"""
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
    _detect_style,
    _repair_lyrics,
    _severe_checks,
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


async def generate(base_url: str, api_key: str, model: str, prompt: str, temperature: float) -> str:
    endpoint = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
    async with httpx.AsyncClient(timeout=300) as client:
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                r = await client.post(
                    f"{endpoint}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                    },
                )
                if r.status_code in (429, 502, 503) and attempt < 3:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < 3:
                    await asyncio.sleep(3 * (attempt + 1))
        raise last_exc or RuntimeError("generate failed")


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        return {"error": "JSON 解析失败", "raw": text[:300]}


async def main() -> None:
    env = _load_env()
    base_url = "http://127.0.0.1:8000"  # 宿主访问 grok2api（.env 里是容器内地址 host.docker.internal:8317）
    api_key = env.get("OPENAI_COMPATIBLE_API_KEY", "none")
    # grok-chat-fast 上游暂 503，用可用的 grok-4.6 实测（脚本参数可覆盖：--model）
    model = sys.argv[1] if len(sys.argv) > 1 else "grok-4.6"

    theme = "矿工清晨下井前的半个小时，井口的热豆浆摊，他给相好的姑娘留了一杯"
    style = _detect_style(theme) or "民谣"
    print(f"主题：{theme}\n检测风格：{style}\n")

    prompt = _COMPOSE_PROMPT.format(
        theme=theme,
        style=style,
        mood="温暖克制",
        language="中文",
        verse_count=2,
        style_profile=_STYLE_PROFILES.get(style, _STYLE_PROFILES["流行"]),
    )
    raw = await generate(base_url, api_key, model, prompt, 0.95)
    data = extract_json(raw)
    if data.get("error"):
        print("首轮解析失败：", data["error"])
        return
    data["lyrics"] = _repair_lyrics(str(data.get("lyrics") or ""))
    checks = _validate_lyrics(str(data.get("lyrics") or ""))
    print(f"首轮自检（{len(checks)} 项警告）：")
    for c in checks:
        print("  -", c[:70])
    print()

    if _severe_checks(checks):
        print("== 严重问题 → 触发自动重写一轮 ==")
        rewrite_prompt = (
            prompt
            + "\n\n【上一轮自检警告】（本次为修正轮：必须逐条修正下列问题后再输出定稿，"
            "修正后的作品不得再出现同类问题）\n"
            + "\n".join(f"- {w}" for w in checks)
        )
        raw2 = await generate(base_url, api_key, model, rewrite_prompt, 0.7)
        data2 = extract_json(raw2)
        if not data2.get("error"):
            data2["lyrics"] = _repair_lyrics(str(data2.get("lyrics") or ""))
            data2["checks"] = _validate_lyrics(str(data2.get("lyrics") or ""))
            data = data2
            print(f"重写后自检（{len(data2['checks'])} 项警告）：")
            for c in data2["checks"]:
                print("  -", c[:70])
    print()
    print(f"歌名：《{data.get('title')}》")
    print("=" * 40)
    print(data.get("lyrics", ""))
    print("=" * 40)
    print(f"\nstyle_en: {data.get('style_en', '')[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
