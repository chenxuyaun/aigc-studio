from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.config import settings


class TextGenerationRequest(BaseModel):
    model: str = Field(default_factory=lambda: settings.DEFAULT_TEXT_PROVIDER)
    messages: list[dict[str, str]] = Field(default_factory=list, max_length=200)
    prompt: str = Field(default="", max_length=50_000)
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    stream: bool = True
    # 知识库 RAG：限定在这些文档内检索，命中片段注入提示词（空/None 表示不启用）
    knowledge_doc_ids: list[str] | None = Field(default=None, max_length=100)
    knowledge_max_chunks: int = Field(default=3, ge=1, le=6)


class AgentChatRequest(BaseModel):
    """智能体对话（工具调用）：结构化 messages + 可选工具白名单。"""

    model: str = Field(default_factory=lambda: settings.DEFAULT_TEXT_PROVIDER)
    messages: list[dict[str, object]] = Field(max_length=200)
    tools: list[str] | None = Field(default=None, max_length=50)  # 省略 = 全部工具


class ImageGenerationRequest(BaseModel):
    model: str = Field(default_factory=lambda: settings.DEFAULT_IMAGE_PROVIDER)
    prompt: str = Field(max_length=50_000)
    negative_prompt: str = Field(default="", max_length=50_000)
    width: int = Field(default=1024, ge=64, le=2048)
    height: int = Field(default=1024, ge=64, le=2048)
    num_images: int = Field(default=1, ge=1, le=4)
    # 高级参数：seed 固定可复现；cfg_scale/steps 对真实模型生效（mock 仅用 seed 定色）
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    cfg_scale: float | None = Field(default=None, ge=1.0, le=20.0)
    steps: int | None = Field(default=None, ge=1, le=100)
    # 预留：写真/素材参考（P1 接通；mock 可忽略像素）
    reference_photo_id: str | None = None
    reference_asset_id: str | None = None


class VideoGenerationRequest(BaseModel):
    model: str = Field(default_factory=lambda: settings.DEFAULT_VIDEO_PROVIDER)
    prompt: str = Field(default="", max_length=50_000)
    duration: int = Field(default=5, ge=1, le=60)


class AudioGenerationRequest(BaseModel):
    model: str = Field(default_factory=lambda: settings.DEFAULT_SPEECH_PROVIDER)
    text: str = Field(max_length=50_000)
    voice: str = Field(default="default", max_length=100)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class MusicGenerationRequest(BaseModel):
    """音乐生成（MusicGen 等 HF 音频模型）：自然语言描述风格/情绪/乐器。"""

    model: str = Field(default_factory=lambda: settings.DEFAULT_SPEECH_PROVIDER)
    prompt: str = Field(max_length=50_000)
    # MusicGen 时长由 max_new_tokens 控制（~30s 默认）；预留 duration 便于后续扩展
    duration_seconds: int = Field(default=30, ge=5, le=120)


class ComicGenerationRequest(BaseModel):
    """漫画生成：分镜（文本模型）→ 逐格出图（图片模型）→ PIL 拼合。"""

    prompt: str = Field(max_length=50_000)
    panels: int = Field(default=4, ge=4, le=9)
    style: str = Field(default="日式漫画", max_length=500)
    characters: str = Field(default="", max_length=5000)
    layout: str = Field(default="grid", pattern="^(grid|manga)$")  # grid（网格）| manga（条漫）
    model: str = Field(default_factory=lambda: settings.DEFAULT_IMAGE_PROVIDER)


class RegisterBatchRequest(BaseModel):
    """注册机批次触发参数。"""

    run_count: int = Field(default=10, ge=1, le=100)


class TaskResponse(BaseModel):
    id: str
    task_type: str
    status: str
    progress: int
    result: str
    model: str
    error_message: str
    # 创建时写入的参数 JSON 字符串，供任务中心「再次运行」回填。
    params: str = "{}"
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
