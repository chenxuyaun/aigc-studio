"""联网搜索层（SearXNG→Bing RSS→Wikipedia 三层兜底）+ 创作素材兜底检索。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.knowledge_materials import (
    _digest_web_results,
    retrieve_creation_materials,
)
from app.services.web_search import search_web

# ---------- 逐层兜底顺序 ----------


@pytest.mark.asyncio
async def test_search_web_uses_searxng_zh_first():
    """SearXNG zh-CN 有结果：直接用，不触发后续层。"""
    with (
        patch(
            "app.services.web_search._search_searxng",
            new=AsyncMock(return_value=[{"title": "a", "url": "u", "content": "c"}]),
        ),
        patch("app.services.web_search._search_wikipedia") as m_wiki,
    ):
        out = await search_web("矿工", limit=3)
    assert out and out[0]["title"] == "a"
    assert m_wiki.await_count == 0


@pytest.mark.asyncio
async def test_search_web_zh_empty_then_en_locale():
    """SearXNG zh-CN 空 → 自动试 en locale。"""
    zh_hits, en_hits = [], [{"title": "Miner", "url": "https://en.example", "content": "coal miner"}]
    with patch(
        "app.services.web_search._search_searxng",
        new=AsyncMock(side_effect=lambda q, lim, lang: en_hits if lang == "en" else zh_hits),
    ) as m_sx, patch("app.services.web_search._search_wikipedia") as m_wiki:
        out = await search_web("矿工", limit=3)
    assert out == en_hits
    langs = [c.args[2] for c in m_sx.await_args_list]
    assert langs == ["zh-CN", "en"]
    assert m_wiki.await_count == 0


@pytest.mark.asyncio
async def test_search_web_falls_back_to_wikipedia_when_searxng_empty():
    """SearXNG 两个 locale 都空 → Wikipedia 兜底。"""
    wiki_items = [{"title": "维基百科·矿工", "url": "https://zh.wikipedia.org", "content": "…"}]
    with (
        patch("app.services.web_search._search_searxng", new=AsyncMock(return_value=[])),
        patch("app.services.web_search._search_wikipedia", new=AsyncMock(return_value=wiki_items)),
    ):
        out = await search_web("矿工", limit=3)
    assert out == wiki_items


@pytest.mark.asyncio
async def test_search_web_all_fail_returns_empty():
    """全部失败：返回空，不抛异常（创作不阻塞）。"""
    with (
        patch("app.services.web_search._search_searxng", side_effect=RuntimeError("down")),
        patch("app.services.web_search._search_wikipedia", side_effect=RuntimeError("down")),
    ):
        assert await search_web("矿工") == []


@pytest.mark.asyncio
async def test_search_web_empty_query():
    assert await search_web("  ") == []


# ---------- 搜索结果的「读懂」加工 ----------


@pytest.mark.asyncio
async def test_digest_web_results_llm_ok(client):
    items = [
        {"title": "矿井安全", "url": "https://example.com/a", "content": "井下气体检测要点…"},
        {"title": "煤矿历史", "url": "https://example.com/d", "content": "山西煤矿百年史…"},
    ]
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": json.dumps({"notes": ["- 井下靠气体检测保命（矿井安全）", "- 山西煤史百年（煤矿历史）"]})}
    )()
    fake_resolver.model = "mock"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        out = await _digest_web_results(None, "矿工", items)
    assert "气体检测" in out and "煤史" in out


@pytest.mark.asyncio
async def test_digest_web_results_falls_back_to_raw(client):
    """LLM 加工失败：原样截断拼接兜底（事实仍可用，不阻塞）。"""
    items = [
        {"title": "矿井安全", "url": "https://example.com/a", "content": "井下气体检测要点…"},
    ]
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.side_effect = RuntimeError("llm down")
    fake_resolver.model = "mock"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        out = await _digest_web_results(None, "矿工", items)
    assert "矿井安全" in out


@pytest.mark.asyncio
async def test_retrieve_creation_materials_web_even_with_kb_hits(client):
    """知识库有强命中 + use_web=True：知识库照常注入，联网照常补充（勾选即搜）。"""
    strong = [
        ("d1", "卖炭翁（人民性·叙事）", "可怜身上衣正单，心忧炭贱愿天寒。", 5),
        ("d2", "茅屋为秋风所破歌（民生关怀）", "布衾多年冷似铁。", 4),
        ("d3", "石壕吏（叙事白描）", "老妪力虽衰，请从吏夜归。", 4),
    ]
    web_items = [{"title": "海上风电", "url": "https://example.com/sea", "content": "百米塔筒检修规程…"}]
    with (
        patch("app.services.knowledge_materials._retrieve_kb_hits", new=AsyncMock(return_value=strong)),
        patch("app.services.web_search.search_web", new=AsyncMock(return_value=web_items)) as m_search,
    ):
        kb_text, kb_titles, web_text, web_titles = await retrieve_creation_materials(
            None, "admin", "海上风电运维工", limit=3, use_web=True
        )
    assert m_search.await_count == 1
    assert kb_text and len(kb_titles) == 3
    assert web_titles and web_titles[0].startswith("🌐 ")


async def test_retrieve_creation_materials_no_web_when_disabled(client):
    """use_web=False：即使知识库命中不足也不触发联网搜索。"""
    with (
        patch("app.services.knowledge_materials._retrieve_kb_hits", new=AsyncMock(return_value=[])),
        patch("app.services.web_search.search_web") as m_search,
    ):
        kb_text, kb_titles, web_text, web_titles = await retrieve_creation_materials(
            None, "admin", "深海采矿装备", limit=3, use_web=False
        )
    m_search.assert_not_awaited()
    assert kb_text == "" and web_text == "" and web_titles == []


@pytest.mark.asyncio
async def test_retrieve_creation_materials_web_when_enabled(client):
    """use_web=True：无条件触发搜索并注入（带 🌐 前缀标题）。"""
    with (
        patch("app.services.knowledge_materials._retrieve_kb_hits", new=AsyncMock(return_value=[])),
        patch("app.services.web_search.search_web") as m_search,
    ):
        m_search.return_value = [
            {"title": "深海采矿", "url": "https://example.com/sea", "content": "深海采矿装备与环保争议…"}
        ]
        fake_resolver = AsyncMock()
        fake_resolver.provider.generate.return_value = type(
            "R", (), {"content": json.dumps({"notes": ["- 深海采矿有环保争议（深海采矿）"]})}
        )()
        fake_resolver.model = "mock"
        with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
            kb_text, kb_titles, web_text, web_titles = await retrieve_creation_materials(
                None, "admin", "深海采矿装备", limit=3, use_web=True
            )
    m_search.assert_awaited_once()
    assert web_text and "环保争议" in web_text
    assert web_titles and web_titles[0].startswith("🌐 ")


@pytest.mark.asyncio
async def test_retrieve_creation_materials_web_error_silent(client):
    """搜索抛异常：静默降级，返回空，不阻塞创作。"""
    with (
        patch("app.services.knowledge_materials._retrieve_kb_hits", new=AsyncMock(return_value=[])),
        patch("app.services.web_search.search_web", side_effect=RuntimeError("searxng down")),
    ):
        kb_text, kb_titles, web_text, web_titles = await retrieve_creation_materials(
            None, "admin", "深海采矿装备", limit=3, use_web=True
        )
    assert web_text == "" and web_titles == []


# ---------- 搜索前检索词提取 ----------


@pytest.mark.asyncio
async def test_theme_search_query_short_theme_passthrough():
    """短主题（≤20 字）直接原样返回，不做 LLM 调用。"""
    from app.services.knowledge_materials import _theme_search_query

    assert await _theme_search_query(None, "歌颂您，同志") == "歌颂您，同志"


@pytest.mark.asyncio
async def test_theme_search_query_llm_extracts():
    """长主题：LLM 压缩成核心检索词。"""
    from unittest.mock import AsyncMock, patch

    from app.services.knowledge_materials import _theme_search_query

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": '{"query": "海上风电场运维"}'}
    )()
    fake_resolver.model = "mock"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        out = await _theme_search_query(
            None,
            "海上风电场运维工：台风前夜爬 100 米塔筒检修叶片，对讲机里是家人的声音",
        )
    assert out == "海上风电场运维"
    assert len(out) <= 30


@pytest.mark.asyncio
async def test_theme_search_query_llm_fail_passthrough():
    """LLM 提取失败：原样返回主题（搜索链路不中断）。"""
    from unittest.mock import AsyncMock, patch

    from app.services.knowledge_materials import _theme_search_query

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.side_effect = RuntimeError("llm down")
    fake_resolver.model = "mock"
    theme = "码头装卸工老陈：凌晨三点扛包，把工钱分一半寄回老家"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        out = await _theme_search_query(None, theme)
    assert out == theme


# ---------- 通用圆桌定稿结构自检 ----------


def test_validate_final_flags_missing_fields():
    from app.services.roundtable_service import _severe_domain_checks, _validate_final

    w = _validate_final("copy", {"title": "", "content": "太短"})
    assert any("缺少标题" in x for x in w)
    assert any("偏短" in x for x in w)
    assert _severe_domain_checks(w)


def test_validate_final_ok_case():
    from app.services.roundtable_service import _validate_final

    good = {"title": "标题", "content": "正" * 400, "style": "风格"}
    assert _validate_final("copy", good) == []
    assert _validate_final("image", {"title": "画面", "content": "主体" * 120}) == []
