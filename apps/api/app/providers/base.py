from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel


class TextResult(BaseModel):
    content: str
    model: str = ""
    provider: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: list[dict[str, object]] | None = None


class TextProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str = "default",
        tools: list[dict[str, object]] | None = None,
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> TextResult: ...
    @abstractmethod
    async def stream_generate(
        self,
        prompt: str,
        model: str = "default",
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        yield ""


class ImageProvider(ABC):
    @abstractmethod
    async def submit(
        self, prompt: str, model: str = "default", **kwargs: object
    ) -> dict[str, object]: ...
    @abstractmethod
    async def poll(self, task_id: str) -> dict[str, object]: ...


class VideoProvider(ABC):
    @abstractmethod
    async def submit(
        self, prompt: str, model: str = "default", **kwargs: object
    ) -> dict[str, object]: ...
    @abstractmethod
    async def poll(self, task_id: str) -> dict[str, object]: ...


class SpeechProvider(ABC):
    @abstractmethod
    async def submit(
        self, text: str, model: str = "default", **kwargs: object
    ) -> dict[str, object]: ...
    @abstractmethod
    async def poll(self, task_id: str) -> dict[str, object]: ...
