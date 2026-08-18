# ruff: noqa: E501
from __future__ import annotations

import asyncio
import contextlib
import json
import random
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


# 风格同义词表：主题文本里的常见说法 → 规范风格名（mission prompt 往往写"民谣/古风/电子"而非枚举值）
_STYLE_ALIASES: dict[str, tuple[str, ...]] = {
    "古风": ("古风", "古韵", "汉服", "国风", "诗词意境"),
    "中国风": ("中国风", "国潮"),
    "民谣": ("民谣", "叙事民谣", "乡村民谣", "民谣风"),
    "流行": ("流行", "pop", "流行乐"),
    "R&B": ("r&b", "rnb", "节奏布鲁斯"),
    "电子": ("电子", "电音", "合成器", "techno", "edm", "house", "舞曲"),
    "摇滚": ("摇滚", "rock", "朋克", "金属", "grunge"),
    "爵士": ("爵士", "jazz", "布鲁斯", "swing", "蓝调"),
    "嘻哈": ("嘻哈", "说唱", "rap", "hip", "trap"),
    "治愈系": ("治愈", "疗愈", "轻音乐", "暖心", "温柔系"),
}


def _detect_style(text: str) -> str:
    """从主题/提示文本中检测风格基调（首次命中权重最高，计数决胜），未命中返回空串。

    Mission 等自动生成的 prompt 常把风格写在主题里（"为矿工清晨写一首叙事民谣"），
    但不会传 style 字段——检测后注入风格专属特征，避免所有歌都写成默认腔调。
    """
    t = (text or "").lower()
    best, best_count = "", 0
    for style, aliases in _STYLE_ALIASES.items():
        count = sum(t.count(a.lower()) for a in aliases)
        if count > best_count:
            best, best_count = style, count
    return best


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
    "lyrics": "定稿歌词（标【主歌1】【预副歌】【副歌】【主歌2】【副歌】【桥段】【主歌3】【副歌】，900-1100 字两段式长曲，体现讨论中达成的方向）",
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
【口语化范例】好歌词是"人"会说的话：「等拼完车门，我就去报成人高考」「师傅骂我两句，又帮我补了一针」；不是散文诗——「铁皮还留着白天的呼吸」这类作文腔是废稿。
【点睛铁律】全程白描不点破 = 废稿：必须有至少一处「心口之言」——人物直接说/唱出心里话，或一句能记住的情感点破；禁止只有动作和物件、没有一句人物声音的"观察报告"。

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
  "style_en": "给 AI 音乐工具的英文生成指令（VOCAL/MOOD/SPACE/ARRANGEMENT 四块，硬参数收敛到 4 项，见 style_en 指令铁律）",
  "lyrics": "完整歌词（用 \\n 分行，标注【主歌1】【预副歌】【副歌】【主歌2】【副歌】【桥段】【主歌3】【副歌】），总长 900-1100 字（两段式完整长曲，Part A≈500字+Part B≈400字，约 5-6 分钟）",
  "tips": "一句使用建议（Suno/天音如何设置生成）"
}}

【主题挖掘铁律】（表面主题只是氛围，深层主题才是歌）
- 先挖深层主题：这个主题下"谁、在哪儿、经历了什么、心里压着什么"？
  例："烟雨朦胧"→「雨声中十年的守候：修伞老人等胥江翻船的亡人」。
- 歌词必须服务深层主题（人物/事件/情绪），禁止被表面氛围词带跑；表面氛围只作环境底色（一两句）。

【副歌递进铁律】（hook 是情绪骨架，不是复读机）
- 两遍副歌语义递进：第一遍 hook 只露一半（设悬念），第二遍补全真相，桥段点破；
  禁止两遍一字不差地简单重复。范例：「留个响，夜里像有人推门」→「留个响，夜里不像一个人」→「留个响」。

【style_en 指令铁律】（按生成指令写，不是制作说明）
- 四块：VOCAL 写具体质感（low gravelly restrained male, close-mic）禁止"深情男声"空词；
  MOOD 写具体心境（damp, lonely, restrained）禁止"唯美忧伤"氛围词；
  SPACE 写空间距离（small room, close, rainy night）；
  ARRANGEMENT 写乐器入场顺序与动态走向，硬参数（BPM/调式）不超过 4 个
- 环境音写 subtle distant rain ambience, naturally blended；禁止 heavy rain sound effects；
  关键声音设计（如雨滴搪瓷盆）单独写清并标 long natural decay

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

【立人铁律】被描写的"你/他/她"必须有面孔：身份 + 一件只有他/她做得出的具体的事（如"夜班公交司机老周，收车总留一盏灯给等末班车的人"）。禁止对着模糊的"您"唱空泛赞歌；没有面孔 = 废稿
【人名禁令】歌词里严禁「我是XX」自报家门、严禁完整人名直呼（「老李把豆浆倒进杯」是废稿写法）——人物的具体性靠物件/动作/细节传递，必须称呼时用「你/她/师傅/老哥」这类口语称呼
【短句铁律】一句只说一件事，禁止一句塞多个并列信息（散文不是歌词）；拆成短行，长句会压垮旋律
【点睛铁律】必须有至少一处「心口之言」——人物直接说/唱出心里话（引语或第一人称心声），或一句情感点破；禁止只有动作和物件、没有一句人物声音的"观察报告"
【钩子事件化】副歌钩子必须是具体事件/画面/动作（谁在哪儿做了什么），禁止"道理对仗句"式总结陈词（如"车铃响三声，夜路短一截"）；前一句具体朴素，后一句"戳破"——意料之外、情理之中的反转

【歌词感铁律】（这是"歌"，不是分行散文——检验标准是能否跟着拍子哼唱）
1. 句长：6-14 字为主（短句 4-8 字、中句 9-14 字），单句禁超 16 字；**段内句长要有起伏**（短-中-长节奏，像呼吸），禁止整段全是 5-8 字短句平推（那是口号，不是叙事）
2. 押韵：每段至少 2 处句尾押韵；副歌句句押或隔句押，句尾字各不相同（禁整段押同一个字）；押不上就自然断句，禁硬凑单字
3. 副歌 4 句：第 1-2 句是最抓耳的 hook（能独立反复跟唱），第 3-4 句收束；两遍副歌**结构对齐、语义递进**（hook 重复或递进加深，见副歌递进铁律；禁止整段一字不差复制）
4. 节奏：读出来有呼吸感，像人说话有轻重缓急；禁止一句塞多个并列信息
5. 韵律范例（模仿其节奏与押韵结构，禁止照抄内容）：
   - 「和我在成都的街头走一走 / 直到所有的灯都熄灭了也不停留」
   - 「越过山丘 / 才发现无人等候」
   - 「我曾经跨过山和大海 / 也穿过人山人海」
6. 写完后自我检验：每段能跟着拍子哼出来吗？句尾能押上吗？不能就重写这段

【信息密度铁律】（单薄 = 废稿——短句化后细节全丢只剩骨架）
- 主歌 5-8 句、桥段 3-4 句；每段至少 2 个具体细节（物件/动作/声音/身体感受），禁止骨架式口号
- 全曲 260-450 字；写完数一数：每段若只剩 3 句、细节全丢 → 重写加厚
- 细节要"长在句子里"：每句自带一个画面/声音/触感，不是单独罗列

【人物价值层级铁律】（坍缩 = 废稿）
- 人物的坚持/守候/等待必须从信仰/使命/职业伦理推导，禁止用"亡妻/思念"解释一切；
  创伤可以是信仰的起点（因为失去过，所以不能再让别人失去），但不得吞掉人物本身
- 反第一联想：禁默认"雨=思念/旧物=回忆/老人=孤独"；物件首先是物件，意义从使用中涌现
- 允许人物有矛盾价值（负责+骄傲+爱钱+不善表达），不解释读者能懂的意义，禁止强行升华

