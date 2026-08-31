"""联网搜索层：SearXNG（zh-CN → en）→ Wikipedia API（zh → en）逐层兜底。

供创作流程兜底检索：素材库（主食：已读懂的文化素材）优先；联网（时蔬：新鲜
题材）只在知识库命中不足时补充。任何失败静默降级——创作不阻塞。

- SearXNG：用户本地部署（.env SEARXNG_URL，容器内 host.docker.internal:8891）。
  中文 locale 下部分引擎（ddg/google 等）返回空/验证页，故中文空时再试英文 locale；
  若代理出口可用则 ddg 等引擎正常出真实结果
- Wikipedia API：直连（无需 key），中文词条真实可靠，作为最终兜底
- 刻意不用 Bing RSS 等无鉴权接口：其对爬虫返回无关推荐内容，会污染创作

容器内通过 .env 的 SEARXNG_URL 指向宿主机（compose 已配 host.docker.internal）。
"""

from __future__ import annotations

import os
import re

import httpx

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8891").rstrip("/")
_TIMEOUT_SECONDS = 8.0
_MAX_RESULTS = 6
_WIKI_UA = "AigcStudioBot/1.0 (creative-material-retrieval; contact: local)"


def _clean(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """过滤无标题/无内容的结果，并剥掉内容里的 HTML 标签（wiki snippet 带 searchmatch 等）。"""
    out = []
    for i in items:
        content = re.sub(r"<[^>]+>", "", i.get("content") or "").strip()
        if i.get("title") and content and i.get("url"):
            out.append({"title": i["title"], "url": i["url"], "content": content})
    return out


async def _search_searxng(query: str, limit: int, language: str) -> list[dict[str, str]]:
    """SearXNG JSON API（用户本地部署）。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "language": language},
            headers={"User-Agent": "aigc-studio/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
    return _clean(
        [
            {
                "title": str(r.get("title") or "").strip(),
                "url": str(r.get("url") or "").strip(),
                "content": str(r.get("content") or "").strip(),
            }
            for r in (data.get("results") or [])[:limit]
        ]
    )


async def _search_wikipedia(query: str, limit: int) -> list[dict[str, str]]:
    """Wikipedia API 直连（无需 key；中文优先，空则英文）。"""
    for lang in ("zh", "en"):
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": limit,
                    "format": "json",
                    "utf8": "1",
                },
                headers={"User-Agent": _WIKI_UA},
            )
            resp.raise_for_status()
            data = resp.json()
        items = _clean(
            [
                {
                    "title": f"维基百科·{s.get('title', '')}",
                    "url": f"https://{lang}.wikipedia.org/wiki/{s.get('title', '').replace(' ', '_')}",  # noqa: E501
                    "content": (s.get("snippet") or "").strip(),
                }
                for s in (data.get("query", {}).get("search") or [])[:limit]
            ]
        )
        if items:
            return items
    return []


async def search_web(query: str, limit: int = _MAX_RESULTS) -> list[dict[str, str]]:
    """联网搜索（逐层兜底）：SearXNG zh-CN → SearXNG en → Wikipedia zh/en。

    每一层失败或空结果都自动降级下一层；全部失败返回空列表——创作流程
    不因搜索失败而中断（调用方已有知识库主食兜底）。
    """
    if not query.strip():
        return []
    for language in ("zh-CN", "en"):
        try:
            items = await _search_searxng(query, limit, language)
            if items:
                return items
        except Exception:
            pass
    try:
        return await _search_wikipedia(query, limit)
    except Exception:
        return []
