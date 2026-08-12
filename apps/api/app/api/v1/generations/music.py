# ruff: noqa: E501
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.generation import MusicGenerationRequest, TaskResponse
from app.security.auth import get_current_user
from app.services.generation_service import create_media_task
from app.services.provider_resolver import resolve_text_provider
from app.services.text_utils import result_text as _provider_text
from app.services.text_utils import sse_event as _sse_event

router = APIRouter()


class MusicComposeRequest(BaseModel):
    """AI 写歌：主题 → 原创歌词 + 风格描述（供 Suno/网易天音等免费合成）。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="流行", max_length=100)
    mood: str = Field(default="治愈", max_length=100)
    language: str = Field(default="中文", max_length=50)
    verse_count: int = Field(default=2, ge=1, le=4)
    model: str = ""  # 空 = 自动选择文本 Provider（cpa）


class MusicDiscussRequest(BaseModel):
    """音乐讨论室：多轮对话式共创（主题/歌词/编曲/乐理，AI 基于上下文迭代）。"""

    messages: list[dict[str, str]] = Field(min_length=1, max_length=30)
    style: str = Field(default="", max_length=100)  # 可选：固定风格后讨论
    use_web: bool = False  # 首轮注入联网素材（知识库不足时）
    model: str = ""


class MusicRoundtableRequest(BaseModel):
    """多角色圆桌：四位 AI 创作者（作词/作曲/制作/乐评）围绕主题相互讨论后定稿。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="", max_length=100)  # 可选：指定风格基调
    mood: str = Field(default="", max_length=100)  # 可选：情绪基调
    quick: bool = False  # 快速模式：3 轮迷你讨论（约 25 秒）
    use_web: bool = False  # 知识库命中不足时联网搜索兜底（新鲜题材）
    model: str = ""


class MusicFollowupRequest(BaseModel):
    """圆桌定稿后追问：全员基于讨论+定稿回应一个问题，产出新定稿。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="", max_length=100)
    cast: list[dict[str, Any]] = Field(default_factory=list)
    rounds: list[dict[str, str]] = Field(default_factory=list)
    final: dict[str, Any] | None = None
    question: str = Field(min_length=1, max_length=500)
    use_web: bool = False  # 追问轮同样可补充联网素材
    model: str = ""


class MusicToChatRequest(BaseModel):
    """把作品发布到创作群。"""

    chat_id: str = Field(min_length=8, max_length=64)


class MusicWorkSaveRequest(BaseModel):
    """手动保存一首作品（写歌/讨论室成品）。"""

    title: str = Field(default="未命名", max_length=100)
    theme: str = Field(default="", max_length=500)
    style: str = Field(default="", max_length=100)
    lyrics: str = Field(default="", max_length=20000)
    arrangement: str = Field(default="", max_length=10000)
    style_en: str = Field(default="", max_length=5000)
    rounds: list[dict[str, str]] | None = None
    source: str = Field(default="roundtable", max_length=20)


# 圆桌限流：每用户每分钟最多 3 场（一场 8 次 LLM 调用，成本保护）
_ROUNDTABLE_RATE = 3
_ROUNDTABLE_WINDOW = 60.0
_roundtable_hits: dict[str, list[float]] = {}


def _rate_limit_roundtable(user_id: str) -> bool:
    """滑动窗口限流：返回 False 表示超限。"""
    import time

    now = time.monotonic()
    hits = [t for t in _roundtable_hits.get(user_id, []) if now - t < _ROUNDTABLE_WINDOW]
    if len(hits) >= _ROUNDTABLE_RATE:
        _roundtable_hits[user_id] = hits
        return False
    hits.append(now)
    _roundtable_hits[user_id] = hits
    return True


def _style_profile_block(style: str) -> str:
    """风格基调 → 风格特征约束（注入阵容/讨论/定稿 prompt）。"""
    profile = _STYLE_PROFILES.get(style)
    if not profile:
        return ""
    return f"\n\n【风格基调专属特征（必须严格遵守）】\n{profile}"


# 圆桌会议：四位 AI 创作者相互讨论碰撞，最后由制作人定稿（用户只需给主题）
_ROUNDTABLE_PROMPT = """你是「音乐创作圆桌会议」的主持人。四位创作者围绕主题展开真实讨论：各抒己见、互相反驳、被说服、修正方向，最后主理人定稿。
严格输出 JSON（不要任何多余文字）：

{{
  "rounds": [
    {{"speaker": "作词人", "content": "发言（60-100 字，谈意象/文学性/主题挖掘）"}},
    {{"speaker": "作曲家", "content": "发言（60-100 字，谈调式/和弦/旋律走向/BPM）"}},
    {{"speaker": "制作人", "content": "发言（60-100 字，谈编曲层次/风格市场听感）"}},
    {{"speaker": "乐评人", "content": "发言（60-100 字，毒舌挑刺：意象俗套/结构平庸/听感问题）"}},
    {{"speaker": "作曲家", "content": "回应乐评人（50-90 字）"}},
    {{"speaker": "作词人", "content": "根据讨论修正方向（50-90 字）"}}
  ],
  "final": {{
    "title": "歌名（2-6 字，有记忆点）",
    "lyrics": "定稿歌词（标【主歌1】【副歌】【主歌2】【桥段】【副歌】，260-450 字，体现讨论中达成的方向）",
    "arrangement": "定稿编曲思路（80-150 字：风格/BPM/调式/乐器层次/段落动态）",
    "style_en": "英文风格描述（40-60 词，给 Suno）"
  }}
}}

四位创作者人设：
- 作词人·阿墨：文字功底深，重视意象与文学性，反对陈词滥调与网络腔
- 作曲家·小调：乐理派，谈调式/和声进行/旋律记忆点，反对平庸走向
- 制作人·老K：制作与市场视角，谈编曲层次/混音/听感，务实
- 乐评人·毒舌：挑剔毒舌，从普通听众角度挑毛病，逼其他人改进

讨论要求：发言要真实交锋（乐评人必须挑出具体毛病，其他人必须实质回应），不客套。
【文学性铁律】文采：善用通感/拟人/虚实相生；至少一处让人"心头一动"的妙句；可化用古典意象但自然不生硬；留白，不写满。
【歌词铁律】画面感（每句有具体场景/感官细节）；叙事推进（主歌1铺场景→主歌2转折→桥段升华）；副歌有重复金句；押韵自然；意象新颖。
【语言铁律】歌词必须用普通人日常能听懂的语言——专业/技术术语（模型名、参数、代码、行业黑话）只可作人物设定背景，严禁直接写入歌词正文；意象必须来自人的具体生活。

