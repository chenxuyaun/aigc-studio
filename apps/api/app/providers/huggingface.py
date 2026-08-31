# ruff: noqa: F401
# P2-2 薄 facade：实现已迁 app.providers.models.huggingface，旧 import 路径保持兼容。
from app.providers.models.huggingface import (
    HuggingFaceImageProvider,
    HuggingFaceSpeechProvider,
    HuggingFaceTextProvider,
)
