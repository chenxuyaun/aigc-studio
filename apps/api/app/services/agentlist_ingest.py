"""AgentList 目录接入服务：下载 llms-full.txt → 解析 → 幂等入库。

数据源：https://www.agentlist.top/llms-full.txt（站点官方 LLM 摄取全量 dump，
含 31 个 PK 对比表、75 篇长文、1484 个项目元数据索引）。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agentlist import AgentArticle, AgentComparison, AgentProject

FULL_URL = "https://www.agentlist.top/llms-full.txt"
SYNC_TIMEOUT = 180

_RE_URL = re.compile(r"^- URL:\s*(.+)$", re.MULTILINE)
_RE_GITHUB = re.compile(r"^- GitHub:\s*(.+)$", re.MULTILINE)
_RE_HOMEPAGE = re.compile(r"^- Homepage:\s*(.+)$", re.MULTILINE)
_RE_DESC = re.compile(r"^- Description:\s*(.+)$", re.MULTILINE)
_RE_CATS = re.compile(r"^- Categories:\s*(.+)$", re.MULTILINE)
_RE_TAGS = re.compile(r"^- Tags:\s*(.+)$", re.MULTILINE)
_RE_STARS = re.compile(r"^- GitHub stars:\s*([\d,]+)", re.MULTILINE)
_RE_LANG = re.compile(r"^- Language:\s*(.+)$", re.MULTILINE)
_RE_LICENSE = re.compile(r"^- License:\s*(.+)$", re.MULTILINE)
_RE_PROJECTS = re.compile(r"^- Projects compared:\s*(.+)$", re.MULTILINE)
_RE_RELATED = re.compile(r"^- Related projects:\s*(.+)$", re.MULTILINE)


def _g(regex: re.Pattern[str], text: str) -> str:
    """取正则第一个捕获组（无匹配返回空串）。"""
    m = regex.search(text)
    return m.group(1).strip() if m else ""


def _parse_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


async def fetch_full_text() -> str:
    async with httpx.AsyncClient(timeout=SYNC_TIMEOUT, follow_redirects=True) as client:
        r = await client.get(FULL_URL, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.text


def _parse_project_block(block: list[str]) -> dict[str, Any]:
    text = "\n".join(block)
    name = block[0].removeprefix("### ").strip()
    stars_txt = _g(_RE_STARS, text)
    return {
        "name": name,
        "url": _g(_RE_URL, text),
        "github_url": _g(_RE_GITHUB, text),
        "homepage_url": _g(_RE_HOMEPAGE, text),
        "description": _g(_RE_DESC, text),
        "categories": json.dumps(_parse_list(_g(_RE_CATS, text)), ensure_ascii=False),
        "tags": json.dumps(_parse_list(_g(_RE_TAGS, text)), ensure_ascii=False),
        "stars": int(stars_txt.replace(",", "")) if stars_txt else 0,
        "language": _g(_RE_LANG, text),
        "license": _g(_RE_LICENSE, text),
    }


def parse_full_text(text: str) -> dict[str, list[dict[str, Any]]]:
    """按三大段解析：对比表 / 长文 / 项目索引。"""
    lines = text.splitlines()
    # 定位段边界
    idx_board = next(i for i, ln in enumerate(lines) if ln.startswith("## 1. PK Comparison"))
    idx_articles = next(i for i, ln in enumerate(lines) if ln.startswith("## 2. Long-form"))
    # 项目索引段：标题为 "## 3. Project Index"（文章内部小节也可能以 "## 3." 开头，
    # 但完整标题唯一）
    idx_meta = None
    for i in range(len(lines) - 1, 0, -1):
        if lines[i].startswith("## 3. Project Index"):
            idx_meta = i
            break
    if idx_meta is None:
        # 兜底：取文章段之后所有 "### " 块
        idx_meta = idx_articles

    board_text = "\n".join(lines[idx_board:idx_articles])
    art_text = "\n".join(lines[idx_articles:idx_meta])
    meta_text = "\n".join(lines[idx_meta:])

    comparisons: list[dict[str, Any]] = []
    for block in _split_blocks(board_text):
        if not block[0].startswith("### "):
            continue
        text = "\n".join(block)
        # 对比表条目特征：含 URL 与 Projects compared
        if "- Projects compared:" not in text or "- URL:" not in text:
            continue
        title = block[0].removeprefix("### ").strip()
        comparisons.append(
            {
                "title": title,
                "url": _g(_RE_URL, text),
                "description": _g(_RE_DESC, text),
                "categories": json.dumps(_parse_list(_g(_RE_CATS, text)), ensure_ascii=False),
                "projects": json.dumps(_parse_list(_g(_RE_PROJECTS, text)), ensure_ascii=False),
                "content": text,
            }
        )

    articles: list[dict[str, Any]] = []
    for block in _split_blocks(art_text):
        if not block[0].startswith("### "):
            continue
        text = "\n".join(block)
        # 长文条目特征：含 URL 且不含 GitHub（区分于项目索引/对比表）
        if "- URL:" not in text or "- GitHub:" in text:
            continue
        title = block[0].removeprefix("### ").strip()
        articles.append(
            {
                "title": title,
                "url": _g(_RE_URL, text),
                "description": _g(_RE_DESC, text),
                "categories": json.dumps(_parse_list(_g(_RE_CATS, text)), ensure_ascii=False),
                "related_projects": json.dumps(
                    _parse_list(_g(_RE_RELATED, text)), ensure_ascii=False
                ),
                "content": text,
            }
        )

    projects: list[dict[str, Any]] = []
    for block in _split_blocks(meta_text):
        if not block[0].startswith("### "):
            continue
        # 项目条目特征：含 GitHub 链接
        if "- GitHub:" not in "\n".join(block):
            continue
        projects.append(_parse_project_block(block))

    return {"comparisons": comparisons, "articles": articles, "projects": projects}


def _split_blocks(text: str) -> list[list[str]]:
    """按 '### ' 二级块切分（保留块内所有行，含正文多段）。"""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("### "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


async def sync_agentlist(db: AsyncSession, text: str | None = None) -> dict[str, int]:
    """下载并幂等入库（按 name/title upsert）。"""
    if text is None:
        text = await fetch_full_text()
    parsed = parse_full_text(text)
    counts = {"projects": 0, "articles": 0, "comparisons": 0}

    # 项目
    existing = set(
        (await db.execute(select(AgentProject.name))).scalars().all()
    )
    for p in parsed["projects"]:
        if not p["name"]:
            continue
        if p["name"] in existing:
            await db.execute(
                update(AgentProject)
                .where(AgentProject.name == p["name"])
                .values(**{k: v for k, v in p.items() if k != "name"})
            )
        else:
            db.add(AgentProject(**p))
            existing.add(p["name"])
        counts["projects"] += 1

    # 文章
    existing_art = set((await db.execute(select(AgentArticle.title))).scalars().all())
    for a in parsed["articles"]:
        if not a["title"]:
            continue
        if a["title"] in existing_art:
            await db.execute(
                update(AgentArticle)
                .where(AgentArticle.title == a["title"])
                .values(**{k: v for k, v in a.items() if k != "title"})
            )
        else:
            db.add(AgentArticle(**a))
            existing_art.add(a["title"])
        counts["articles"] += 1

    # 对比表
    existing_cmp = set((await db.execute(select(AgentComparison.title))).scalars().all())
    for c in parsed["comparisons"]:
        if not c["title"]:
            continue
        if c["title"] in existing_cmp:
            await db.execute(
                update(AgentComparison)
                .where(AgentComparison.title == c["title"])
                .values(**{k: v for k, v in c.items() if k != "title"})
            )
        else:
            db.add(AgentComparison(**c))
            existing_cmp.add(c["title"])
        counts["comparisons"] += 1

    await db.commit()
    return counts


async def count_agentlist(db: AsyncSession) -> dict[str, int]:
    return {
        "projects": (await db.execute(select(func.count()).select_from(AgentProject))).scalar()
        or 0,
        "articles": (await db.execute(select(func.count()).select_from(AgentArticle))).scalar()
        or 0,
        "comparisons": (
            await db.execute(select(func.count()).select_from(AgentComparison))
        ).scalar()
        or 0,
    }