主题：{theme}
风格基调：{style}
情绪基调：{mood}"""


# 讨论室人格：懂词/曲/编曲/乐理，多轮上下文延续，首轮出完整初稿
_DISCUSS_SYSTEM = """你是「音乐讨论室」的创作伙伴：顶级词曲作者 + 音乐制作人 + 乐理顾问。
- 对话式共创：像真正的创作伙伴一样先【讨论】再动笔，有来有回。
- 首轮（用户只有想法，没有明确要出稿）：先讨论——简短回应想法，给出 2-3 个创作方向构思（风格走向/情绪基调/结构想法），然后问 1-2 个关键问题（如"偏民谣的叙事感还是电子的氛围感？副歌想要一句反复的金句吗？"），让用户选择。不要直接出完整歌词。
- 用户明确要出稿（"直接写/来一首/写吧/选第X个"或给了明确风格选择）→ 给完整初稿：歌名 + 完整歌词（标【主歌1】【副歌】【主歌2】【桥段】）+ 编曲思路（风格/BPM/乐器层次/段落动态/人声处理）。
- 后续轮次：基于上下文迭代，只针对用户要求精准修改（改词/换风格/加段落/讨论乐理与编曲/对比不同走向），不要整首重抄，除非用户明确要求。
- 有音乐品味：避免陈词滥调意象与网络腔；可以引用乐理与制作知识（调式/和弦走向/配器/律动/混音）让讨论有深度。
- 歌词标【】段落结构，方便复制到 Suno / 网易天音。语言跟随用户（默认中文）。"""


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
        theme=req.theme,
        style=req.style,
        mood=req.mood,
        language=req.language,
        verse_count=req.verse_count,
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


def _transcript(messages: list[dict[str, str]], style: str) -> str:
    """多轮对话 → 可投递给单 prompt 的文本（保留最近 20 条）。"""
    lines: list[str] = []
    if style:
        lines.append(f"（本次创作固定风格：{style}，讨论与修改都要贴合该风格）")
    for m in messages[-20:]:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"用户：{content}")
        elif role == "assistant":
            lines.append(f"助手：{content}")
        else:
            lines.append(content)
    return "\n\n".join(lines)


@router.post("/discuss")
async def discuss_music(
    req: MusicDiscussRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """音乐讨论室：多轮对话式创作（自由讨论，歌词可复制）。

    首轮（对话刚开始）自动注入创作素材：知识库优先，勾选联网则补充新鲜题材。
    """
    prompt = _transcript(req.messages, req.style)
    # 首轮注入创作素材（从用户最新消息提取主题；后续轮次素材已在对话上下文里）
    if len(req.messages) <= 2:
        theme = next(
            (m.get("content") or "" for m in reversed(req.messages) if m.get("role") == "user"),
            "",
        ).strip()[:100]
        if theme:
            try:
                from app.services.knowledge_materials import retrieve_creation_materials

                kb_text, _kt, web_text, _wt = await retrieve_creation_materials(
                    db, user.id, theme, limit=3, use_web=req.use_web
                )
                from app.services.knowledge_materials import format_material_block

                block = format_material_block(kb_text, web_text)
                if block:
                    prompt += block
            except Exception:
                pass
    resolved = await resolve_text_provider(db, req.model)
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, system=_DISCUSS_SYSTEM, temperature=0.95
    )
    if isinstance(result, dict):
        text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        text = str(result.content)
    else:
        text = str(result)
    return {"reply": text, "provider": resolved.model}


@router.post("/roundtable")
async def roundtable_music(
    req: MusicRoundtableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """多角色圆桌（单次版）：四位 AI 创作者相互讨论后定稿（用户只需给主题）。"""
    prompt = _ROUNDTABLE_PROMPT.format(
        theme=req.theme,
        style=req.style or "（自由，由讨论决定）",
        mood=req.mood or "（自由，由讨论决定）",
    )
    resolved = await resolve_text_provider(db, req.model)
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
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


# ===== 圆桌·真讨论版（SSE 逐轮真实生成，角色按主题定制）=====

# 第 0 轮：AI 根据主题定制会议阵容（4 位专业角色，人设/领域贴合主题）
_CAST_PROMPT = """你是「音乐创作圆桌会议」的选角导演。根据创作主题与风格基调，为这场创作会量身定制 4 位专业角色——
不是通用的作词/作曲/制作/乐评，而是**真正贴合这个主题的专业人士**。
严格输出 JSON（不要任何多余文字）：

{{
  "roles": [
    {{
      "name": "角色名（2 字，有辨识度）",
      "field": "专业领域（贴合主题，如：古风词作 / 民乐编曲 / 电子合成器制作 / 戏曲唱腔顾问）",
      "persona": "人设（40-60 字：专业背景 + 创作主张 + 说话风格，贴合该领域）",
      "icon": "一个 emoji 代表形象",
      "order": 1,
      "finalizer": false
    }}
  ]
}}

要求：
- 4 位角色领域互补、都紧扣主题（主题是古风就请懂五声调式/民乐/戏曲的人，主题是电子就请懂合成器/Drop/律动的人）
- 其中一位是"挑剔的听众/评审"（order 4，persona 里明确毒舌挑剔）
- 其中一位是"主理人/制作人"（finalizer=true，负责最后定稿，persona 里明确综合能力）
- 拒绝万金油人设，每位必须有该主题专属的专业深度