【词曲专业技法】（专业词曲人的基本功）
- 用词讲究质感：动词选有质地（勒/楔/嵌/搪），名词具体到能看见（三号扳手/搪瓷缸沿），禁止"形容词+名词"惰性搭配（温暖的灯/孤独的夜）
- 韵脚是设计：每段定主韵，句尾字从主韵部选，副歌 hook 落主韵；换韵要有意，禁止散韵
- 句内节奏=旋律气口：断句点就是换气点，短-长-短交替，禁连续同长度句
- 和声贴情绪：主歌挂留（sus2/add9）留呼吸，副歌强进行，桥段可离调；**禁全曲 Em-C-G-D 万能和弦**
- 声场三层（近人声/中和声/远环境）+ 动态弧线（主歌最轻→副歌最满→结尾留白），人声写音区与气息，禁"深情男声"空词

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
    # 词曲专业常驻注入：单次写歌同样带上创作技法（专业地基）
    try:
        from app.services.knowledge_materials import retrieve_music_pro_notes

        pro_notes = await retrieve_music_pro_notes(db, user.id)
        if pro_notes:
            prompt += "\n\n" + pro_notes
    except Exception:
        pass
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
    # 质量闭环：结构修复 + 自检 + 严重问题自动重写一轮（与圆桌定稿同一套把关）
    if not data.get("error"):
        data["lyrics"] = _repair_lyrics(str(data.get("lyrics") or ""))
    checks = [] if data.get("error") else _validate_lyrics(str(data.get("lyrics") or ""))
    data["checks"] = checks
    if not data.get("error") and _severe_checks(checks):
        rewrite_prompt = (
            prompt
            + "\n\n【上一轮自检警告】（本次为修正轮：必须逐条修正下列问题后再输出定稿，"
            "修正后的作品不得再出现同类问题）\n"
            + "\n".join(f"- {w}" for w in checks)
        )
        try:
            r2 = await provider.generate(  # type: ignore[attr-defined]
                rewrite_prompt, resolved.model, temperature=0.7
            )
            data2 = _extract_json(_provider_text(r2))
            if not data2.get("error"):
                data2["lyrics"] = _repair_lyrics(str(data2.get("lyrics") or ""))
                data2["checks"] = _validate_lyrics(str(data2.get("lyrics") or ""))
                data2["rewrote"] = True
                data2["provider"] = resolved.model
                data = data2
        except Exception:
            pass  # 重写失败保留初稿（自检警告已在 checks 返回）
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
    if not req.style:
        # 未显式固定风格时，从对话文本检测（"写首民谣"→民谣特征注入讨论）
        req.style = _detect_style(
            " ".join(m.get("content", "") for m in req.messages[-6:] if m.get("content"))
        )
    prompt = _transcript(req.messages, req.style)
    if req.style:
        prompt = prompt + _style_profile_block(req.style)
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
    style = req.style or _detect_style(req.theme)
    prompt = _ROUNDTABLE_PROMPT.format(
        theme=req.theme,
        style=style or "（自由，由讨论决定）",
        mood=req.mood or "（自由，由讨论决定）",
    ) + _style_profile_block(style)
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
    # 质量闭环：结构修复 + 自检 + 严重问题自动重写一轮（与真讨论版一致）
    if not data.get("error"):
        data["lyrics"] = _repair_lyrics(str(data.get("lyrics") or ""))
    checks = [] if data.get("error") else _validate_lyrics(str(data.get("lyrics") or ""))
    data["checks"] = checks
    if not data.get("error") and _severe_checks(checks):
        rewrite_prompt = (
            prompt
            + "\n\n【上一轮自检警告】（本次为修正轮：必须逐条修正下列问题后再输出定稿，"
            "修正后的作品不得再出现同类问题）\n"
            + "\n".join(f"- {w}" for w in checks)
        )
        try:
            r2 = await resolved.provider.generate(  # type: ignore[attr-defined]
                rewrite_prompt, resolved.model, temperature=0.7
            )
            data2 = _extract_json(_provider_text(r2))
            if not data2.get("error"):
                data2["lyrics"] = _repair_lyrics(str(data2.get("lyrics") or ""))
                data2["checks"] = _validate_lyrics(str(data2.get("lyrics") or ""))
                data2["rewrote"] = True
                data2["provider"] = resolved.model
                data = data2
        except Exception:
            pass
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
      "field": "专业领域（贴合主题，如：古风词作 / 民乐编曲 / 电子合成器制作 / 戏曲唱腔顾问。只写专业本身，禁止写「主理人/制作人/评审」等角色标签——角色由 finalizer/order 字段表达）",
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
- 其中一位是"主理人/制作人"（finalizer=true，负责最后定稿，persona 里明确综合能力；但 field 仍写其专业领域如「民谣摇滚制作」，禁止把「主理人」写进 field——前端会单独打「主理人」标签，写进 field 会拼成「主理人主理人」）
- 拒绝万金油人设，每位必须有该主题专属的专业深度

