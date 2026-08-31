"""Core Runtime - Music 业务引擎包（P1-1 从 api/v1/generations/music.py 抽离）。

子模块：
- style.py      风格画像 / 同义词检测（纯函数）
- quality.py    歌词质量门：结构修复 / 自检 / 严重度 / 十三辙韵表（纯函数）
- textproc.py   LLM 输出 JSON 容错解析 + 讨论记录转写（纯函数）
- prompts.py    全部提示词模板 + 任务构造器（纯文本）
- engine.py     文本 LLM 编排：写歌质量闭环 / 圆桌选角·议程·发言·定稿 / 心跳 / 限流
- works.py      作品落库 + 知识库回填（DB 副作用）

P1 边界：app.api.v1.generations.music 保留薄路由 + 兼容再导出（旧 import 路径不破坏）。
P4 计划：本包随 applications/creation 归位（与 comic_bridge 同模式）。
"""
from app.core.runtime.music import engine, works  # noqa: F401
from app.core.runtime.music.prompts import (  # noqa: F401
    _CAST_PROMPT,
    _COMPOSE_PROMPT,
    _DISCUSS_SYSTEM,
    _FINAL_PROMPT,
    _FIX_LIST_PROMPT,
    _ROUNDTABLE_PROMPT,
)
from app.core.runtime.music.quality import (  # noqa: F401
    _is_antithetical_hook,
    _repair_lyrics,
    _segment_text,
    _severe_checks,
    _strip_tag,
    _syllable_count,
    _tail_char,
    _validate_lyrics,
)
from app.core.runtime.music.style import (  # noqa: F401
    _STYLE_ALIASES,
    _STYLE_PROFILES,
    _detect_style,
    _style_profile_block,
)
from app.core.runtime.music.textproc import (  # noqa: F401
    _extract_json,
    _shuffled_transcript,
    _transcript,
    _transcript_block,
)