主题：{theme}
风格基调：{style}"""


def _speaker_prompt(
    theme: str,
    style: str,
    rounds: list[dict[str, str]],
    task: str,
    extra: str = "",
) -> str:
    """构造发言者 prompt：主题 + 风格特征 + 前序发言记录 + 本轮任务。"""
    history = "\n".join(f"{r['speaker']}：{r['content']}" for r in rounds) or "（你是第一位发言者）"
    return (
        f"【第一信条·人民性】你从人民中来，为人民而写：站在普通人一边，写普通人的真实生活、劳动、尊严与悲欢；不居高临下地歌颂，用人民的语言，禁止鸡汤与宣传腔。\n"
        f"【语言铁律】讨论与歌词都禁止专业/技术术语直接入词（模型名/参数/代码/黑话只可作人物设定背景），意象来自普通人的具体生活。\n"
        f"创作主题：{theme}\n"
        f"风格基调：{style or '（自由）'}\n"
        f"{_style_profile_block(style)}"
        f"{extra}"
        f"\n\n【前序发言】\n{history}\n\n"
        f"【本轮任务】{task}"
    )


def _transcript_block(rounds: list[dict[str, str]], limit: int = 2500) -> str:
    """讨论记录 → 文本（从最新往前截断，防定稿 prompt 超长）。"""
    parts: list[str] = []
    total = 0
    for r in reversed(rounds):
        s = f"{r['speaker']}：{r['content']}"
        if parts and total + len(s) > limit:
            break
        parts.append(s)
        total += len(s)
    return "\n".join(reversed(parts)) or "（无讨论记录）"


def _repair_lyrics(lyrics: str) -> str:
    """程序化修复常见结构错误：同一段落标签连续重复时合并（主歌/桥段各 1 段，副歌最多 2 遍）。

    模型常把每行都打上【主歌1】标签——把「【主歌1】A\n【主歌1】B」修复为「【主歌1】A\nB」。
    """
    if not lyrics:
        return lyrics
    out: list[str] = []
    seen_tags: dict[str, int] = {}  # 标签 → 已出现次数
    for raw in lyrics.splitlines():
        line = raw.strip()
        if not line:
            out.append("")
            continue
        m = re.match(r"^(【[^】]+】)(.*)$", line)
        if not m:
            out.append(line)
            continue
        tag, rest = m.group(1), m.group(2)
        count = seen_tags.get(tag, 0)
        # 副歌允许 2 遍；其它标签只允许 1 次；超限的并入最近一次同名段落
        limit = 2 if tag == "【副歌】" else 1
        if count >= limit:
            # 找最近一次该标签所在的行，把内容追加到其后
            for i in range(len(out) - 1, -1, -1):
                if out[i].startswith(tag):
                    out.insert(i + 1, rest.strip())
                    break
            continue
        seen_tags[tag] = count + 1
        out.append(line)
    return "\n".join(out).strip()


def _validate_lyrics(lyrics: str) -> list[str]:
    """定稿结构自检：返回警告列表（缺段落/标签重复/副歌次数/字数/押韵提示）。"""
    warnings: list[str] = []
    text = lyrics or ""
    # 段落存在性 + 次数（主歌1/主歌2/桥段各 1 次，副歌恰好 2 次）
    counts: dict[str, int] = {}
    for tag in ("【主歌1】", "【副歌】", "【主歌2】", "【桥段】"):
        counts[tag] = text.count(tag)
        if counts[tag] == 0:
            warnings.append(f"缺少{tag}段落")
    if counts["【主歌1】"] > 1:
        warnings.append(f"【主歌1】出现了 {counts['【主歌1】']} 次（应合并为 1 段）")
    if counts["【主歌2】"] > 1:
        warnings.append(f"【主歌2】出现了 {counts['【主歌2】']} 次（应合并为 1 段）")
    if counts["【桥段】"] > 1:
        warnings.append(f"【桥段】出现了 {counts['【桥段】']} 次（应合并为 1 段）")
    if counts["【副歌】"] < 2:
        warnings.append("副歌重复次数不足（应至少 2 次）")
    elif counts["【副歌】"] > 2:
        warnings.append(f"副歌出现了 {counts['【副歌】']} 次（应为 2 次）")
    if 0 < len(text) < 200:
        warnings.append(f"歌词偏短（{len(text)}字，建议 260-450）")
    # 押韵提示：任一段内句尾字完全相同的重复韵脚（如整段全押"光"）
    for tag in ("【主歌1】", "【副歌】", "【主歌2】", "【桥段】"):
        seg = _segment_text(text, tag)
        lines = [ln.strip() for ln in seg.splitlines() if ln.strip()]
        tails = [_tail_char(ln) for ln in lines if _tail_char(ln)]
        dup = {t for t in tails if tails.count(t) > 1}
        if dup and len(tails) >= 3:
            warnings.append(
                f"{tag}句尾反复用「{''.join(sorted(dup))}」字（押韵偷懒），建议同韵部换不同字"
            )
    # 空洞赞颂/鸡汤词检测：赞颂句式填空词（步伐/鼓点/星火/路标/光芒/梦想/辉煌/灯塔/力量）
    # 出现 ≥2 个不同词即报警——对模糊对象喊口号或把苦难鸡汤化
    _HOLLOW_WORDS = (
        "步伐", "鼓点", "星火", "路标", "光芒", "梦想", "辉煌", "灯塔", "力量", "时代",
        "灿烂", "绽放", "闪耀", "温柔", "希望", "美好", "救赎", "远方",
    )
    hollow_hits = [w for w in _HOLLOW_WORDS if w in text]
    if len(hollow_hits) >= 2:
        warnings.append(
            f"空洞赞颂/鸡汤词过密（{''.join(hollow_hits)}），"
            "疑似对模糊对象喊口号或把苦难浪漫化：换成具体动作、物件与人物对话"
        )
    # 作文腔检测：散文/文艺腔高频词——歌词应是"能唱的人话"，不是散文诗
    # 出现 ≥4 处说明语言文人腔过重，句子飘在抽象里，普通人唱不出来
    _LITERARY_WORDS = (
        "呼吸", "温热", "悄悄", "静静", "沉默", "未凉", "仿佛", "如同", "呢喃",
        "低语", "余温", "斑驳", "澄澈", "氤氲", "缱绻", "喟叹", "游走", "轻颤",
    )
    literary_hits = [w for w in _LITERARY_WORDS if w in text]
    if len(literary_hits) >= 4:
        warnings.append(
            f"作文腔过重（{''.join(literary_hits[:8])}…），"
            "歌词是能唱出来的人话，不是散文诗：改口语化，让'人'直接说话和动作"
        )
    # 唱感检查：段内句长（音节数=汉字数）应均衡——某句明显长/短于该段均值，
    # 旋律对不齐（6 秒一句的副歌被 12 字长句压垮）
    # 按行级处理：同标签所有行合并统计（重复标签场景不被 _segment_text 截断漏检）
    for tag in ("【主歌1】", "【副歌】", "【主歌2】", "【桥段】"):
        contents = [
            ln.strip()[len(tag) :].strip()
            for ln in text.splitlines()
            if ln.strip().startswith(tag) and len(ln.strip()) > len(tag)
        ]
        lens = [(_syllable_count(c), c) for c in contents if _syllable_count(c) > 0]
        if len(lens) >= 3:
            avg = sum(n for n, _ in lens) / len(lens)
            for n, c in lens:
                if abs(n - avg) > max(4, avg * 0.4):
                    warnings.append(
                        f"{tag}唱感不齐：「{c[:18]}…」{n}字，段内均值{avg:.0f}字——"
                        "长句会压垮旋律，建议拆分或删减"
                    )
    return warnings


def _segment_text(lyrics: str, tag: str) -> str:
    """取【tag】到下一个【 之间的文本。"""
    idx = lyrics.find(tag)
    if idx < 0:
        return ""
    nxt = lyrics.find("【", idx + len(tag))
    return lyrics[idx + len(tag) : nxt if nxt > 0 else len(lyrics)]


def _tail_char(line: str) -> str:
    """句尾最后一个汉字（跳过标点/括号）。"""
    for ch in reversed(line):
        if "\u4e00" <= ch <= "\u9fff":
            return ch
    return ""


def _syllable_count(line: str) -> int:
    """句子的音节数 ≈ 汉字数（唱感：旋律对齐的粗略单位）。"""
    return sum(1 for ch in line if "\u4e00" <= ch <= "\u9fff")


async def _auto_save_work(
    db: AsyncSession,
    *,
    user_id: str,
    theme: str,
    style: str,
    final: dict[str, Any],
    rounds: list[dict[str, str]],
    source: str = "roundtable",
) -> str:
    """定稿自动存入「我的作品」，返回 work_id。"""
    from app.services.music_works import save_work

    work = await save_work(
        db,
        user_id=user_id,
        title=str(final.get("title") or "未命名"),
        theme=theme,
        style=style,
        lyrics=str(final.get("lyrics") or ""),
        chords=str(final.get("chords") or ""),
        arrangement=str(final.get("arrangement") or ""),
        style_en=str(final.get("style_en") or ""),
        rounds=rounds,
        source=source,
    )
    return work.id


# 创作范例回填防刷：每用户每 10 分钟最多 1 篇（进程内）
_backfill_lock: dict[str, float] = {}
_BACKFILL_MIN_INTERVAL = 600.0


async def _backfill_work_material(
    *,
    user_id: str,
    work_title: str,
    theme: str,
    lyrics: str,
    chords: str,
    arrangement: str,
) -> None:
    """好定稿自动沉淀回知识库（创作范例）：检索命中后成为后续创作的营养。

    条件：自检无严重警告（由调用方把关）+ 标题去重（同用户已有同名范例则跳过）
    + 每用户每 10 分钟最多 1 篇。任何失败静默（不影响创作主流程）。
    """
    if not work_title or not lyrics or len(lyrics) < 200:
        return
    import time as _time

    now = _time.monotonic()
    last = _backfill_lock.get(user_id, 0.0)
    if now - last < _BACKFILL_MIN_INTERVAL:
        return
    _backfill_lock[user_id] = now
    try:
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.models.text_document import TextDocument
        from app.services.knowledge_materials import summarize_for_creation

        title = f"创作范例·{work_title}"
        content = (
            f"创作主题：{theme}\n\n【定稿歌词】\n{lyrics}\n\n【和弦谱】\n{chords or '（无）'}"
            f"\n\n【编曲思路】\n{arrangement or '（无）'}"
        )
        async with AsyncSessionLocal() as session:
            dup = await session.execute(
                select(TextDocument.id)
                .where(TextDocument.user_id == user_id, TextDocument.title == title)
                .limit(1)
            )
            if dup.scalar_one_or_none():
                return
            interpretation = await summarize_for_creation(session, title, content)
            if interpretation:
                content = content + "\n\n" + interpretation
            # AI 自动写入的素材默认待确认（pending）：确认前不参与检索，防幻觉污染
            session.add(
                TextDocument(title=title, content=content, user_id=user_id, status="pending")
            )
            await session.commit()
    except Exception:
        pass


_FIX_LIST_PROMPT = """从以下创作讨论记录中，提取「被批评的元素 → 定稿必须采用的替代方案」清单。
规则：
- 只提取评审明确批评且**给出替代方向**的内容（没给替代的批评不算）
- 每条一行，格式：- 批评：「被批元素」→ 替代：「替代方案」（各 20 字内）
- 最多 4 条；讨论中没有合格批评则输出空数组
输出 JSON（不要任何多余文字）：{{"fixes": ["..."]}}

