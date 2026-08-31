"""Core Runtime - Story 基础层包（P1-3 从 api/v1/story.py 抽离）。

子模块：
- generation.py  章节生成 SSE 编排（断点续存草稿/正则后处理/质量预检/AI 腔体检）
- serial.py      自动连载排期 CRUD（直连 DB 的薄查询）

P1 边界：app.api.v1.story 保留薄路由（schema + handler 委托）。
P4 计划：本包随 applications/novel 归位。
"""
from app.core.runtime.story import generation, serial  # noqa: F401