主题：{theme}
风格基调：{style}"""


def _speaker_prompt(
    theme: str,
    style: str,
    task: str,
    opponent: str = "",
    extra: str = "",
) -> str:
    """构造发言者 prompt：主题 + 风格 + 本轮任务 + 针对性回应对象（自我中心投影）。

    关键：不再全文拼接历史（那会导致"总结性续写"和复读套话），
    只给「上一个对手的原话」——让回应针锋相对，而非对全文泛泛而谈。
    """
    target = (
        f"【你要回应的对象（上一轮的原话）——必须针对它回应，引用它的具体说法】\n{opponent}"
        if opponent
        else "（你是第一位发言者，没有前文可回应，直接发表你的方案）"
    )
    return (
        f"【第一信条·人民性】你从人民中来，为人民而写：站在普通人一边，写普通人的真实生活、劳动、尊严与悲欢；不居高临下地歌颂，用人民的语言，禁止鸡汤与宣传腔。\n"
        f"【语言铁律】讨论与歌词都禁止专业/技术术语直接入词（模型名/参数/代码/黑话只可作人物设定背景），意象来自普通人的具体生活。\n"
        f"【人名禁令】讨论里可以给人物立名（周秀兰/老周），但歌词里严禁「我是XX」自报家门、严禁完整人名直呼——人物的具体性靠物件/动作/细节传递，不靠念名字。\n"
        f"【点睛铁律】发言与歌词须推敲「心口之言」——人物直接说出的心里话（引语/第一人称）或一句情感点破；心口之言必须是具体事件/画面/动作，禁止「道理对仗句」（如'车铃响三声，夜路短一截'式格言总结）；警惕全程白描只有物件没有声音。\n"
        f"创作主题：{theme}\n"
        f"风格基调：{style or '（自由）'}\n"
        f"{_style_profile_block(style)}"
        f"{extra}"
        f"\n\n{target}\n\n"
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


def _shuffled_transcript(rounds: list[dict[str, str]], limit: int = 2500) -> str:
    """裁决去位置偏见：随机打乱发言块顺序（保留发言者名），打破 primacy/recency 锚定。

    搜索结论（Judging the Judges）：judge 有系统性位置偏见，机械修复（随机化/轮换）
    比「写更公正的 rubric」有效。主理人裁决时应按观点质量而非发言顺序——随机化
    迫使它逐条看观点内容（每个块都带 speaker 名，可归因），而非"谁最后说就听谁的"。
    """
    shuffled = list(rounds)
    random.shuffle(shuffled)
    return _transcript_block(shuffled, limit)


def _repair_lyrics(lyrics: str) -> str:
    """程序化修复常见结构错误：同一段落标签连续重复时合并（主歌/桥段各 1 段，副歌最多 2 遍）。

    模型常把每行都打上【主歌1】标签——把「【主歌1】A\n【主歌1】B」修复为「【主歌1】A\nB」；
    也用【副歌2】代替第二遍【副歌】——归一化为【副歌】（计数/校验按两遍【副歌】处理）。
    """
    if not lyrics:
        return lyrics
    lyrics = re.sub(r"【副歌[2４]】", "【副歌】", lyrics)
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


def _is_antithetical_hook(line: str) -> bool:
    """判断一句歌词是否是「道理对仗格言」而非「具体事件/画面」。

    特征：逗号分隔两个字数完全相等的短语，且结尾不是具体动作动词——
    如「车铃响三声，夜路短一截」「他走他的路，我补我的乐」；
    事件句（「栽进排水沟」「我那年下夜班，铃是个哑巴」）不命中。
    """
    s = (line or "").strip().rstrip("，,。")
    if not s:
        return False
    parts = re.split(r"[，,]", s)
    if len(parts) != 2:
        return False
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b:
        return False
    # 对仗：字数完全相等
    if len(a) != len(b):
        return False
    # 结尾若是具体动作动词（栽/摔/骂/扶/推/擦/按/敲/走/跑/看/听/捡/递/塞/扫），是事件句非格言
    action_tail = re.compile(r"(栽|摔|骂|扶|推|擦|按|敲|走|跑|看|听|捡|递|塞|扫)$")
    return not (action_tail.search(a) or action_tail.search(b))


def _strip_tag(line: str) -> str:
    """去掉行首的【段落标记】，返回正文；无标记则原样返回（保留首尾空白去除）。"""
    m = re.match(r"^【[^】]*】", line.strip())
    return line.strip()[m.end() :].strip() if m else line.strip()


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
    elif counts["【副歌】"] > 3:
        warnings.append(f"副歌出现了 {counts['【副歌】']} 次（应为 2-3 次）")
    if 0 < len(text) < 500:
        warnings.append(f"歌词偏短（{len(text)}字，完整长曲应 900-1100 字两段式）——这是短版不是长曲："
                        "补【主歌3】/加长主歌句数与副歌遍数/加厚细节（物件/动作/声音），Part A+B 合计到 5-6 分钟")
    # 段落单薄检测：句数不足 = 骨架化（每段只剩两三句口号式短句，没有细节承载）
    for tag, min_lines in (("【主歌1】", 5), ("【主歌2】", 5), ("【主歌3】", 4), ("【副歌】", 4), ("【桥段】", 3), ("【预副歌】", 2)):
        seg_lines = [ln.strip() for ln in _segment_text(text, tag).splitlines() if ln.strip()]
        if seg_lines and len(seg_lines) < min_lines:
            warnings.append(
                f"{tag}单薄（仅 {len(seg_lines)} 句，应 ≥{min_lines} 句）——细节被砍光了，"
                "每段要写够物件/动作/声音的具体细节，禁止骨架式口号"
            )
    # 人物动机降维检测：丧亲意象 + 反复守/等/留，但几乎没有职业/劳动动作 = 悲情覆盖价值
    # （人物价值层级坍缩：人物被悲伤解释吞掉，缺少信仰/使命/职业伦理支撑）
    _LOSS_WORDS = ("亡妻", "去世", "走丢", "没救上来", "牺牲", "不在了", "出的事", "翻船", "淋雨走丢", "再没回来", "走的那年", "没接住", "没等到")
    _LINGER_WORDS = ("守", "等", "留", "念")
    _LABOR_WORDS = (
        "修", "补", "焊", "扫", "检", "量", "算", "装", "卸", "递", "撑", "擦", "磨",
        "捡", "纳", "缝", "煮", "熬", "抄", "记", "值", "倒", "盛", "捞", "洗", "晾",
        "拆", "绑", "缠", "拧", "敲", "刮", "浇", "筑", "搬", "扛", "推", "铲", "刨",
    )
    loss_hits = [w for w in _LOSS_WORDS if w in text]
    linger_hits = [w for w in _LINGER_WORDS if w in text]
    labor_hits = [w for w in _LABOR_WORDS if w in text]
    if loss_hits and len(linger_hits) >= 2 and len(labor_hits) <= 1:
        warnings.append(
            "人物动机降维（悲情覆盖价值）：出现丧亲意象（"
            + "、".join(loss_hits[:3])
            + "）+ 反复「守/等/留」，但全曲几乎没有职业/劳动动作——"
            "人物被悲伤解释吞掉，加职业逻辑与具体劳动细节（修/补/检/扫/煮…），"
            "让创伤成为信仰的起点而非动机的全部"
        )
    # 符号过密检测：意象全在第一联想语义空间（雨=思念/桥=人生/旧物=回忆）
    _SYMBOL_WORDS = (
        "雨", "桥", "伞", "灯", "旧", "故人", "十年", "远方", "霜", "青瓦", "江南", "烟雨", "风",
    )
    symbol_hits = [w for w in _SYMBOL_WORDS if w in text]
    if len(symbol_hits) >= 6:
        warnings.append(
            "符号过密（"
            + "、".join(symbol_hits[:6])
            + "）：意象全在第一联想语义空间，换现实/职业/技术维度；"
            "物件首先是物件，意义从使用中涌现"
        )

    # 押韵提示：任一段内句尾字完全相同的重复韵脚（如整段全押"光"）
    # 每段最多取前 4 行检测——模型常把两遍副歌粘连在同一标签下（重复段句尾必相同，
    # 不取前几行会把"副歌重复"误报成"押韵偷懒"；单遍副歌/主歌标准 3-4 句）
    for tag in ("【主歌1】", "【副歌】", "【主歌2】", "【桥段】"):
        seg = _segment_text(text, tag)
        lines = [ln.strip() for ln in seg.splitlines() if ln.strip()][:4]
        tails = [_tail_char(ln) for ln in lines if _tail_char(ln)]
        dup = {t for t in tails if tails.count(t) >= 3}
        if dup and len(tails) >= 3:
            warnings.append(
                f"{tag}句尾反复用「{''.join(sorted(dup))}」字（押韵偷懒），建议同韵部换不同字"
            )
        # 无韵检测（十三辙）：段内句尾字去重后 ≥4 个且零同辙 = 明显无韵
        # 同辙不同字 = 真押韵；同字重复被上面"押韵偷懒"接住
        uniq = list(dict.fromkeys(tails))
        if len(uniq) >= 4:
            rhyme_z = {_RHYME_INDEX.get(u) for u in uniq}
            rhyme_z.discard(None)
            if len(rhyme_z) == len(uniq) and len(rhyme_z) >= 4 and not dup:
                warnings.append(
                    f"{tag}无韵（句尾 {len(uniq)} 个尾字互不押韵）："
                    "按十三辙选韵（如言前辙 an/ian：山/天/年/见），每段至少两处同辙句尾"
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
    # 暖词复用检测：用「热乎/焐软/焐热/暖烘烘」这类笼统暖词给情感收尾 = 词汇偷懒（把情感抽象成温度）
    _WARM_CRUTCH = ("热乎", "焐软", "焐热", "暖烘烘")
    warm_hits = [w for w in _WARM_CRUTCH if w in text]
    if warm_hits:
        warnings.append(
            f"暖词复用（{''.join(warm_hits)}）：情感落点用笼统暖词收尾（把情感抽象成'温度'），"
            "换成具体的物件/动作/声音，禁止'热/暖/焐'从头用到尾"
        )
    # 点睛检测：全程第三人称白描（无直接引语/无第一人称心声）→ 观察报告式，缺心口之言
    # 引号兼容：中文引号（“”「」）与 ASCII 双引号都算引语（模型常输出英文引号）
    has_dialogue = any(
        mark in text
        for mark in ("“", "「", "”", "」", '"', "说：", "想：", "在心里", "对自己说")
    )
    if not has_dialogue and "我" not in text:
        warnings.append(
            "全程白描缺点睛：歌词没有人物自己的声音（直接引语/第一人称心口之言），"
            "只有动作和物件——加一句人物直接说的话或情感点破"
        )
    # 钩子事件化检测：副歌首行若是「道理对仗格言」（车铃响三声，夜路短一截式）而非具体事件 → 报警
    hook_lines = [
        ln.strip()[len("【副歌】") :].strip()
        for ln in text.splitlines()
        if ln.strip().startswith("【副歌】") and len(ln.strip()) > len("【副歌】")
    ]
    if hook_lines and _is_antithetical_hook(hook_lines[0]):
        warnings.append(
            "副歌钩子是「道理对仗格言」（如'车铃响三声，夜路短一截'式总结陈词）而非具体事件/画面——"
            "把钩子改成具体动作或画面（如'栽进排水沟''我那年下夜班，铃是个哑巴'）"
        )
    # 自报家门检测：歌词行首（去段落标记后）以「我是XX」+名字开头（小说人物卡式自报）→ 报警
    # 「我是真的/想说/就是」这类口语连用排除，避免误伤
    _SELF_INTRO_STOP = {"真的", "想说", "想要", "要说", "就是", "不是", "一个", "这样", "那样"}
    _SELF_INTRO_RE = re.compile(r"^我是([一-龥]{2,3})[，,、。\s]")
    for raw in text.splitlines():
        ln = _strip_tag(raw)
        m = _SELF_INTRO_RE.match(ln)
        if m and m.group(1) not in _SELF_INTRO_STOP:
            warnings.append(
                "歌词自报家门（「我是XX」人物卡写法）：歌词不是人物小传，"
                "人物的具体性靠物件/动作/细节传递——删掉「我是XX」自报，名字不进歌词正文"
            )
            break
    # 散文长句检测：单句塞 ≥3 个并列信息（逗号/顿号/分号）→ 散文不是歌词，短行断句
    prose_hits = []
    for raw in text.splitlines():
        ln = _strip_tag(raw)
        if not ln:
            continue
        breaks = ln.count("，") + ln.count(",") + ln.count("、") + ln.count("；") + ln.count(";")
        if breaks >= 3:
            prose_hits.append(ln)
    if prose_hits:
        warnings.append(
            f"散文长句（歌词不是散文，一句塞了多个并列信息）：「{prose_hits[0][:16]}…」等 {len(prose_hits)} 处——"
            "拆成短行，一句只说一件事"
        )
    # 绝对句长超限检测：单句 > 15 汉字（歌词感铁律——5-12 字为主，禁超 15 字）。
    # 段内相对比较查不出"整段都长"（叙事诗式），必须按绝对阈值拦。
    for raw in text.splitlines():
        ln = _strip_tag(raw)
        if not ln:
            continue
        n = _syllable_count(ln)
        if n > 16:
            warnings.append(
                f"长句（{n}字，歌词感铁律禁超16字）：「{ln[:20]}…」——"
                "拆成 5-12 字短句，长句是叙事诗/散文，不是能跟拍子唱的歌词"
            )
            break  # 报一处即可，重写轮会带全文
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
    # 裁决去位置偏见：随机化发言块顺序（每个块带 speaker 名，主理人按观点质量而非顺序裁决）
    transcript = _shuffled_transcript(rounds)
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
    final: dict[str, Any] = {"error": "定稿失败：上游异常"}
    # 定稿是整场会议的收尾，失败代价高：上游抖动/JSON 解析失败都重试 2 次
    for attempt in range(3):
        try:
            result = await resolved.provider.generate(  # type: ignore[attr-defined]
                final_prompt, resolved.model, temperature=0.7
            )
            candidate = _extract_json(_provider_text(result))
            if candidate.get("error"):
                raise ValueError(str(candidate.get("raw") or candidate["error"])[:120])
            final = candidate
            break
        except Exception as exc:
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
            final = {"error": f"定稿失败：{str(exc)[:80]}"}
    if not final.get("error") and isinstance(final.get("final"), dict):
        final = final["final"]  # 兼容模型偶发输出的嵌套结构
    if not final.get("error"):
        final["lyrics"] = _repair_lyrics(str(final.get("lyrics") or ""))
    checks = [] if final.get("error") else _validate_lyrics(str(final.get("lyrics") or ""))
    return final, checks


async def _with_heartbeat(
    coro_factory, event_type: str = "thinking", interval: float = 25.0
) -> AsyncIterator[dict[str, Any] | tuple[str, Any]]:
    """运行协程并在等待期间周期产出 SSE 心跳事件（防 nginx 读超时断流 → 前端 network error）。

    圆桌每轮发言/定稿是一次长时间 LLM 调用（含重试），nginx proxy_read_timeout
    只按"两次读取间隔"计——每 25 秒发一个心跳事件保持连接有数据流动，
    nginx 永不超时，前端也能实时看到「思考中」状态。

    用法：
        async for ev in _with_heartbeat(lambda: _speak(item)):
            if isinstance(ev, tuple):
                value = ev[1]  # ("result", 协程返回值)
            else:
                yield ev       # 心跳事件直接透传给前端
    """
    task = asyncio.create_task(coro_factory())
    try:
        while True:
            try:
                value = await asyncio.wait_for(asyncio.shield(task), timeout=interval)
                yield ("result", value)
                return
            except asyncio.TimeoutError:
                yield {"type": event_type, "payload": "working"}
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task



# 十三辙韵部表（歌词句尾字 → 辙）：用于押韵校验（比"同字重复"高级——同辙不同字=真押韵）
_RHYME_TABLE: dict[str, tuple[str, ...]] = {
    "发花": ("啊", "巴", "吧", "妈", "花", "华", "家", "牙", "沙", "大", "发", "啥", "拉", "哇", "瓜", "夸", "抓", "夏", "下", "画", "话", "他", "她", "它", "怕", "答", "查", "加", "打", "马", "假"),
    "梭波": ("波", "坡", "佛", "哥", "科", "河", "车", "蛇", "火", "果", "多", "罗", "做", "错", "桌", "说", "托", "过", "国", "活", "货", "落", "朵", "热", "我", "坐", "默", "可"),
    "乜斜": ("别", "灭", "爹", "贴", "列", "姐", "切", "些", "夜", "月", "雪", "缺", "约", "学", "绝", "血", "借", "写", "谢", "叶", "叠", "铁", "节", "解", "结", "些"),
    "姑苏": ("屋", "无", "夫", "服", "古", "鼓", "哭", "苦", "路", "鹿", "兔", "土", "苏", "足", "住", "数", "处", "湖", "炉", "孤", "读", "书", "目", "暮", "骨"),
    "一七": ("衣", "比", "米", "低", "梯", "尼", "离", "理", "力", "期", "七", "齐", "西", "地", "第", "替", "机", "鸡", "记", "气", "日", "自", "此", "思", "词", "你", "里", "起", "去", "雨", "语", "遇", "女", "绿", "曲", "虚", "许", "序", "鱼", "依", "意", "易", "义", "细", "急", "滴", "迹", "系", "喜", "已", "以", "椅", "疑"),
    "怀来": ("哀", "爱", "来", "开", "海", "带", "白", "买", "快", "怪", "外", "帅", "坏", "呆", "待", "猜", "才", "菜", "台", "抬", "拍", "排", "牌", "麦", "卖"),
    "灰堆": ("杯", "飞", "非", "雷", "累", "内", "黑", "背", "美", "妹", "对", "队", "回", "会", "最", "追", "水", "吹", "归", "泪", "碎", "醉", "亏", "危", "灰", "赔", "配"),
    "遥条": ("高", "好", "老", "刀", "早", "草", "跑", "抱", "跳", "笑", "桥", "小", "叫", "鸟", "了", "到", "道", "少", "找", "扫", "烧", "绕", "腰", "要", "药", "票", "飘", "桥", "潮", "照", "烧"),
    "由求": ("头", "口", "走", "楼", "愁", "收", "手", "有", "又", "酒", "久", "牛", "留", "流", "修", "丢", "秋", "周", "州", "豆", "够", "后", "厚", "扣", "漏", "瘦", "透", "邮", "游"),
    "言前": ("山", "寒", "看", "站", "兰", "散", "南", "三", "干", "边", "天", "年", "连", "前", "间", "见", "远", "全", "选", "眼", "脸", "烟", "然", "断", "短", "船", "传", "转", "乱", "慢", "满", "暖", "半", "班", "盘", "安", "案", "岸", "喊", "还", "换", "宽", "关", "管", "惯", "圆", "愿", "怨", "原", "源"),
    "人辰": ("人", "门", "分", "很", "根", "真", "深", "身", "针", "心", "新", "今", "金", "因", "音", "春", "村", "问", "温", "闻", "文", "吻", "尘", "沉", "陈", "臣", "神", "痕", "恨", "认", "忍", "润", "顺", "损", "存", "困", "魂", "昏", "混", "尽", "近", "进", "禁", "紧", "斤", "锦", "亲", "琴", "勤", "林", "邻", "临", "民", "敏", "品", "频", "贫", "云", "运", "韵", "均", "群"),
    "江阳": ("光", "乡", "香", "方", "房", "堂", "长", "张", "场", "汤", "刚", "康", "黄", "忙", "忘", "王", "床", "常", "窗", "唱", "伤", "霜", "双", "爽", "想", "向", "像", "响", "相", "香", "凉", "量", "亮", "两", "辆", "江", "讲", "强", "墙", "枪", "让", "浪", "放", "望", "往", "网", "阳", "洋", "样", "羊", "央", "扬", "羊"),
    "中东": ("风", "灯", "更", "声", "生", "成", "城", "星", "行", "明", "平", "名", "空", "红", "东", "中", "同", "龙", "用", "梦", "痛", "送", "松", "钟", "终", "重", "虫", "冲", "通", "工", "公", "功", "共", "宫", "弓", "洪", "宏", "恒", "衡", "冷", "岭", "零", "灵", "领", "另", "令", "停", "听", "庭", "晴", "情", "清", "请", "庆", "轻", "倾", "琼", "荣", "容", "融", "荣"),
}

# 字 → 辙 的倒排（查句尾字属于哪一辙）
_RHYME_INDEX: dict[str, str] = {}
for _z, _chars in _RHYME_TABLE.items():
    for _c in _chars:
        _RHYME_INDEX.setdefault(_c, _z)


def _severe_checks(checks: list[str]) -> bool:
    """自检中值得自动重写的严重问题（空洞赞颂/作文腔/缺点睛/格言钩子/缺段落/押韵偷懒等）。"""
    return any(
        ("空洞赞颂" in c)
        or ("作文腔" in c)
        or ("点睛" in c)
        or ("格言" in c)
        or ("缺少" in c)
        or ("副歌重复次数不足" in c)
        or ("押韵偷懒" in c)
        or ("无韵" in c)
        or ("长句" in c)
        or ("偏短/单薄" in c)
        or ("太短" in c)
        or ("动机降维" in c)
        or ("符号过密" in c)
        or ("单薄" in c)
        or ("废稿" in c)
        or ("自报家门" in c)
        or ("散文长句" in c)
        or ("暖词复用" in c)
        for c in checks
    )


# 对抗式讨论任务（提案 → 反驳 → 辩护 → 补充 → 裁决）
# 纪律：评审只挑刺不给方案（替代是提案方的事）；提案方允许反驳（不为和谐全盘接受）
def _proposer_task() -> str:
    """提案轮：立人物 + 核心意象 + 副歌钩子，立场鲜明。"""
    return (
        "你是本场第一个发言的提案人：**先为创作对象立一个具体可信的人物原型**"
        "（称呼/名字 + 年龄身份 + 一件只有他/她做得出的具体的事 + 一个具体的失去/代价），"
        "全曲围绕这个人物写，"
        "禁止对着模糊的'你'唱空泛赞歌；"
        "然后提出核心意象（具体可感：物件/生活细节/感官细节，禁抽象大词）"
        "和副歌金句雏形（口语化、朗朗上口、**要有反转**：前一句具体朴素，"
        "后一句意料之外情理之中，如「越过山丘，才发现无人等候」；"
        "禁止用「热乎/温暖/幸福」这类笼统词当情感落点）。"
        "你的方案马上会被质疑——**立场要鲜明，写清你坚持什么、为什么**，别含糊。"
    )


def _critic_task() -> str:
    """反驳轮：纯反对——逐条引用提案原话挑刺，禁止给替代方案。"""
    return (
        "你是本场的质疑者：**逐条引用提案人的原话**，指出其中最致命的 1-2 个具体问题"
        "（意象俗套/人物没立住/副歌钩子弱/空洞口号/白描无点睛）。"
        "**默认否定：除非提案里有你无法反驳的具体证据，否则先当它不合格。**"
        "**禁止给出替代方案或'应该改成…'的建议**——替代是提案人自己的事，你只负责指出问题。"
        "每个批评都要落到提案的原话上，不许空泛地说'质量低'。"
    )


def _defense_task() -> str:
    """辩护轮：针对质疑逐条回应，允许反驳/让步。"""
    return (
        "针对质疑者的每一条批评，**逐条明确表态**：同意 / 反驳 / 部分让步，并给理由。"
        "**允许并且应当反驳**你不认同的批评——如果对方挑错了，就说'这条我不接受，因为…'，"
        "不要为了和谐而全盘接受。对真有道理的批评，才让步并给出实质改进。50-90 字。"
    )


def _supporter_task() -> str:
    """补充轮：基于辩论结果给专业方案，默认怀疑。"""
    return (
        "基于前面的提案与辩论，从你的专业领域给出**可落地的具体方案**"
        "（和声走向/配器/节奏型，具体到调式/拍号/BPM）。"
        "默认怀疑前文，专业判断优先：只有你认为正确的才采纳，不要人云亦云。60-100 字。"
    )


async def _has_unresolved_conflict(
    db: AsyncSession, theme: str, rounds: list[dict[str, str]]
) -> bool:
    """共识检测（需求6：共识就停）——判断辩论是否还有未解决的实质分歧。

    辩护轮后调用：若已收敛（辩护实质回应了关键批评）→ False，跳过补充轮；
    若仍有明显对立 → True，跑补充轮。判断失败时保守返回 True（跑补充轮）。
    """
    transcript = _transcript_block(rounds, limit=1500)
    prompt = (
        f"下面是关于「{theme}」的创作讨论（提案 → 反驳 → 辩护）：\n{transcript}\n\n"
        "判断：提案与反驳之间是否还有「未解决的实质分歧」？\n"
        "- 若辩护轮已实质回应了所有关键批评（达成共识/收敛），has_conflict=false\n"
        "- 若仍有明显对立、关键问题未被回应，has_conflict=true\n"
        '严格输出 JSON（不要任何多余文字）：{"has_conflict": true} 或 {"has_conflict": false}'
    )
    try:
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, temperature=0.0
        )
        data = _extract_json(_provider_text(result))
        return bool(data.get("has_conflict", False))
    except Exception:
        return True  # 判断失败保守处理：跑补充轮


_FINAL_PROMPT = """【第一信条·人民性】（最高原则，一切创作以此为纲）
你从人民中来，为人民而写：作品站在普通人一边，写普通人的真实生活、劳动、尊严与悲欢。
- 不居高临下地"歌颂"：普通人不是"被赞美的对象"，而是有主体性的人——他们的幽默、倔强、柔软、无奈都要是真的
- 用人民的语言：方言、口语、职业黑话，不用文人腔与宣传腔
- 写"在其中的"视角：细节来自生活内部（劳动的手、挤公交的汗、工资条、夜班饭盒），不是旅游式观察
- 禁忌：禁止鸡汤、宣传腔、居高临下的怜悯、把苦难浪漫化
- 语言铁律：歌词必须用普通人日常能听懂的话——专业/技术术语（模型名、参数、代码、行业黑话）只可作人物设定背景，严禁直接写入歌词正文；意象必须来自人的具体生活
- 人名禁令：歌词里严禁「我是XX」自报家门、严禁完整人名直呼——「我是郑玉兰」「老赵，我把它交给你」这类人物卡写法是废稿。讨论里人物可以有名有姓，但歌词里人物的具体性只能靠物件/动作/细节传递（搪瓷缸、掰蛋黄、第五页那道圈），不靠念名字；必须称呼时用「你/她/师傅/老哥」这类口语称呼
- 口语化范例（好歌词是"人"会说的话）：「等拼完车门，我就去报成人高考」「师傅骂我两句，又帮我补了一针」「准考证贴在车模挡风玻璃上，塑封膜起泡了」；
  不是散文诗——「铁皮还留着白天的呼吸」「焊点悄悄排成行」这类作文腔是废稿，写出来就重写