讨论记录：
{transcript}"""


async def _extract_fix_list(db: AsyncSession, rounds: list[dict[str, str]]) -> str:
    """定稿前把「批评→替代」结构化提取，注入定稿 prompt 作为必改清单。

    失败返回空串（定稿照常进行，模型从讨论自行提取）。
    """
    transcript = _transcript_block(rounds, limit=1800)
    if not transcript or ("批评" not in transcript and "毒舌" not in transcript):
        return ""
    resolved = await resolve_text_provider(db, "")
    try:
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            _FIX_LIST_PROMPT.format(transcript=transcript[:4000]),
            resolved.model,
            temperature=0.2,
        )
        text = _provider_text(result).strip()
        import re as _re

        cleaned = _re.sub(r"^```(?:json)?\s*", "", text)
        cleaned = _re.sub(r"\s*```$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return ""
        data = json.loads(cleaned[start : end + 1])
        fixes = data.get("fixes") or []
        return "\n".join(str(f) for f in fixes if str(f).strip())[:800]
    except Exception:
        return ""


async def _produce_final(
    db: AsyncSession,
    *,
    theme: str,
    style: str,
    finalizer: dict[str, Any] | None,
    rounds: list[dict[str, str]],
    kb_block: str = "",
    rewrite_warnings: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """定稿轮：主编把关 + 结构自检。返回 (final, checks)。

    rewrite_warnings 非空时为重写轮：把上一轮自检警告注入 prompt 要求逐条修正。
    """
    finalizer_name = str((finalizer or {}).get("name") or "主理人")
    transcript = _transcript_block(rounds)
    # 定稿前把「批评→替代」结构化提取（失败返回空，定稿照常）
    try:
        fix_list = await _extract_fix_list(db, rounds)
    except Exception:
        fix_list = ""
    final_prompt = _FINAL_PROMPT.format(
        name=finalizer_name,
        field=str((finalizer or {}).get("field") or "音乐制作"),
        theme=theme,
        style=style or "（自由）",
        style_profile=_style_profile_block(style) + kb_block,
        transcript=transcript,
        fix_list=fix_list
        or "（无结构化清单：从讨论记录自行提取评审点名批评过的元素与替代方案，定稿必须落实）",
    )
    if rewrite_warnings:
        final_prompt += (
            "\n\n【上一轮自检警告】（本次为修正轮：必须逐条修正下列问题后再输出定稿，"
            "修正后的作品不得再出现同类问题）\n" + "\n".join(f"- {w}" for w in rewrite_warnings)
        )
    resolved = await resolve_text_provider(db, "")
    try:
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            final_prompt, resolved.model, temperature=0.7
        )
        final = _extract_json(_provider_text(result))
    except Exception as exc:
        final = {"error": f"定稿失败：{str(exc)[:80]}"}
    if not final.get("error"):
        final["lyrics"] = _repair_lyrics(str(final.get("lyrics") or ""))
    checks = [] if final.get("error") else _validate_lyrics(str(final.get("lyrics") or ""))
    return final, checks


def _severe_checks(checks: list[str]) -> bool:
    """自检中值得自动重写的严重问题（空洞赞颂/作文腔/缺段落/押韵偷懒等）。"""
    return any(
        ("空洞赞颂" in c)
        or ("作文腔" in c)
        or ("缺少" in c)
        or ("押韵偷懒" in c)
        or ("废稿" in c)
        for c in checks
    )


# 讨论顺序模板：order 1 率先 → 2/3 补充 → 4 挑刺 → 2 回应 → 1 修正 → finalizer 定稿
# 讨论纪律：批评必须落到实质改进——换全新意象/方案，禁止"保留+微调"式敷衍
def _round_task(order: int, role_count: int) -> str:
    if order == 1:
        return (
            "你率先发言：**如果主题没有点名具体的人（谁/什么身份），第一步先为创作对象立一个"
            "具体可信的人物原型**——称呼或名字、年龄身份、一件只有他/她做得出的具体的事"
            "（如'巷口炸油条三十年的老张，每天第一根油条总递给上夜班的环卫工，收摊前留半碗豆浆给流浪猫'），"
            "全曲必须围绕这个立住的人物写，禁止对着模糊的'你'唱空泛的赞歌；"
            "然后从你的专业领域出发提出创作方向：核心意象必须**具体可感**（用具象物件/生活细节/感官细节，"
            "如手机屏保、便利店关东煮、门禁卡、地铁报站声），"
            "禁止抽象大词（灯光/星光/孤独/回忆这类被用滥的意象要做出新意）；"
            "**并给出副歌金句的雏形**（一句口语化、朗朗上口的钩子），80-120 字。"
        )
    if order == 2 or order == 3:
        return (
            "基于前序发言补充：从你的专业领域给出**可落地的具体方案**"
            "（和声走向/配器/节奏型要具体到调式/拍号/BPM），60-100 字。"
        )
    return (
        "你担任挑剔的听众：针对前三位发言毒舌挑刺，必须具体到 1-2 个被用滥的意象/方案，"
        "并且**每个被批评的点都要给出一个反方向的替代方向**（如：把抽象的'灯光'换成具体的'便利店关东煮的热气'）；"
        "**若主题未点名对象而方案把'你'写成了没有面孔的模糊形象，必须要求立人物**"
        "（给出身份 + 一件具体的事作为替代，如'与其对着模糊的您唱赞歌，不如写：夜班公交司机老周，方向盘上磨出茧'）；"
        "**副歌金句也要挑**——太弱/太俗/不朗朗上口就指出并给一句更好的候选，60-100 字。"
    )


_FINAL_PROMPT = """【第一信条·人民性】（最高原则，一切创作以此为纲）
你从人民中来，为人民而写：作品站在普通人一边，写普通人的真实生活、劳动、尊严与悲欢。
- 不居高临下地"歌颂"：普通人不是"被赞美的对象"，而是有主体性的人——他们的幽默、倔强、柔软、无奈都要是真的
- 用人民的语言：方言、口语、职业黑话，不用文人腔与宣传腔
- 写"在其中的"视角：细节来自生活内部（劳动的手、挤公交的汗、工资条、夜班饭盒），不是旅游式观察
- 禁忌：禁止鸡汤、宣传腔、居高临下的怜悯、把苦难浪漫化
- 语言铁律：歌词必须用普通人日常能听懂的话——专业/技术术语（模型名、参数、代码、行业黑话）只可作人物设定背景，严禁直接写入歌词正文；意象必须来自人的具体生活

