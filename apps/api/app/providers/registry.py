"""Provider 注册表：按配置分发真实 / Mock Provider。

切换逻辑：
- DEFAULT_*_PROVIDER 环境变量控制默认 provider（mock | huggingface | openai_compatible）
- 前端可在请求中通过 model/provider 字段覆盖
- 真实 Provider 失败时自动回退 Mock（带日志），保证演示不中断
"""

from app.core.config import settings
from app.providers.base import ImageProvider, SpeechProvider, TextProvider, VideoProvider
from app.providers.mock.mock_image import MockImageProvider
from app.providers.mock.mock_speech import MockSpeechProvider
from app.providers.mock.mock_text import MockTextProvider
from app.providers.mock.mock_video import MockVideoProvider


class ProviderRegistry:
    # ── 文本 ─────────────────────────────────────────────────────────
    @classmethod
    def get_text_provider(cls, name: str = "") -> TextProvider:
        provider = name or settings.DEFAULT_TEXT_PROVIDER
        if provider in {"openai_compatible", "grok", "grok2api"}:
            from app.providers.openai_compatible import OpenAICompatibleTextProvider

            return OpenAICompatibleTextProvider()
        if provider == "huggingface":
            from app.providers.huggingface import HuggingFaceTextProvider

            return HuggingFaceTextProvider()
        return MockTextProvider()

    # ── 图像 ─────────────────────────────────────────────────────────
    @classmethod
    def get_image_provider(
        cls,
        name: str = "",
        *,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
    ) -> ImageProvider:
        """按 name / 默认配置解析图像 Provider。

        name 可为：
        - mock
        - huggingface
        - grok / grok2api / openai_compatible（本地 OpenAI 兼容网关）
        - 具体 HF 模型 id（含 /），同样走 HuggingFaceImageProvider
        base_url/api_key/default_model 来自 DB ProviderConfig 解析（覆盖 env 兜底）。
        """
        raw = (name or settings.DEFAULT_IMAGE_PROVIDER).strip()
        key = raw.lower()
        if key in {"", "mock"}:
            return MockImageProvider()
        if key in {"grok", "grok2api", "openai_compatible"}:
            from app.providers.openai_compatible import OpenAICompatibleImageProvider

            return OpenAICompatibleImageProvider(
                base_url=base_url, api_key=api_key, default_model=default_model
            )
        if key == "huggingface" or "/" in raw:
            from app.providers.huggingface import HuggingFaceImageProvider

            # 传具体模型 id；仅写 huggingface 时用 HF 默认 SDXL
            model = "" if key == "huggingface" else raw
            return HuggingFaceImageProvider(model=model) if model else HuggingFaceImageProvider()
        # 未知 id：不默认 HF（曾导致 Grok 显示名/配置 id 误路由到 HF 报鉴权错），
        # 无配置时返回 Mock，由调用方按 DB 配置路由
        return MockImageProvider()

    # ── 视频（grok2api /videos/generations；模型恢复后自动走真实链路）──
    @classmethod
    def get_video_provider(
        cls,
        name: str = "",
        *,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
    ) -> VideoProvider:
        raw = (name or settings.DEFAULT_VIDEO_PROVIDER).strip()
        if raw.lower() in {"", "mock"}:
            return MockVideoProvider()
        if raw.lower() in {"grok", "grok2api", "openai_compatible"}:
            from app.providers.openai_compatible import OpenAICompatibleVideoProvider

            return OpenAICompatibleVideoProvider(
                base_url=base_url, api_key=api_key, default_model=default_model
            )
        return MockVideoProvider()

    # ── 语音 ─────────────────────────────────────────────────────────
    @classmethod
    def get_speech_provider(cls, name: str = "") -> SpeechProvider:
        provider = name or settings.DEFAULT_SPEECH_PROVIDER
        if provider == "huggingface":
            from app.providers.huggingface import HuggingFaceSpeechProvider

            return HuggingFaceSpeechProvider()
        if provider in {"edge_tts", "edge-tts", "edge"}:
            from app.providers.edge_tts import EdgeTTSSpeechProvider

            return EdgeTTSSpeechProvider()
        return MockSpeechProvider()