- 点睛铁律：全程白描而不点破 = 废稿——每首歌必须有至少一个「心口之言」时刻：
  ① 人物直接说/唱出心里话（哪怕一句引语或第一人称心声），或
  ② 一句能让人记住的情感点破（把前面的细节收成一句直抵人心的话）
  禁止只有动作和物件、没有一句人物声音或情感落点的"观察报告式"歌词

【歌词性第一律】（歌词首先是"歌"，其次才是"叙事"——不要让题材说明和谱面驱动歌词）
- 一首歌由两样东西驱动：① 一个情绪核心（一句话能说清"唱的到底是哪种心情"）② 一个能反复跟唱、戳中人的钩子句
- 所有意象、细节、物件都服务这个情绪和钩子，禁止反过来——让细节堆砌替代情绪、让题材说明（"48岁女吊车司机的夜班日志"）替代钩子
- 编曲谱面（调式/BPM/和弦/配器）只写进 chords 与 arrangement 字段，**不得驱动或挤占歌词**：歌词里不出现乐理词，也不为"配合和弦"而凑句；谱面再精致，歌词写成流水账/人物卡 = 废稿

【主题挖掘铁律】（表面主题只是氛围，深层主题才是歌——先挖再写）
- 定稿前先完成一次主题挖掘：这个主题下"谁、在哪儿、经历了什么、心里压着什么"？
  例：主题"烟雨朦胧"→ 深层主题「雨声中的十年守候：修伞老人等胥江翻船的亡人」；
  例：主题"诗与远方"→ 深层主题「老周守的不是远方，是塌方后别人的路」。