你是{name}（{field}），担任这场创作圆桌的主理人兼主编。产出定稿前先自查，再产出高质量定稿。
严格输出 JSON（不要任何多余文字）：

{{
  "title": "歌名（2-6 字，有记忆点）",
  "lyrics": "定稿歌词（标【主歌1】【副歌】【主歌2】【桥段】【副歌】），详见下方结构要求",
  "chords": "逐段和弦谱（每段一行：段落标记 + 和弦进行，如：【主歌1】C G Am F ｜【副歌】F G C C），给吉他弹唱/Suno 直接用",
  "arrangement": "定稿编曲思路（80-150 字：风格/BPM/调式/乐器层次/段落动态，必须落实讨论中的修正）",
  "style_en": "英文风格描述（40-60 词，给 Suno）"
}}

【第一步·自查修正清单】（逐条落实，严禁任何被批评的元素回归）
{fix_list}

【歌词结构硬要求】（违者视为废稿）
- 段落次数：**【主歌1】恰好 1 次、【主歌2】恰好 1 次、【桥段】恰好 1 次、【副歌】恰好 2 次**（重复时允许微调）。禁止同一标签重复出现。
- 【主歌1】3-4 句：**一个场景**（不是时间线），每句有动作/感官/情节，禁止清单式堆砌
- 【副歌】必须 4 句：第 1-2 句是**金句钩子**（口语化、有意象、朗朗上口、可直接跟唱），第 3-4 句收束；两句副歌内容一致（第二遍可微调）
- 【主歌2】3-4 句：转折/新细节，情绪递进，不得复述主歌1
- 【桥段】2-3 句：升华点，至少一处"心头一动"的妙句
- 全曲 260-450 字

【叙事铁律】（流水账是头号大敌——"清晨…午后…深夜…"式逐段记动作 = 废稿）
0. **立人物（写人先立人）**：若主题未点名具体对象，被歌颂/被描写的"你"必须有**面孔**——
   身份 + 一件只有他/她做得出的具体的事（如"夜班公交司机老周，方向盘磨出茧，收车总留一盏灯给站台等末班车的人"）。
   全曲围绕立住的人物写，禁止对着模糊的"您"唱空泛的赞歌；没有面孔 = 废稿
