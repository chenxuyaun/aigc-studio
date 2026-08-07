"""Provider 路由测试：Grok 显示名/配置 id 不再误路由到 HuggingFace。"""

from __future__ import annotations

from app.providers.registry import ProviderRegistry


def test_image_provider_grok_names_route_correctly() -> None:
    """Grok 关键字/显示名/配置 id 均不得路由到 HuggingFace。"""
    for name in ("grok2api", "grok", "openai_compatible"):
        p = ProviderRegistry.get_image_provider(name)
        assert p.__class__.__name__ == "OpenAICompatibleImageProvider", name
    # 未知 id（配置显示名/UUID/默认模型名）：不默认 HF，落 Mock 由 DB 配置接管
    for name in (
        "Grok（本地 grok2api）",
        "1ec02dea-7c1f-464d-80a7-fa34e589d2ad",
        "grok-imagine-image",
    ):
        p = ProviderRegistry.get_image_provider(name)
        assert p.__class__.__name__ == "MockImageProvider", name


def test_image_provider_huggingface_still_routes() -> None:
    """HF 关键字与含 / 的模型 id 仍走 HuggingFace。"""
    p = ProviderRegistry.get_image_provider("huggingface")
    assert p.__class__.__name__ == "HuggingFaceImageProvider"
    p2 = ProviderRegistry.get_image_provider("black-forest-labs/FLUX.1-schnell")
    assert p2.__class__.__name__ == "HuggingFaceImageProvider"