- 歌词必须服务深层主题（人物/事件/情绪），禁止被表面氛围词（烟雨/江南/唯美/远方）带跑；
  表面氛围只允许作为环境底色（一两句），不许成为情绪主调。
- 自检：如果歌词删掉氛围词后还剩不下"一个人/一件事/一份心"，说明深层主题没立住 = 废稿

【叙事弧线铁律】（叙事歌的副歌揭底时机 = 情绪设计）
- 理想弧线：陌生 → 好奇 → 真相 → 理解 → 心碎。主歌1立人物（只铺场景，不揭底），
  主歌2才给转折/真相，副歌是情绪站口，桥段点破。
- 禁止主歌1结束就把底牌全掀了——"先给结果再解释原因"会提前耗尽情绪，
  除非是'留个响'式 hook 设计（见副歌递进铁律）。

【副歌三遍递进铁律】（hook 是情绪骨架，不是复读机）
- 两遍副歌鼓励"语义递进"：第一遍 hook 只露一半（陌生/好奇），第二遍补全真相（理解），
  桥段点破（心碎）。每遍 hook 换一个落点，逐层加深，禁止两遍一字不差地简单重复。
- '留个响'式三遍递进是范例：①「留个响，夜里像有人推门」（第一遍，设悬念）
  ②「留个响，夜里不像一个人」（第二遍，揭开失去）③「留个响」（桥段只剩词根，情绪全在里面）。