0b. **人物一致性**：若讨论记录中已确立人物原型（姓名/称呼/身份/具体的事），定稿必须**沿用同一人物**，
   不得另立他人、不得把人物写模糊（姓名或称呼保持一致）
1. **一段只写一个场景，动作最多 2 个**——笔墨花在"那一刻"的感受、细节与留白上；纯交代性动作（拧钥匙/掀锅盖/锁门这类）全曲最多保留 1 个
2. **全曲必须有一个具体的"戏剧时刻"**：一个人、一次交汇、一件小事，让平凡落进心里——例如递茶时注意到少年校徽上的磨损，想起自己也年轻过；没有戏剧时刻 = 废稿
3. **克制不是平淡**：每段允许 1 句直接的内心瞬间（"那一刻，他想起……"），其余用细节说话；把感情全部抹平 = 废稿
4. 每句要么推进情绪、要么揭示人物；只交代动作不交代感受的句子禁止
5. **禁止空洞赞颂句式**：步伐/鼓点/星火/路标/光芒/梦想/辉煌这类抽象词做"赞颂填充"（如"跟着你的步伐向前走""时代鼓点""汗水凝成星火"）——出现即废；要写就写具体动作与物件（"他把第一根油条递给上夜班的环卫工"）

【落地铁律】（"文化不高"的头号病根——句子飘在抽象里）
1. 每句必须落在一个**具体的时空/动作/物件/感官**上：谁在哪儿、做什么、闻到什么、摸到什么
2. 情感要有**真实的处境落点**（"我"的具体身份、具体的那一天、具体的东西），禁止"把孤独写进风里"式空转
3. 允许并鼓励市井烟火气：夜市摊、快递柜、旧皮鞋、食堂的碗——越具体越动人

【文化硬指标】（至少满足 3 条，否则视为废稿）
1. 至少一处**妙句**：通感 / 双关 / 虚实相生，让人心头一动
2. 至少一处**古典文化的当代化用**：唐诗宋词意象、成语反转、典故新解——注意：要**自己创造**化用，禁止直接照抄任何现成句子
3. **句尾自然收束（通顺永远优先，押韵是加分项不是必选项）**：
   - 每句句尾字必须是句子语义的**自然落点**，读起来通顺完整
   - 能自然押韵更好（同韵部、句尾字各不相同），但**禁止为押韵在句尾硬塞孤立单字**——如"在街头航""比灯火更忙""门口城""把温暖送""沉重如酬""影楼"这类凑字一律禁止；**押不上韵就放弃押韵，句子完整通顺最重要**
   - 禁止"~呀~啦"网络腔
4. 至少一句**可单独流传的金句**（发朋友圈不尴尬的那种）
5. 意象新颖：避开"月亮/星星/大海/烟火"直白组合
6. **禁止拼凑旧素材**：不得重复使用讨论记录之外的现成诗句/金句，全部内容须为本次创作原创

【格式】段落标记必须使用【】（如【主歌1】），不得用方括号。

【格式】段落标记必须使用【】（如【主歌1】），不得用方括号。

创作主题：{theme}
风格基调：{style}
{style_profile}

