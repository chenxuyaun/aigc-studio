"""文本故障转移 Provider：按候选顺序降级，主选失败自动换下一家。

模型中心 text 槽位链（slots_chain）>1 时由 provider_resolver 包装使用，
对上层完全透明——generate/stream_generate 签名与 OpenAICompatibleTextProvider 一致。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog

from app.providers.base import TextResult

logger = structlog.get_logger()


class FailoverTextProvider:
    """组合多个 TextProvider 候选；generate 逐个尝试直到成功。"""

    def __init__(self, providers: list[Any]) -> None:
        if not providers:
            raise ValueError("FailoverTextProvider 需要至少一个候选 provider")
        self._providers = providers

    async def generate(
        self,
        prompt: str,
        model: str = "default",
        tools: list[dict[str, object]] | None = None,
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> TextResult:
        last_exc: Exception | None = None
        for i, p in enumerate(self._providers):
            # 主选沿用解析出的模型名；备选传空让其用自身 default_model——
            # 各候选的模型名属于各自供应商（如 cpa 的 gpt-oss 与 OpenRouter 的
            # stealth/* 互不认识），把主选模型名传给备选必然 400。
            use_model = model if i == 0 else ""
            try:
                result = await p.generate(
                    prompt,
                    model=use_model,
                    tools=tools,
                    system=system,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                )
                if i > 0:
                    logger.info(
                        "text_failover_used",
                        candidate=f"{i + 1}/{len(self._providers)}",
                        model=getattr(result, "model", "") or use_model or "default",
                    )
                return result
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "text_failover_next",
                    failed_candidate=i + 1,
                    error=(str(exc).strip() or type(exc).__name__)[:140],
                    remaining=len(self._providers) - i - 1,
                )
        assert last_exc is not None
        raise last_exc

    async def stream_generate(
        self,
        prompt: str,
        model: str = "default",
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """流式降级：拿到首个 chunk 才算「选定」该候选；首字节前失败自动换下一家。

        已开始输出后的中途失败无法无缝重放，按原样抛出（与单 provider 行为一致）。
        """
        last_exc: Exception | None = None
        for i, p in enumerate(self._providers):
            use_model = model if i == 0 else ""  # 备选用自身 default_model（模型名不跨供应商）
            agen = p.stream_generate(
                prompt,
                model=use_model,
                system=system,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )
            try:
                first = await agen.__anext__()
            except StopAsyncIteration:
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "text_failover_next",
                    failed_candidate=i + 1,
                    phase="stream_first_byte",
                    error=(str(exc).strip() or type(exc).__name__)[:140],
                    remaining=len(self._providers) - i - 1,
                )
                continue
            if i > 0:
                logger.info("text_failover_used", candidate=f"{i + 1}/{len(self._providers)}", model=model)
            try:
                yield first
                async for chunk in agen:
                    yield chunk
            finally:
                await agen.aclose()
            return
        if last_exc is not None:
            raise last_exc