- 若 hook 无法递进，两遍副歌至少第二遍要微调语义落点，禁止纯复制粘贴。

【人物价值层级铁律】（人物先于主题；创伤/爱情不得覆盖高层价值——坍缩 = 废稿）
- 人物是分层的：信仰/使命/职业伦理 > 家庭/关系 > 情感 > 欲望。
  人物的重大行为（守/等/留/坚持）必须能从其高层价值推导，禁止用"亡妻/思念/爱情"解释一切。
- 反例（价值坍缩）："妻子去世 → 他守桥 → 桥成了亡妻纪念碑"——人物被爱情解释吞掉。
  正例（信仰形成）："他本来相信桥的意义是让人安全抵达；妻子的事故让信仰变得具体；
  因为已经失去过一个人，所以更不能再让别人失去"——创伤是信仰的起点，不是动机的全部。
- 自检三问：①删掉创伤，人物还成立吗？②没有妻子，他还会做这个选择吗？③行为能反推人物
  （"他果然会这么做"）还是只为催泪（"作者让我哭"）？
- 允许人物有矛盾价值：负责+骄傲+讨厌形式主义+爱钱+不善表达，同时存在才像人。

【反语义收敛铁律】（禁止第一联想——"雨=思念/桥=人生/旧物=回忆/老人=孤独/职业=奉献"）
- 主题先展开多语义方向（职业/技术/经济/社会/身体/环境/制度/劳动），再选人物与事件；
  禁止直接进"烟雨-旧伞-青瓦-故人-离别"等高概率语义空间。
- 物件首先是物件：搪瓷盆先是接漏水的盆，意义从使用中涌现；禁止一开始就赋予象征意义。
- 不解释读者能懂的意义；允许留白；禁止强行升华（平凡→哲理→时代→永恒）。
- 禁止"死亡+遗物+回忆""旧物+雨+思念""老人+孤独+等待""桥+爱情+牺牲"模板组合直接套用；
  若使用其中元素，必须有具体职业逻辑/现实细节支撑，不能只靠情绪堆叠。

你是{name}（{field}），担任这场创作圆桌的主理人兼主编。产出定稿前先自查，再产出高质量定稿。

【裁决要求】（定稿前必做——把讨论收成明确的取舍，禁止"综合了事"）
- 逐条引用讨论中的原话，明确记录：**采纳了谁的具体哪句、否决了谁的具体哪句、为什么**
- 裁决基于质量而非发言长度——**不要偏爱更长或更靠后的发言**，短而准的意见同样采纳
- 若无实质分歧，如实写"各方一致，无否决项"；有分歧才裁决
严格输出 JSON（不要任何多余文字）：

{{
  "verdict": "裁决记录（2-4 条，每条引用原话：采纳了〈角色名〉的「…」/否决了〈角色名〉的「…」，因为…）",
  "title": "歌名（2-6 字，有记忆点）",
  "lyrics": "定稿歌词（标【主歌1】【预副歌】【副歌】【主歌2】【副歌】【桥段】【主歌3】【副歌】），详见下方结构要求",
  "chords": "逐段和弦谱（每段一行：段落标记 + 和弦进行，如：【主歌1】C G Am F ｜【副歌】F G C C），给吉他弹唱/Suno 直接用",
  "arrangement": "定稿编曲思路（80-150 字：风格/BPM/调式/乐器层次/段落动态，必须落实讨论中的修正）",
  "style_en": "给 AI 音乐工具的英文生成指令（4 块：VOCAL / MOOD / SPACE / ARRANGEMENT，硬参数收敛到 4 项，见 style_en 指令铁律）"
}}

【style_en 生成指令铁律】（Suno v4.5 对自然语言指令理解增强——按"生成指令"写，不是写制作说明）
- 分四块写，每块 1-2 句：
  · VOCAL（人声）：写具体质感（low gravelly restrained male, close-mic, narrative whispering），
    禁止"深情男声/唯美女声"这类空词
  · MOOD（情绪）：写具体心境（damp, lonely, restrained, resigned），
    禁止"唯美/忧伤/烟雨朦胧"这类氛围词
  · SPACE（声场）：写空间与距离（small room, close, rainy night, room tone）
  · ARRANGEMENT（编曲）：写乐器入场顺序与动态走向（acoustic guitar → soft bass →
    clean electric → minimal drums），硬参数（BPM/调式）不超过 4 个且必须是核心控制项
- 环境音写法：写 subtle distant rain ambience, naturally blended into the acoustic recording；
  禁止 heavy rain sound effects（雨是音乐的一部分，不是音效）。关键声音设计
  （如结尾雨滴搪瓷盆单音）单独写清并标 long natural decay
- 总长 60-90 词，直接可粘贴给 Suno/天音

【第一步·自查修正清单】（逐条落实，严禁任何被批评的元素回归）
{fix_list}

【歌词结构硬要求】（违者视为废稿；完整长曲结构，两段式，约 5-6 分钟）
- 段落顺序：**【主歌1】 → 【预副歌】 → 【副歌】 → 【主歌2】 → 【副歌】 → 【桥段】 → 【主歌3】 → 【副歌】(最终副歌)**
- 两段式说明（供 Suno Extend / 音频拼接）：
  · **Part A** = 主歌1 → 预副歌 → 副歌 → 主歌2 → 副歌（约 500 字，可独立成曲）
  · **Part B** = 桥段 → 主歌3 → 最终副歌（约 400 字，续写部分）
  · 两段语义连贯（Part B 承接 Part A 的叙事/情绪），Extend 从桥段处续接自然
- 段落次数：**【主歌1】1 次、【主歌2】1 次、【主歌3】1 次、【桥段】1 次、【副歌】3 次、【预副歌】1-2 次**。禁止同一标签无意义重复。
- 【主歌1】5-7 句：**一个场景**（不是时间线），每句有动作/感官/情节，禁止清单式堆砌
- 【预副歌】2-3 句：情绪抬升段——从叙事过渡到副歌，句长渐短、张力上扬
- 【副歌】4-5 句：第 1-2 句是**金句钩子**（口语化、有意象、朗朗上口、可直接跟唱），第 3-5 句收束；三遍副歌语义递进（见副歌三遍递进铁律）
  **钩子事件化铁律**：钩子必须是一个「具体事件/画面/动作」（谁在哪儿、做了什么、看见了什么、说了什么），
  禁止「道理对仗句」——把生活总结成一句格言的对仗句式是废稿，例如「车铃响三声，夜路短一截」「今天就没白过」「他走他的路，我补我的乐」「路—人—家」这类；
  要写就写具体事件（如「栽进排水沟」「老周扶腰骂自己：当年那跟头白摔了」「我那年下夜班，铃是个哑巴」），让金句长在动作和画面里，不飘在道理里
  **钩子可唱性铁律**：钩子必须能**独立唱出来、能反复跟唱**（短句、口语、有情感落点，像「和我在成都的街头走一走」），
  禁止写成"动作汇报"——只罗列做了什么、没有情感反转或戳心一击（如「我掰一半给野猫留着」只是汇报善良，缺一个让心里咯噔一下的落点）
  **副歌铺垫铁律**：副歌里引用的具体人物/情感/物件，必须先在主歌里出现过并铺垫——听众第一次听到副歌时，必须已经知道"这个人/这件事"是谁/是什么。禁止副歌凭空引入新人物或新情感（如副歌突然冒出"像闺女喊我别着凉"，而主歌对"闺女"只字未提）
  **钩子范例与解剖**（钩子的力量来自"反转"，不是形容词、不是温度词——照着这个结构写，但禁止照抄原句）
  - 「和我在成都的街头走一走，直到所有的灯都熄灭了也不停留」——具体动作(走一走) + 时间反转(走到灯全熄也不停)，把"舍不得走"顶出来，不直说舍不得
  - 「爱上一匹野马，可我的家里没有草原」——具体(爱上野马) + 反转(没有草原=留不住)，用隐喻一句说尽"我给不了你"
  - 「越过山丘，才发现无人等候」——动作(越过山丘=拼命往前走) + 反转(回头才发现没人在等)，把怅然用一个画面点破
  - 规律：**前一句具体朴素，后一句"戳破"——意料之外、情理之中的反转**；落点必须长在动作和画面里，禁止用"热乎/温暖/幸福"这类笼统词当落点
