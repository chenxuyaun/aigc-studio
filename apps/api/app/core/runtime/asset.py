"""Core Runtime - Asset 资源格式。

从 services/task_runner.py 拆出：
- _EXT_MIME：扩展名 → MIME 映射

P0 边界：task_runner.py 通过 `from app.core.runtime.asset import ...` 使用。
"""
from __future__ import annotations

# 文件扩展名 → MIME 映射（与 providers/media.render_for 输出格式一致）。
EXT_MIME: dict[str, str] = {"svg": "image/svg+xml", "wav": "audio/wav"}
