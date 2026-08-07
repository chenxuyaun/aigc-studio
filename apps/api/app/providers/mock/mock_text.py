import asyncio
import random
from collections.abc import AsyncIterator

from app.providers.base import TextProvider, TextResult


class MockTextProvider(TextProvider):
    MOCK_TEXT = (
        "这是一段由 Mock Provider 生成的示例文本。在生产环境中，这里会显示真实 AI 模型生成的内容。"
    )

    async def generate(
        self,
        prompt: str,
        model: str = "mock",
        tools: list[dict[str, object]] | None = None,
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> TextResult:
        await asyncio.sleep(random.randint(300, 1000) / 1000)
        return TextResult(
            content=f"【Mock 响应】\n\n用户输入：{prompt}\n\n{self.MOCK_TEXT}",
            model=model,
            provider="mock",
        )

    async def stream_generate(
        self,
        prompt: str,
        model: str = "mock",
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        text = f"【Mock 流式响应】\n\n用户输入：{prompt}\n\n{self.MOCK_TEXT}"
        for word in text:
            yield word
            await asyncio.sleep(random.randint(20, 80) / 1000)