- 【主歌2】5-7 句：转折/新细节，情绪递进，不得复述主歌1
- 【桥段】3-4 句：升华点，至少一处"心头一动"的妙句；同时是 Part A/B 的衔接点
- 【主歌3】4-6 句：Part B 新进展——余波/回望/新的细节，不得重复主歌1/2
- 全曲 **900-1100 字**（约 5-6 分钟的完整长曲；两段式，Part A ≈500 字 + Part B ≈400 字；低于 800 字是短版）

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
4. **常识自检**：每个意象都要经得起物理/生活常识——橡皮擦擦铅笔字不会让纸"发潮"、热敏小票晒了会褪色、柴油味不是"香"的；违反常识的意象是硬伤，出现即重写

【作词技法铁律】（专业词人的基本功——不是会写句子就叫作词）
1. **用词讲究质感**：动词选有质地有动作感的（勒/楔/嵌/搪/浸/楔），拒绝"弄/放/拿"这类滑动词；名词具体到能看见（三号扳手/退票窗口/搪瓷缸沿），拒绝抽象名词堆叠
2. **韵脚是设计不是碰巧**：每段定一个主韵（-ang/-an/-i/-u 等），句尾字从主韵部里选，副歌 hook 句尾必须落在主韵上；换韵要有意（主歌2 换韵推进情绪，桥段可转韵收束）；禁止每句尾字各不相关的散韵
3. **句内节奏 = 旋律气口**：一行歌词的断句点就是旋律换气点——短-长-短交替，避免连续同长度句（像数拍子）；开口音（a/ang/an）给强拍与副歌爆发，闭口音（i/u）给低回与留白
4. **意象第二联想**：第一联想（雨=思念等）禁用后还要拒绝第二层惰性——"等待"写成"门框被磨亮的木纹"，"失去"写成"柜里那双鞋还按原样摆着"，让读者自己去接
5. **名词说话、动词做事**：禁止"形容词+名词"的惰性搭配（温暖的灯/孤独的夜/漫长的等待）——名词自带画面，动词自带动作，形容词留给真正需要的地方

【作曲专业规范】（编曲不是乐器清单——是声场、和声、动态的完整设计）
1. **和声贴情绪且有色彩**：主歌用开放排列/挂留（sus2/add9）留呼吸，副歌给强进行（I-IV-V-vi 或 IV-V-iii-vi），桥段可离调（bVII/降二级）制造"心头一动"；**禁止全曲一个 Em-C-G-D 万能和弦循环**
2. **调式先行**：先定色彩——自然小调=忧伤 / 五声=东方 / 混合利底亚=公路感 / 多利亚=苍凉，再定音区与转调点（副歌可升调半音/全音推进）；和弦谱写清楚，不是流水账
3. **声场三层**：近（人声/主奏）— 中（和声/铺底）— 远（环境/空气声），每层给频段定位（人声 2-4kHz、贝斯 80-200Hz、铺底避开人声频段），禁止所有乐器挤在中频
4. **动态弧线**：主歌最轻（人声+一件乐器）→ 预副歌加节奏 → 副歌全乐队但留一轨呼吸（鼓只在反拍/军鼓芯）→ 桥段撤到最空 → 最终副歌最满；结尾留空间（长衰减/单音），不糊满
5. **人声设计**：音区（男声 E3-E4 舒适区）、气息（气声/喉音/胸腔共鸣对应情绪）、咬字（句尾收音），禁止只写"深情男声"

【重量铁律】（歌词没重量 = 水——白描不等于轻，但没有代价、没有时间、没有对照就是水）
1. **必须有一个"代价"**：人物为这件事失去了什么、放弃了什么（一个具体、不可逆的失去，如"报名表锁进铁皮柜""女儿去了东莞流水线"）。这些代价要写进歌词，不能只停在讨论里；只有动作没有代价 = 水
2. **意象必须承载时间跨度**：一个物件要压着"从哪年到哪年"的重量（"从她十二岁纳到二十三岁"），不是现在时的静物计数（"纳了三回"只有量，没有年的重量）
3. **必须有"过去 vs 现在"的对照**：至少一处，一句过去（完整/美好/在场）+ 一句现在（空/缺/不在），让失去感从对照里长出来，而不是靠形容词喊
4. 重量范例（重量长在哪，别照抄）：「如此生活三十年，直到大厦崩塌」= 时间(三十年)+代价(崩塌)；「越过山丘，才发现无人等候」= 半生奋斗+落空；「爱上一匹野马，可我的家里没有草原」= 想要+给不起

【暖词禁令】（情感落点反复用同一套暖意象 = 词汇偷懒）
- 禁止用「热乎/热气/焐软/焐热/暖烘烘」这类笼统暖词给情感收尾——"这一路的热乎""把累都焐软了"是把情感抽象成"温度"，等于没写出具体的东西
- 每处情感落点必须落在不同的具体物件/动作/声音上（水壶嘴响、搪瓷缸盖、方向盘磨亮的皮、加油小票背面那句"慢些"），禁止同一个"热/暖/焐"字从头用到尾

【歌词感铁律】（这是"歌"，不是分行散文——检验标准是能否跟着拍子哼唱；与下方文化硬指标冲突时以此为准）
1. 句长：6-14 字为主（短句 4-8 字、中句 9-14 字），单句禁超 16 字；**段内句长要有起伏**（短-中-长节奏，像呼吸），禁止整段全是 5-8 字短句平推（那是口号，不是叙事）
2. 押韵：每段至少 2 处句尾押韵；副歌句句押或隔句押，句尾字各不相同（禁整段押同一个字）；押不上就自然断句，禁硬凑单字
3. 副歌 4 句：第 1-2 句是最抓耳的 hook（能独立反复跟唱），第 3-4 句收束；两遍副歌**结构对齐、语义递进**（hook 重复或递进加深，见副歌递进铁律；禁止整段一字不差复制）
4. 节奏：读出来有呼吸感，像人说话有轻重缓急；禁止一句塞多个并列信息
5. 韵律范例（模仿其节奏与押韵结构，禁止照抄内容）：
   - 「和我在成都的街头走一走 / 直到所有的灯都熄灭了也不停留」
   - 「越过山丘 / 才发现无人等候」
   - 「我曾经跨过山和大海 / 也穿过人山人海」
6. 写完后自我检验：每段能跟着拍子哼出来吗？句尾能押上吗？不能就重写这段

【信息密度铁律】（单薄 = 废稿——短句化后细节全丢只剩骨架）
- 主歌 5-8 句、桥段 3-4 句；每段至少 2 个具体细节（物件/动作/声音/身体感受），禁止骨架式口号
- 全曲 260-450 字；写完数一数：每段若只剩 3 句、细节全丢 → 重写加厚
- 细节要"长在句子里"：每句自带一个画面/声音/触感，不是单独罗列