【完整讨论记录】
{transcript}"""


@router.post("/roundtable/stream")
async def roundtable_stream(
    req: MusicRoundtableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """多角色圆桌·真讨论版（SSE）：每位发言者实时生成（携带前序发言），最后定稿。"""

    async def _gen() -> AsyncIterator[str]:
        # 限流：每用户每分钟最多 3 场（成本保护）
        if not _rate_limit_roundtable(user.id):
            err = {
                "type": "error",
                "error": "圆桌会议开得太频繁了，请等一分钟再开（每用户每分钟 3 场）",
            }
            yield _sse_event(err)
            yield "data: [DONE]\n\n"
            return
        # 创作素材：知识库（已读懂）优先；命中不足且开启联网时，搜索兜底新鲜题材
        materials = ""
        material_titles: list[str] = []
        web_materials = ""
        try:
            from app.services.knowledge_materials import retrieve_creation_materials

            (
                materials,
                material_titles,
                web_materials,
                web_titles,
            ) = await retrieve_creation_materials(
                db, user.id, req.theme, limit=3, use_web=req.use_web
            )
            material_titles = material_titles + web_titles
        except Exception:
            materials = ""
        from app.services.knowledge_materials import format_material_block

        kb_block = format_material_block(materials, web_materials)
        # 成长档案：用户创作偏好注入（风格/主题倾向贴合用户习惯）
        try:
            from app.services.profile_service import build_profile_text

            profile_block = await build_profile_text(db, user.id)
            if profile_block:
                kb_block += "\n\n" + profile_block
        except Exception:
            pass
        yield _sse_event({"type": "materials", "titles": material_titles})
        # 第 0 轮：AI 按主题定制会议阵容（4 位专业角色）
        cast: list[dict[str, Any]] = []
        yield _sse_event({"type": "cast_start"})
        cast_prompt = (
            _CAST_PROMPT.format(theme=req.theme, style=req.style or "（自由）")
            + _style_profile_block(req.style)
            + kb_block
        )
        resolved = await resolve_text_provider(db, req.model)
        try:
            cast_result = await resolved.provider.generate(  # type: ignore[attr-defined]
                cast_prompt, resolved.model, temperature=0.9
            )
            cast_data = _extract_json(_provider_text(cast_result))
            roles = cast_data.get("roles") or []
            if isinstance(roles, list):
                cast = [
                    {
                        "name": str(r.get("name") or f"专家{idx}")[:20],
                        "field": str(r.get("field") or "音乐创作")[:40],
                        "persona": str(r.get("persona") or "")[:300],
                        "icon": str(r.get("icon") or "🎙️")[:4],
                        "order": int(r.get("order") or idx + 1),
                        "finalizer": bool(r.get("finalizer")),
                    }
                    for idx, r in enumerate(roles[:4])
                ]
        except Exception:
            cast = [
                {
                    "name": "作词人",
                    "field": "词作与意象",
                    "persona": "重视意象与文学性",
                    "icon": "✍️",
                    "order": 1,
                    "finalizer": False,
                },
                {
                    "name": "作曲家",
                    "field": "调式与和声",
                    "persona": "乐理派",
                    "icon": "🎼",
                    "order": 2,
                    "finalizer": False,
                },
                {
                    "name": "制作人",
                    "field": "编曲与听感",
                    "persona": "务实派",
                    "icon": "🎧",
                    "order": 3,
                    "finalizer": True,
                },
                {
                    "name": "乐评人",
                    "field": "挑剔听众",
                    "persona": "毒舌挑剔",
                    "icon": "👀",
                    "order": 4,
                    "finalizer": False,
                },
            ]
            cast_data = {}
        if len(cast) < 4:  # 数量不足补位
            cast = (
                cast
                + [
                    {
                        "name": f"专家{n}",
                        "field": "音乐创作",
                        "persona": "",
                        "icon": "🎙️",
                        "order": n,
                        "finalizer": False,
                    }
                    for n in range(len(cast) + 1, 5)
                ]
            )[:4]
        ordered = sorted(cast, key=lambda r: int(r.get("order") or 99))
        yield _sse_event({"type": "cast", "cast": cast})

        # 讨论顺序：1 率先 → 2/3 补充 → 4 挑刺 → 2 回应 → 1 修正（quick 模式跳过回应/修正）
        agenda: list[dict[str, Any]] = []
        for r in ordered:
            agenda.append({"role": r, "task": _round_task(int(r.get("order") or 1), len(ordered))})
        if len(ordered) >= 3 and not req.quick:
            agenda.append(
                {
                    "role": ordered[1],
                    "task": (
                        "回应挑剔者的批评：必须**实质性改变至少一个方案点**"
                        "（换全新意象/换和声走向/换配器，给出具体做法）；"
                        "最多辩护 1 点且要有专业理由。禁止'保留+微调'式敷衍，50-90 字。"
                    ),
                }
            )
            agenda.append(
                {
                    "role": ordered[0],
                    "task": (
                        "根据讨论修正你的方案：必须用**至少一个全新的核心意象**替换被批评的部分"
                        "（用具象物件/场景细节，禁止对旧意象换说法）；"
                        "你只负责你自己的专业领域（词作者改词，编曲的交给编曲位落实），50-90 字。"
                    ),
                }
            )

        rounds: list[dict[str, str]] = []
        for idx, item in enumerate(agenda, start=1):
            role = item["role"]
            speaker = str(role.get("name") or f"专家{idx}")
            yield _sse_event({"type": "round_start", "speaker": speaker, "round_no": idx})
            persona = f"你是{role.get('name')}（{role.get('field')}）：{role.get('persona')}"
            prompt = _speaker_prompt(
                req.theme, req.style, rounds, str(item["task"]), extra=kb_block
            )
            resolved = await resolve_text_provider(db, req.model)
            try:
                result = await resolved.provider.generate(  # type: ignore[attr-defined]
                    prompt, resolved.model, system=persona, temperature=0.9
                )
                text = _provider_text(result).strip()
            except Exception as exc:
                text = f"（发言中断：{str(exc)[:80]}）"
            rounds.append({"speaker": speaker, "content": text})
            yield _sse_event({"type": "round", "speaker": speaker, "content": text})

        # 定稿轮：主理人主编把关 + 自检 + 严重问题自动重写一轮 + 自动存入「我的作品」
        finalizer = next(
            (r for r in ordered if r.get("finalizer")), ordered[0] if ordered else None
        )
        yield _sse_event({"type": "final_start"})
        final, checks = await _produce_final(
            db,
            theme=req.theme,
            style=req.style,
            finalizer=finalizer,
            rounds=rounds,
            kb_block=kb_block,
        )
        rewrote = False
        if not final.get("error") and _severe_checks(checks):
            rewrote = True
            final, checks = await _produce_final(
                db,
                theme=req.theme,
                style=req.style,
                finalizer=finalizer,
                rounds=rounds,
                kb_block=kb_block,
                rewrite_warnings=checks,
            )
        work_id = ""
        if not final.get("error"):
            try:
                work_id = await _auto_save_work(
                    db,
                    user_id=user.id,
                    theme=req.theme,
                    style=req.style,
                    final=final,
                    rounds=rounds,
                    source="roundtable",
                )
            except Exception:
                work_id = ""
            # 好作品自动回填知识库（创作范例）：平台自己长素材——「继续学」自动化
            if work_id and not _severe_checks(checks):
                with contextlib.suppress(Exception):
                    backfill_task = asyncio.create_task(
                        _backfill_work_material(
                            user_id=user.id,
                            work_title=str(final.get("title") or "")[:60],
                            theme=req.theme,
                            lyrics=str(final.get("lyrics") or ""),
                            chords=str(final.get("chords") or ""),
                            arrangement=str(final.get("arrangement") or ""),
                        )
                    )
                    backfill_task.add_done_callback(lambda _t: None)
        yield _sse_event(
            {
                "type": "final",
                "final": final,
                "rounds": rounds,
                "cast": cast,
                "checks": checks,
                "work_id": work_id,
                "rewrote": rewrote,
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/roundtable/followup")
async def roundtable_followup(
    req: MusicFollowupRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """圆桌定稿后追问：全员基于讨论+定稿+问题各回应一句，产出新定稿（SSE）。"""

    async def _gen() -> AsyncIterator[str]:
        if not _rate_limit_roundtable(user.id):
            yield _sse_event(
                {"type": "error", "error": "操作太频繁了，请等一分钟再试（每用户每分钟 3 场）"}
            )
            yield "data: [DONE]\n\n"
            return
        # 创作素材（与主会议一致）：知识库优先，追问轮勾选联网则补充新鲜题材
        kb_block = ""
        try:
            from app.services.knowledge_materials import retrieve_creation_materials

            materials, _kt, web_materials, _wt = await retrieve_creation_materials(
                db, user.id, req.theme, limit=2, use_web=req.use_web
            )
            from app.services.knowledge_materials import format_material_block

            kb_block = format_material_block(materials, web_materials)
        except Exception:
            kb_block = ""
        cast = req.cast or []
        ordered = sorted(cast, key=lambda r: int(r.get("order") or 99))
        if not ordered:
            ordered = [
                {
                    "name": "作词人",
                    "field": "词作与意象",
                    "persona": "重视意象与文学性",
                    "icon": "✍️",
                    "order": 1,
                    "finalizer": False,
                },
                {
                    "name": "作曲家",
                    "field": "调式与和声",
                    "persona": "乐理派",
                    "icon": "🎼",
                    "order": 2,
                    "finalizer": False,
                },
                {
                    "name": "制作人",
                    "field": "编曲与听感",
                    "persona": "务实派",
                    "icon": "🎧",
                    "order": 3,
                    "finalizer": True,
                },
                {
                    "name": "乐评人",
                    "field": "挑剔听众",
                    "persona": "毒舌挑剔",
                    "icon": "👀",
                    "order": 4,
                    "finalizer": False,
                },
            ]
        prev_final = req.final or {}
        prev_lyrics = str(prev_final.get("lyrics") or "")

        rounds: list[dict[str, str]] = list(req.rounds or [])
        base = _transcript_block(rounds, limit=1800)
        for idx, role in enumerate(ordered, start=1):
            speaker = str(role.get("name") or f"专家{idx}")
            yield _sse_event({"type": "round_start", "speaker": speaker, "round_no": idx})
            persona = f"你是{role.get('name')}（{role.get('field')}）：{role.get('persona')}"
            task = (
                f"听众对定稿提出了新要求：{req.question}。"
                "基于这场讨论与定稿，从你的专业领域回应：给出具体调整方案"
                "（改词/换意象/调和声/改配器，必须可落地），60-100 字。"
            )
            prompt = (
                f"创作主题：{req.theme}\n"
                f"风格基调：{req.style or '（自由）'}\n"
                f"{_style_profile_block(req.style)}"
                f"{kb_block}"
                f"\n\n【前序讨论】\n{base or '（无）'}\n\n"
                f"【当前定稿歌词】\n{prev_lyrics[:1500]}\n\n"
                f"【本轮任务】{task}"
            )
            resolved = await resolve_text_provider(db, req.model)
            try:
                result = await resolved.provider.generate(  # type: ignore[attr-defined]
                    prompt, resolved.model, system=persona, temperature=0.9
                )
                text = _provider_text(result).strip()
            except Exception as exc:
                text = f"（发言中断：{str(exc)[:80]}）"
            rounds.append({"speaker": speaker, "content": text})
            yield _sse_event({"type": "round", "speaker": speaker, "content": text})

        # 新定稿：基于原定稿 + 全员回应
        finalizer = next(
            (r for r in ordered if r.get("finalizer")), ordered[0] if ordered else None
        )
        yield _sse_event({"type": "final_start"})
        finalizer_name = str((finalizer or {}).get("name") or "主理人")
        transcript = _transcript_block(rounds, limit=2000)
        followup_prompt = _FINAL_PROMPT.format(
            name=finalizer_name,
            field=str((finalizer or {}).get("field") or "音乐制作"),
            theme=req.theme,
            style=req.style or "（自由）",
            style_profile=_style_profile_block(req.style),
            transcript=(
                f"【听众新要求】{req.question}\n\n"
                f"【原定稿】\n{prev_lyrics[:1500]}\n\n"
                f"【讨论记录】\n{transcript}"
            ),
        )
        resolved = await resolve_text_provider(db, req.model)
        try:
            result = await resolved.provider.generate(  # type: ignore[attr-defined]
                followup_prompt, resolved.model, temperature=0.7
            )
            final = _extract_json(_provider_text(result))
        except Exception as exc:
            final = {"error": f"定稿失败：{str(exc)[:80]}"}
        if not final.get("error"):
            final["lyrics"] = _repair_lyrics(str(final.get("lyrics") or ""))
        checks = [] if final.get("error") else _validate_lyrics(str(final.get("lyrics") or ""))
        work_id = ""
        if not final.get("error"):
            try:
                work_id = await _auto_save_work(
                    db,
                    user_id=user.id,
                    theme=req.theme,
                    style=req.style,
                    final=final,
                    rounds=rounds,
                    source="roundtable",
                )
            except Exception:
                work_id = ""
        yield _sse_event(
            {
                "type": "final",
                "final": final,
                "rounds": rounds,
                "cast": cast,
                "checks": checks,
                "work_id": work_id,
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/works")
async def list_music_works(
    q: str = Query(default="", max_length=100),
    tag: str = Query(default="", max_length=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """我的音乐作品列表（q 按标题/主题/风格过滤；tag 按标签过滤）。"""
    from app.services.music_works import list_works

    return {"items": await list_works(db, user.id, q=q, tag=tag)}


@router.post("/works")
async def save_music_work(
    req: MusicWorkSaveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """手动保存一首作品（写歌/讨论室成品）。"""
    from app.services.music_works import save_work

    work = await save_work(
        db,
        user_id=user.id,
        title=req.title,
        theme=req.theme,
        style=req.style,
        lyrics=req.lyrics,
        arrangement=req.arrangement,
        style_en=req.style_en,
        rounds=req.rounds,
        source=req.source,
    )
    return {"id": work.id, "title": work.title}


@router.get("/works/{work_id}/public")
async def public_music_work(
    work_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """公开只读分享（分享链接用，返回作品内容不含用户信息）。"""
    from app.models.music_work import MusicWork

    work = await db.get(MusicWork, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    return {
        "id": work.id,
        "title": work.title,
        "theme": work.theme,
        "style": work.style,
        "lyrics": work.lyrics,
        "chords": work.chords,
        "arrangement": work.arrangement,
        "style_en": work.style_en,
        "source": work.source,
        "created_at": str(work.created_at) if work.created_at else "",
    }


@router.post("/works/{work_id}/to-chat")
async def publish_work_to_chat(
    work_id: str,
    req: MusicToChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """把作品发布到创作群（作为消息进群，群成员可见）。"""
    from app.models.music_work import MusicWork
    from app.services import sessions

    work = await db.get(MusicWork, work_id)
    if work is None or work.user_id != user.id:
        raise HTTPException(status_code=404, detail="作品不存在")
    chat = await sessions.get_chat(db, user.id, req.chat_id)
    if chat is None or not chat.is_room:
        raise HTTPException(status_code=404, detail="群不存在或无权访问")
    block = [
        f"🎵 主题曲《{work.title}》",
        "",
        work.lyrics,
    ]
    if work.chords:
        block.append("")
        block.append(f"🎸 和弦谱：{work.chords}")
    if work.arrangement:
        block.append("")
        block.append(f"🎧 编曲：{work.arrangement}")
    await sessions.append_message(db, chat, {"role": "assistant", "content": "\n".join(block)})
    await db.commit()
    return {"ok": True, "chat_id": chat.id, "title": work.title}


@router.delete("/works/{work_id}")
async def delete_music_work(
    work_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """删除一首作品。"""
    from app.services.music_works import delete_work

    deleted = await delete_work(db, user.id, work_id)
    return {"ok": deleted}


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
