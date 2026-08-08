# ruff: noqa: E501
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.generation import MusicGenerationRequest, TaskResponse
from app.security.auth import get_current_user
from app.services.generation_service import create_media_task
from app.services.provider_resolver import resolve_text_provider

router = APIRouter()


class MusicComposeRequest(BaseModel):
    """AI 写歌：主题 → 原创歌词 + 风格描述（供 Suno/网易天音等免费合成）。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="流行", max_length=100)
    mood: str = Field(default="治愈", max_length=100)
    language: str = Field(default="中文", max_length=50)
    verse_count: int = Field(default=2, ge=1, le=4)
    model: str = ""  # 空 = 自动选择文本 Provider（cpa）


# 各风格专属的歌词特征与制作参数（解决"都是一个调调"：风格差异必须体现在歌词里）
_STYLE_PROFILES: dict[str, str] = {
    "古风": "歌词特征：化用古典诗词与典故（如《诗经》、宋词意象），文言词句与白话自然交织，"
            "意象用山水/舟楫/锦书/烛影等古典符号但要有新意，可带戏曲唱腔感的衬词；"
            "制作：五声调式（宫商角徵羽）色彩、笛/箫/古筝/琵琶、慢板 60-80 BPM、空灵混响",
    "中国风": "歌词特征：现代口语为主，融入传统意象（茶/巷/檐/信笺/灯火）做隐喻，"
              "副歌有一句可流传的金句，兼具流行传唱度与东方韵味；"
              "制作：流行编曲骨架+民乐点缀（二胡/笛子/古筝）、80-100 BPM、副歌渐强",
    "民谣": "歌词特征：叙事诗式白描，像在讲一个真实的故事（具体地名/职业/物件），"
            "冷峻克制的情感，留白多于抒情，允许方言/口语颗粒感；"
            "制作：木吉他/口琴/手风琴、70-90 BPM、贴近话筒的人声",
    "流行": "歌词特征：强记忆点的副歌 hook（一句重复金句），主歌铺垫情绪，"
            "词汇现代年轻化，允许英文单词点缀，节奏与呼吸贴合旋律感；"
            "制作：现代流行编曲（合成器+鼓机+贝斯）、90-120 BPM、副歌能量拉满",
    "R&B": "歌词特征：律动驱动，句子按节拍切分（像在说话中摇摆），暧昧氛围与细腻情绪，"
           "副歌用旋律性强的假声感语句；制作：Trap/R&B 鼓点、慢速 60-80 BPM、滑音与和声堆叠",
    "电子": "歌词特征：短句+重复性短语（适合循环），意象偏未来/霓虹/城市夜景/代码，"
            "副歌有口号式的爆发句；制作：合成器琶音/808 低音/侧链压缩、110-130 BPM、Drop 落差",
    "摇滚": "歌词特征：直接有力，有反叛或呐喊的张力，允许粗粝口语，副歌是能量爆发点，"
            "意象偏公路/工厂/城市/青春；制作：电吉他失真/鼓组密集、120-160 BPM、失真与破音",
    "爵士": "歌词特征：慵懒机敏，像即兴对话，押韵灵活（内韵/斜韵），场景感强（酒吧/雨夜/雪茄），"
            "副歌是旋律性回旋句；制作：钢琴/贝斯/萨克斯/刷鼓、60-100 BPM、swing 律动",
    "嘻哈": "歌词特征：flow 优先，句尾双押/内韵，叙事带态度（街头/奋斗/生活观察），"
            "副歌是一段可跟唱的 hook；制作：鼓机/采样/808、80-100 BPM、切分节奏",
    "治愈系": "歌词特征：温柔抚慰的意象（光/窗/怀抱/雨停），像对朋友说话，短句+呼吸感，"
              "副歌是一句温暖肯定的反复；制作：钢琴/弦乐/原声吉他、60-80 BPM、宽广混响",
}

# 长行提示词模板：E501 通过 noqa 豁免（可读性优先于行宽）
_COMPOSE_PROMPT = """你是顶级的词曲创作人 + 音乐制作人，为独立音乐人写一首有质感的歌。严格输出 JSON（不要任何多余文字）：

{{
  "title": "歌名（2-6 字，有记忆点，避免烂大街词汇）",
  "style_zh": "中文制作说明（100-200 字：编曲思路/乐器层次/节奏型/人声处理/段落动态设计）",
  "style_en": "英文风格描述（40-80 词，给 Suno 等 AI 音乐工具：genre/era/instruments/tempo/BPM/key/mood/arrangement/energy curve）",
  "lyrics": "完整歌词（用 \\n 分行，标注【主歌1】【副歌】【主歌2】【桥段】【副歌】），总长 260-450 字",
  "tips": "一句使用建议（Suno/天音如何设置生成）"
}}

【文学性要求（提升文化底蕴）】
1. 文采：善用通感、拟人、虚实相生等修辞；至少一处让人"心头一动"的妙句
2. 古典修养：可化用古诗词/典故/成语的反转用法，但务必自然不生硬
3. 层次：字面一层、情感一层、回味一层——避免一眼看透
4. 留白：不要写满，给听众想象空间

【风格专属特征（必须严格遵守，这是你区别于其它风格的核心）】
{style_profile}

【通用歌词铁律】
1. 画面感：每句有具体场景/动作/感官细节，禁止空泛抒情
2. 叙事推进：主歌1 铺场景 → 主歌2 转折/新细节 → 桥段升华，副歌是情绪爆点
3. 副歌钩子：重复性金句，朗朗上口
4. 押韵自然：不硬凑，允许隔句押/换韵；禁止"~呀~啦"网络腔
5. 意象新颖：避开被用烂的"月亮/星星/流星/大海"直白组合
6. 口语化真诚：像真人说话，允许留白与感叹词

要求：
- 主题：{theme}
- 风格：{style}
- 情绪：{mood}
- 语言：{language}
- 副歌 {verse_count} 段
- style_en 必须全英文，直接可粘贴给 AI 音乐工具"""


def _extract_json(text: str) -> dict[str, Any]:
    """容错解析 LLM 输出的 JSON（剥离 markdown 代码块/前后杂文本）。"""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"error": "AI 输出解析失败", "raw": text[:500]}


@router.post("/compose", response_model=None)
async def compose_song(
    req: MusicComposeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """AI 写歌（免费）：主题 → 原创歌词 + 风格描述 JSON。走平台文本 Provider（cpa）。"""
    style_profile = _STYLE_PROFILES.get(req.style, _STYLE_PROFILES["流行"])
    prompt = _COMPOSE_PROMPT.format(
        theme=req.theme, style=req.style, mood=req.mood,
        language=req.language, verse_count=req.verse_count,
        style_profile=style_profile,
    )
    resolved = await resolve_text_provider(db, req.model)
    provider = resolved.provider
    # 温度 0.95：增加每次生成的风格/表达差异（避免"都是一个调调"）
    result = await provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, temperature=0.95
    )
    if isinstance(result, dict):
        text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        text = str(result.content)
    else:
        text = str(result)
    data = _extract_json(text)
    data["provider"] = resolved.model
    return data


@router.post("/generate", response_model=TaskResponse)
async def generate_music(
    req: MusicGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskResponse:
    """音乐生成任务（MusicGen 等 HF 音频模型，prompt 描述风格/情绪/乐器）。"""
    task = await create_media_task(
        db, user_id=user.id, task_type="music", model=req.model, params=req
    )
    return TaskResponse.model_validate(task)