【文化硬指标】（至少满足 3 条，否则视为废稿）
1. 至少一处**妙句**：通感 / 双关 / 虚实相生，让人心头一动
2. 至少一处**古典文化的当代化用**：唐诗宋词意象、成语反转、典故新解——注意：要**自己创造**化用，禁止直接照抄任何现成句子
3. **句尾自然收束（通顺永远优先，押韵是基本要求——见【歌词感铁律】第 2 条）**：
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
        # 风格基调：显式指定优先；未指定时从主题文本自动检测（"矿工清晨的叙事民谣"→民谣）
        style = req.style or _detect_style(req.theme)
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
        # 词曲专业常驻注入：无论主题，带上创作技法文档（专业地基，让模型边查边写）
        try:
            from app.services.knowledge_materials import retrieve_music_pro_notes

            pro_notes = await retrieve_music_pro_notes(db, user.id)
            if pro_notes:
                kb_block += "\n\n" + pro_notes
        except Exception:
            pass
        yield _sse_event({"type": "materials", "titles": material_titles})
        # 第 0 轮：AI 按主题定制会议阵容（4 位专业角色）
        yield _sse_event({"type": "cast_start"})
        cast_prompt = (
            _CAST_PROMPT.format(theme=req.theme, style=style or "（自由）")
            + _style_profile_block(style)
            + kb_block
        )
        resolved = await resolve_text_provider(db, req.model)
        cast_list: list[dict[str, Any]] = []
        # 选角质量校验：通用占位（「专家N」/空 persona）视为发挥波动 → 重试一次
        for _attempt in range(2):
            try:
                cast_result = await resolved.provider.generate(  # type: ignore[attr-defined]
                    cast_prompt, resolved.model, temperature=0.9
                )
                cast_data = _extract_json(_provider_text(cast_result))
                roles = cast_data.get("roles") or []
                if isinstance(roles, list) and len(roles) >= 2:
                    cast_list = [
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
                    generic = sum(
                        1
                        for c in cast_list
                        if str(c["name"]).startswith("专家") or not c["persona"].strip()
                    )
                    if generic < max(1, len(cast_list) // 2):
                        break  # 定制合格
                cast_list = []  # 通用占位/数量不足 → 重试或 fallback
            except Exception:
                cast_list = []
        if not cast_list:
            cast_list = [
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
        if len(cast_list) < 4:  # 数量不足补位
            cast_list = (
                cast_list
                + [
                    {
                        "name": f"专家{n}",
                        "field": "音乐创作",
                        "persona": "",
                        "icon": "🎙️",
                        "order": n,
                        "finalizer": False,
                    }
                    for n in range(len(cast_list) + 1, 5)
                ]
            )[:4]
        ordered = sorted(cast_list, key=lambda r: int(r.get("order") or 99))
        yield _sse_event({"type": "cast", "cast": cast_list})

        # 对抗式议程：提案 → 反驳 → 辩护 → 补充（quick 模式跳过补充，裁决在定稿轮）
        proposer = ordered[0] if ordered else None
        critic = next((r for r in ordered if int(r.get("order") or 99) == 4), None)
        supporters = [
            r
            for r in ordered
            if r is not proposer and r is not critic and not r.get("finalizer")
        ]
        # 核心对抗闭环：提案 → 反驳 → 辩护
        core: list[dict[str, Any]] = []
        if proposer is not None:
            core.append(
                {
                    "role": proposer,
                    "task": _proposer_task(),
                    "stance": "你立场鲜明，敢于坚持自己的方案，不怕被质疑。",
                }
            )
        if critic is not None and proposer is not None:
            core.append(
                {
                    "role": critic,
                    "task": _critic_task(),
                    "stance": "你默认否定，除非有具体证据；你只挑刺，不给替代方案。",
                }
            )
        if proposer is not None and critic is not None:
            core.append(
                {
                    "role": proposer,
                    "task": _defense_task(),
                    "stance": "你敢于反驳不认同的批评，不为和谐而全盘接受。",
                }
            )

        rounds: list[dict[str, str]] = []

        async def _speak(item: dict[str, Any]) -> str:
            role = item["role"]
            persona = (
                f"你是{role.get('name')}（{role.get('field')}）：{role.get('persona')}\n"
                f"【本轮立场】{item['stance']}"
            )
            # 自我中心投影：只给上一个对手的原话（不全文拼接，防复读套话）
            opponent_block = ""
            if rounds:
                opp = rounds[-1]
                opponent_block = f"{opp['speaker']}：{opp['content']}"
            prompt = _speaker_prompt(
                req.theme,
                style,
                str(item["task"]),
                opponent=opponent_block,
                extra=kb_block,
            )
            resolved = await resolve_text_provider(db, req.model)
            # 上游偶发超时/5xx：重试 2 次再放弃，避免单次抖动中断整轮讨论
            last_err = ""
            for attempt in range(3):
                try:
                    result = await resolved.provider.generate(  # type: ignore[attr-defined]
                        prompt, resolved.model, system=persona, temperature=0.9
                    )
                    return _provider_text(result).strip()
                except Exception as exc:
                    last_err = str(exc)[:80]
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
            return f"（{role.get('name')} 本轮发言生成失败：{last_err or '上游异常'}）"

        for idx, item in enumerate(core, start=1):
            role = item["role"]
            speaker = str(role.get("name") or f"专家{idx}")
            yield _sse_event({"type": "round_start", "speaker": speaker, "round_no": idx})
            text = ""
            async for ev in _with_heartbeat(lambda: _speak(item)):
                if isinstance(ev, tuple):
                    text = ev[1]
                else:
                    yield _sse_event(ev)
            rounds.append({"speaker": speaker, "content": text})
            yield _sse_event({"type": "round", "speaker": speaker, "content": text})

        # 需求6：共识检测——辩护后仍有分歧才跑补充轮（共识就停，不固定轮次）
        if not req.quick and supporters:
            has_conflict = await _has_unresolved_conflict(db, req.theme, rounds)
            if has_conflict:
                for sup in supporters:
                    item = {
                        "role": sup,
                        "task": _supporter_task(),
                        "stance": "你默认怀疑前文，专业判断优先，不人云亦云。",
                    }
                    speaker = str(sup.get("name") or "补充")
                    yield _sse_event(
                        {"type": "round_start", "speaker": speaker, "round_no": len(rounds) + 1}
                    )
                    text = ""
                    async for ev in _with_heartbeat(lambda: _speak(item)):
                        if isinstance(ev, tuple):
                            text = ev[1]
                        else:
                            yield _sse_event(ev)
                    rounds.append({"speaker": speaker, "content": text})
                    yield _sse_event({"type": "round", "speaker": speaker, "content": text})

        # 定稿轮：主理人主编把关 + 自检 + 严重问题自动重写一轮 + 自动存入「我的作品」
        finalizer = next(
            (r for r in ordered if r.get("finalizer")), ordered[0] if ordered else None
        )
        yield _sse_event({"type": "final_start"})
        final: dict[str, Any] = {}
        checks: list[str] = []
        async for ev in _with_heartbeat(
            lambda: _produce_final(
                db,
                theme=req.theme,
                style=style,
                finalizer=finalizer,
                rounds=rounds,
                kb_block=kb_block,
            )
        ):
            if isinstance(ev, tuple):
                final, checks = ev[1]
            else:
                yield _sse_event(ev)
        rewrote = False
        if not final.get("error") and _severe_checks(checks):
            rewrote = True
            async for ev in _with_heartbeat(
                lambda: _produce_final(
                    db,
                    theme=req.theme,
                    style=style,
                    finalizer=finalizer,
                    rounds=rounds,
                    kb_block=kb_block,
                    rewrite_warnings=checks,
                )
            ):
                if isinstance(ev, tuple):
                    final, checks = ev[1]
                else:
                    yield _sse_event(ev)
        work_id = ""
        if not final.get("error"):
            try:
                work_id = await _auto_save_work(
                    db,
                    user_id=user.id,
                    theme=req.theme,
                    style=style,
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
                "cast": cast_list,
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
        # 风格基调：沿用定稿风格；未指定时从主题检测
        style = req.style or _detect_style(req.theme)
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
        try:
            from app.services.knowledge_materials import retrieve_music_pro_notes

            pro_notes = await retrieve_music_pro_notes(db, user.id)
            if pro_notes:
                kb_block += "\n\n" + pro_notes
        except Exception:
            pass
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
                f"风格基调：{style or '（自由）'}\n"
                f"{_style_profile_block(style)}"
                f"{kb_block}"
                f"\n\n【前序讨论】\n{base or '（无）'}\n\n"
                f"【当前定稿歌词】\n{prev_lyrics[:1500]}\n\n"
                f"【本轮任务】{task}"
            )
            resolved = await resolve_text_provider(db, req.model)
            async def _reply() -> str:
                try:
                    result = await resolved.provider.generate(  # type: ignore[attr-defined]
                        prompt, resolved.model, system=persona, temperature=0.9
                    )
                    return _provider_text(result).strip()
                except Exception as exc:
                    return f"（发言中断：{str(exc)[:80]}）"

            text = ""
            async for ev in _with_heartbeat(_reply):
                if isinstance(ev, tuple):
                    text = ev[1]
                else:
                    yield _sse_event(ev)
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
            style=style or "（自由）",
            style_profile=_style_profile_block(style),
            transcript=(
                f"【听众新要求】{req.question}\n\n"
                f"【原定稿】\n{prev_lyrics[:1500]}\n\n"
                f"【讨论记录】\n{transcript}"
            ),
        )
        resolved = await resolve_text_provider(db, req.model)
        async def _finalize() -> dict[str, Any]:
            final: dict[str, Any] = {"error": "定稿失败：上游异常"}
            for attempt in range(3):
                try:
                    result = await resolved.provider.generate(  # type: ignore[attr-defined]
                        followup_prompt, resolved.model, temperature=0.7
                    )
                    candidate = _extract_json(_provider_text(result))
                    if candidate.get("error"):
                        raise ValueError(str(candidate.get("raw") or candidate["error"])[:120])
                    return candidate
                except Exception as exc:
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                    final = {"error": f"定稿失败：{str(exc)[:80]}"}
            return final

        final: dict[str, Any] = {}
        async for ev in _with_heartbeat(_finalize):
            if isinstance(ev, tuple):
                final = ev[1]
            else:
                yield _sse_event(ev)
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
                    style=style,
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
