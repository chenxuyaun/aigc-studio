"""通用创作圆桌引擎：多角色真讨论（SSE 逐轮实时生成，角色按主题定制）。

把音乐的圆桌流程通用化：任何内容创作领域（文案/提示词/角色卡/图片/视频/漫画）
都能开一场"定制阵容 → 真讨论 → 批评带替代 → 主编把关定稿"的会议。
每轮发言携带前序全部发言（真正的多轮讨论）；定稿按领域模板产出。

领域模板（DOMAINS）：
- 阵容生成指令（该领域该请谁）
- 讨论任务模板（首轮/补充/挑刺/回应/修正）
- 定稿格式要求（领域产物的结构）
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.provider_resolver import resolve_text_provider

# ===== 领域模板 =====

_DOMAINS: dict[str, dict[str, str]] = {
    "copy": {
        "label": "文案",
        "cast": """你是「创作圆桌」的选角导演。根据创作需求，为这场文案创作会量身定制 4 位专业角色——
不是通用的岗位，而是真正贴合这个需求的专家（如：营销文案鬼才 / 目标用户代表 / 品牌总监 / 挑剔的主编）。
严格输出 JSON：{{"roles": [{{"name": "2字名", "field": "专业领域", "persona": "人设40-60字", "icon": "emoji", "order": 1, "finalizer": false}}]}}
要求：4 位领域互补紧扣需求；一位是挑剔的读者/评审（order 4）；一位是主编/主理人（finalizer=true）。""",
        "task_first": "你率先发言：从你的专业领域出发，提出这篇内容的核心创意方向（角度/结构/金句/口吻），必须具体可落地，60-100 字。",
        "task_mid": "基于前序发言补充：从你的专业领域给出可落地的具体方案（结构/表达/数据/案例），60-100 字。",
        "task_critic": "你担任挑剔的读者：毒舌挑刺（角度平庸/表达老套/结构拖沓/不接地气），每个被批评的点都要给一个反方向替代，60-100 字。",
        "task_reply": "回应挑剔者的批评：必须实质性改变至少一个方案点（换角度/换结构/换表达），最多辩护 1 点且要有理由，50-90 字。",
        "task_fix": "根据讨论修正你的方案：必须用至少一个全新的核心创意替换被批评的部分，禁止换说法，50-90 字。",
        "final": """你是{name}（{field}），担任主理人兼主编。产出定稿前先自查（从讨论中提取被批评元素，定稿严禁回归），再产出高质量定稿。
严格输出 JSON（不要任何多余文字）：
{{
  "title": "标题/主题名（有吸引力）",
  "content": "定稿正文（500-1200 字：开头抓人、结构清晰、金句至少 2 处、结尾有钩子；具体落地、有细节有例子，禁止空话套话）",
  "style": "风格说明（50 字）"
}}
【铁律】落地（具体场景/人物/数据/例子，禁止抽象堆砌）；文化（至少 1 处妙句或典故当代化用）；每段必须有信息增量。

创作需求：{theme}
{extra}

【完整讨论记录】
{transcript}""",
    },
    "prompt": {
        "label": "提示词",
        "cast": """你是「创作圆桌」的选角导演。根据需求，为这场提示词创作会量身定制 4 位专业角色——
（如：提示词工程师 / 目标用户代表 / 技术评审（懂模型能力边界）/ 挑剔的验收人）。
严格输出 JSON：{{"roles": [{{"name": "2字名", "field": "专业领域", "persona": "人设40-60字", "icon": "emoji", "order": 1, "finalizer": false}}]}}
要求：4 位领域互补紧扣需求；一位是挑剔的验收人（order 4）；一位是主理人（finalizer=true）。""",
        "task_first": "你率先发言：提出这个提示词的核心设计方向（角色设定/任务拆解/输出格式/约束条件），必须具体，60-100 字。",
        "task_mid": "基于前序发言补充：从你的专业领域给出可落地的具体设计（结构/示例/边界条件/防呆设计），60-100 字。",
        "task_critic": "你担任挑剔的验收人：毒舌挑刺（指令含糊/示例缺失/约束不足/输出不可控），每个被批评的点都要给一个反方向替代，60-100 字。",
        "task_reply": "回应挑剔者的批评：必须实质性改进至少一个设计点（补约束/加示例/改结构），最多辩护 1 点且要有理由，50-90 字。",
        "task_fix": "根据讨论修正你的方案：必须用至少一个全新的设计思路替换被批评的部分，禁止换说法，50-90 字。",
        "final": """你是{name}（{field}），担任主理人。产出定稿前先自查（被批评元素严禁回归），再产出高质量定稿。
严格输出 JSON（不要任何多余文字）：
{{
  "title": "提示词名称",
  "content": "最终提示词全文（结构：角色设定/任务/步骤/输出格式/约束/示例；指令明确无歧义，可直接复制使用，300-900 字）",
  "style": "使用说明（50 字：适合场景）"
}}
【铁律】指令可执行（每步都有明确产出）；约束完备（长度/风格/禁忌）；含至少 1 个输入输出示例。

创作需求：{theme}
{extra}

【完整讨论记录】
{transcript}""",
    },
    "character_card": {
        "label": "角色卡",
        "cast": """你是「创作圆桌」的选角导演。根据需求，为这场角色卡创作会量身定制 4 位专业角色——
（如：人设策划 / 性格心理学顾问 / 剧情编剧（设计背景故事）/ 挑剔的扮演玩家）。
严格输出 JSON：{{"roles": [{{"name": "2字名", "field": "专业领域", "persona": "人设40-60字", "icon": "emoji", "order": 1, "finalizer": false}}]}}
要求：4 位领域互补紧扣需求；一位是挑剔的扮演玩家（order 4）；一位是主理人（finalizer=true）。""",
        "task_first": "你率先发言：提出角色的核心设定方向（身份/性格内核/矛盾点/说话风格），必须具体有辨识度，60-100 字。",
        "task_mid": "基于前序发言补充：从你的专业领域给出可落地的具体设计（背景故事/行为逻辑/关系网），60-100 字。",
        "task_critic": "你担任挑剔的扮演玩家：毒舌挑刺（人设扁平/动机不足/说话没辨识度/难以扮演），每个被批评的点都要给一个反方向替代，60-100 字。",
        "task_reply": "回应挑剔者的批评：必须实质性改进至少一个设定点（加深动机/加怪癖/改口癖），最多辩护 1 点且要有理由，50-90 字。",
        "task_fix": "根据讨论修正你的方案：必须用至少一个全新的设定细节替换被批评的部分，禁止换说法，50-90 字。",
        "final": """你是{name}（{field}），担任主理人。产出定稿前先自查（被批评元素严禁回归），再产出高质量定稿。
严格输出 JSON（不要任何多余文字）：
{{
  "title": "角色名",
  "content": "角色卡定稿（结构：身份背景/性格内核/矛盾与秘密/说话风格与口癖/开场白 first_mes/扮演要点；300-800 字，可直接导入 SillyTavern）",
  "style": "扮演建议（50 字）"
}}
【铁律】人设有记忆点（至少一个独特怪癖或矛盾）；动机完整；说话风格有明显辨识度；开场白直接进入情境。

创作需求：{theme}
{extra}

【完整讨论记录】
{transcript}""",
    },
    "image": {
        "label": "图片",
        "cast": """你是「创作圆桌」的选角导演。根据画面需求，为这场图片 prompt 创作会量身定制 4 位专业角色——
（如：美术指导 / 摄影或插画师 / 甲方代表 / 挑剔的评审（懂构图光影））。
严格输出 JSON：{{"roles": [{{"name": "2字名", "field": "专业领域", "persona": "人设40-60字", "icon": "emoji", "order": 1, "finalizer": false}}]}}
要求：4 位领域互补紧扣需求；一位是挑剔的评审（order 4）；一位是主理人（finalizer=true）。""",
        "task_first": "你率先发言：提出画面的核心构想（主体/构图/光影/色调/风格），必须具体可画，60-100 字。",
        "task_mid": "基于前序发言补充：从你的专业领域给出可落地的具体方案（镜头/色彩/质感/细节），60-100 字。",
        "task_critic": "你担任挑剔的评审：毒舌挑刺（构图平庸/光影含糊/风格混乱/细节缺失），每个被批评的点都要给一个反方向替代，60-100 字。",
        "task_reply": "回应挑剔者的批评：必须实质性改进至少一个画面要素（改构图/调光影/换风格），最多辩护 1 点且要有理由，50-90 字。",
        "task_fix": "根据讨论修正你的方案：必须用至少一个全新的画面设计替换被批评的部分，禁止换说法，50-90 字。",
        "final": """你是{name}（{field}），担任主理人。产出定稿前先自查（被批评元素严禁回归），再产出高质量定稿。
严格输出 JSON（不要任何多余文字）：
{{
  "title": "画面名称",
  "content": "最终图片 prompt（结构：主体描述/场景/构图与镜头/光影色调/风格与质感/细节清单；150-350 字，可直接提交文生图）",
  "style": "风格标签（英文逗号分隔，如：cinematic, golden hour, 8k）"
}}
【铁律】主体明确可画；构图光影具体；风格统一不混搭；细节可执行（色彩/材质/氛围）。

创作需求：{theme}
{extra}

【完整讨论记录】
{transcript}""",
    },
    "video": {
        "label": "视频",
        "cast": """你是「创作圆桌」的选角导演。根据需求，为这场短视频创作会量身定制 4 位专业角色——
（如：导演（分镜节奏）/ 编剧（脚本叙事）/ 运营（平台流量）/ 挑剔的观众）。
严格输出 JSON：{{"roles": [{{"name": "2字名", "field": "专业领域", "persona": "人设40-60字", "icon": "emoji", "order": 1, "finalizer": false}}]}}
要求：4 位领域互补紧扣需求；一位是挑剔的观众（order 4）；一位是主理人（finalizer=true）。""",
        "task_first": "你率先发言：提出这支视频的核心创意（主题钩子/结构/时长/风格），必须具体，60-100 字。",
        "task_mid": "基于前序发言补充：从你的专业领域给出可落地的具体方案（分镜/文案/节奏/平台适配），60-100 字。",
        "task_critic": "你担任挑剔的观众：毒舌挑刺（前 3 秒无钩子/节奏拖沓/情绪断层/同质化），每个被批评的点都要给一个反方向替代，60-100 字。",
        "task_reply": "回应挑剔者的批评：必须实质性改进至少一个环节（改钩子/调节奏/换结构），最多辩护 1 点且要有理由，50-90 字。",
        "task_fix": "根据讨论修正你的方案：必须用至少一个全新的创意替换被批评的部分，禁止换说法，50-90 字。",
        "final": """你是{name}（{field}），担任主理人。产出定稿前先自查（被批评元素严禁回归），再产出高质量定稿。
严格输出 JSON（不要任何多余文字）：
{{
  "title": "视频标题",
  "content": "成片方案定稿（结构：标题/前3秒钩子/分镜脚本（每个镜头：画面+文案+时长）/BGM与节奏/结尾引导；300-800 字，可直接执行拍摄）",
  "style": "风格与平台适配（50 字）"
}}
【铁律】前 3 秒必须有钩子；分镜可执行（每镜有画面有台词有时长）；情绪有起伏；结尾有引导。

创作需求：{theme}
{extra}

【完整讨论记录】
{transcript}""",
    },
    "comic": {
        "label": "漫画",
        "cast": """你是「创作圆桌」的选角导演。根据需求，为这场漫画创作会量身定制 4 位专业角色——
（如：漫画编剧 / 分镜师 / 画师 / 挑剔的读者）。
严格输出 JSON：{{"roles": [{{"name": "2字名", "field": "专业领域", "persona": "人设40-60字", "icon": "emoji", "order": 1, "finalizer": false}}]}}
要求：4 位领域互补紧扣需求；一位是挑剔的读者（order 4）；一位是主理人（finalizer=true）。""",
        "task_first": "你率先发言：提出漫画的核心创意（题材/主角/冲突/风格），必须具体，60-100 字。",
        "task_mid": "基于前序发言补充：从你的专业领域给出可落地的具体方案（分镜/节奏/画风/对白），60-100 字。",
        "task_critic": "你担任挑剔的读者：毒舌挑刺（故事老套/节奏失衡/画风混乱/对白注水），每个被批评的点都要给一个反方向替代，60-100 字。",
        "task_reply": "回应挑剔者的批评：必须实质性改进至少一个环节（改冲突/调分镜/换画风），最多辩护 1 点且要有理由，50-90 字。",
        "task_fix": "根据讨论修正你的方案：必须用至少一个全新的创意替换被批评的部分，禁止换说法，50-90 字。",
        "final": """你是{name}（{field}），担任主理人。产出定稿前先自查（被批评元素严禁回归），再产出高质量定稿。
严格输出 JSON（不要任何多余文字）：
{{
  "title": "漫画标题",
  "content": "漫画方案定稿（结构：故事梗概/主角设定/分镜脚本（每格：画面+对白+镜头）/画风与配色/节奏设计；300-800 字，可直接创作）",
  "style": "画风说明（50 字）"
}}
【铁律】故事有明确冲突与转折；分镜每格有画面有对白；对白精炼不注水；画风统一。

创作需求：{theme}
{extra}

【完整讨论记录】
{transcript}""",
    },
}

VALID_DOMAINS = tuple(_DOMAINS.keys())


def domain_label(domain: str) -> str:
    return _DOMAINS.get(domain, {}).get("label", domain)


# ===== 讨论流水线 =====

_PEOPLE_FIRST = "【第一信条·人民性】你从人民中来，为人民而写：站在普通人一边，写普通人的真实生活、劳动、尊严与悲欢；不居高临下地歌颂，用人民的语言，禁止鸡汤与宣传腔。"


def _speaker_prompt(theme: str, extra: str, rounds: list[dict[str, str]], task: str) -> str:
    history = "\n".join(f"{r['speaker']}：{r['content']}" for r in rounds) or "（你是第一位发言者）"
    return (
        f"{_PEOPLE_FIRST}\n"
        f"创作需求：{theme}\n"
        f"{extra}"
        f"\n\n【前序发言】\n{history}\n\n"
        f"【本轮任务】{task}"
    )


def _transcript_block(rounds: list[dict[str, str]], limit: int = 2500) -> str:
    parts: list[str] = []
    total = 0
    for r in reversed(rounds):
        s = f"{r['speaker']}：{r['content']}"
        if parts and total + len(s) > limit:
            break
        parts.append(s)
        total += len(s)
    return "\n".join(reversed(parts)) or "（无讨论记录）"


from app.services.text_utils import result_text as _result_text


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = cleaned.removeprefix("```json").removeprefix("```")
    cleaned = cleaned.removesuffix("```").strip()
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


from app.services.text_utils import sse_event as _sse_event


# 限流：每用户每分钟 4 场通用圆桌
_RATE = 4
_WINDOW = 60.0
_hits: dict[str, list[float]] = {}


def rate_allowed(user_id: str) -> bool:
    now = time.monotonic()
    cur = [t for t in _hits.get(user_id, []) if now - t < _WINDOW]
    if len(cur) >= _RATE:
        _hits[user_id] = cur
        return False
    cur.append(now)
    _hits[user_id] = cur
    return True


async def _gen_cast(db: AsyncSession, domain: str, theme: str, extra: str) -> list[dict[str, Any]]:
    """按领域+需求生成定制阵容（失败用通用兜底）。"""
    tpl = _DOMAINS[domain]
    prompt = tpl["cast"].format(theme=theme)
    resolved = await resolve_text_provider(db, "")
    fallback = [
        {"name": "策划", "field": "创意方向", "persona": "重创意落地", "icon": "💡", "order": 1, "finalizer": False},
        {"name": "执行", "field": "方案落地", "persona": "务实可执行", "icon": "🛠️", "order": 2, "finalizer": False},
        {"name": "主理", "field": "统筹定稿", "persona": "综合把关", "icon": "🎯", "order": 3, "finalizer": True},
        {"name": "评审", "field": "挑剔读者", "persona": "毒舌挑剔", "icon": "😈", "order": 4, "finalizer": False},
    ]
    try:
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, temperature=0.9
        )
        data = _extract_json(_result_text(result))
        roles = data.get("roles") or []
        if not isinstance(roles, list) or not roles:
            return fallback
        cast = []
        for idx, r in enumerate(roles[:4]):
            cast.append(
                {
                    "name": str(r.get("name") or f"专家{idx}")[:20],
                    "field": str(r.get("field") or "创作")[:40],
                    "persona": str(r.get("persona") or "")[:300],
                    "icon": str(r.get("icon") or "🎙️")[:4],
                    "order": int(r.get("order") or idx + 1),
                    "finalizer": bool(r.get("finalizer")),
                }
            )
        if len(cast) < 4:
            cast += fallback[len(cast) :]
        return cast[:4]
    except Exception:
        return fallback


# 各领域定稿正文最低字数（低于视为废稿）
_DOMAIN_MIN_LEN = {
    "copy": 300,
    "prompt": 200,
    "character_card": 200,
    "image": 100,
    "video": 200,
    "comic": 200,
}


def _validate_final(domain: str, final: dict[str, Any]) -> list[str]:
    """通用圆桌定稿结构自检：缺字段/正文过短/AI 腔给出警告列表。"""
    warnings: list[str] = []
    if not isinstance(final, dict):
        return ["定稿不是有效 JSON 对象"]
    title = str(final.get("title") or "").strip()
    content = str(final.get("content") or "").strip()
    if not title:
        warnings.append("缺少标题（title 为空）")
    if not content:
        warnings.append("缺少正文（content 为空）")
    else:
        min_len = _DOMAIN_MIN_LEN.get(domain, 200)
        if len(content) < min_len:
            warnings.append(f"正文偏短（{len(content)}字，{domain} 领域建议 ≥{min_len}字）")
        # AI 腔检测：套话/机械句式/宣传腔（中等及以上）计入必改项
        try:
            from app.services.ai_voice_checker import check_ai_voice

            issues = check_ai_voice(content)
            serious = [i for i in issues if i["level"] in ("high", "medium")]
            if len(serious) >= 2:
                samples = "、".join(i["sample"][:14] for i in serious[:3])
                warnings.append(
                    f"AI 腔过重（{len(serious)} 处：{samples}…）——"
                    "套话/机械句式/宣传腔会让读者出戏，替换成具体事实与动作"
                )
        except Exception:
            pass
    return warnings


def _severe_domain_checks(checks: list[str]) -> bool:
    """缺标题/缺正文/正文过短视为严重，值得自动重写一轮。"""
    return any("缺少" in c or "偏短" in c or "不是有效" in c for c in checks)


async def stream_roundtable(
    db: AsyncSession,
    *,
    user_id: str,
    domain: str,
    theme: str,
    extra: str = "",
    quick: bool = False,
    use_web: bool = False,
) -> Any:
    """通用圆桌 SSE 生成器（yield SSE 文本行）。限流超限先 yield error 事件。"""
    if domain not in _DOMAINS:
        yield _sse_event({"type": "error", "error": f"未知创作领域：{domain}"})
        yield "data: [DONE]\n\n"
        return
    if not rate_allowed(user_id):
        yield _sse_event({"type": "error", "error": "圆桌开得太频繁了，请等一分钟再试（每用户每分钟 4 场）"})
        yield "data: [DONE]\n\n"
        return
    tpl = _DOMAINS[domain]
    # 创作素材：知识库（已读懂）优先；命中不足且开启联网时，搜索兜底新鲜题材
    materials = ""
    material_titles: list[str] = []
    try:
        from app.services.knowledge_materials import retrieve_creation_materials

        materials, material_titles, web_materials, web_titles = (
            await retrieve_creation_materials(
                db, user_id, theme, limit=3, use_web=use_web
            )
        )
        material_titles = material_titles + web_titles
    except Exception:
        materials = ""
    from app.services.knowledge_materials import format_material_block

    kb_block = format_material_block(materials, web_materials)
    yield _sse_event(
        {"type": "domain", "domain": domain, "label": tpl["label"],
         "materials": material_titles}
    )
    yield _sse_event({"type": "cast_start"})
    cast = await _gen_cast(db, domain, theme, extra)
    ordered = sorted(cast, key=lambda r: int(r.get("order") or 99))
    yield _sse_event({"type": "cast", "cast": cast})

    # 议程：1 率先 → 2/3 补充 → 4 挑刺 → 2 回应 → 1 修正（quick 跳过回应/修正）
    agenda: list[dict[str, Any]] = []
    for i, r in enumerate(ordered):
        if i == 0:
            task = tpl["task_first"]
        elif i >= 3:
            task = tpl["task_critic"]
        else:
            task = tpl["task_mid"]
        agenda.append({"role": r, "task": task})
    if len(ordered) >= 3 and not quick:
        agenda.append({"role": ordered[1], "task": tpl["task_reply"]})
        agenda.append({"role": ordered[0], "task": tpl["task_fix"]})

    rounds: list[dict[str, str]] = []
    for idx, item in enumerate(agenda, start=1):
        role = item["role"]
        speaker = str(role.get("name") or f"专家{idx}")
        yield _sse_event({"type": "round_start", "speaker": speaker, "round_no": idx})
        persona = f"你是{role.get('name')}（{role.get('field')}）：{role.get('persona')}"
        prompt = _speaker_prompt(theme, extra + kb_block, rounds, str(item["task"]))
        resolved = await resolve_text_provider(db, "")
        try:
            result = await resolved.provider.generate(  # type: ignore[attr-defined]
                prompt, resolved.model, system=persona, temperature=0.9
            )
            text = _result_text(result).strip()
        except Exception as exc:
            text = f"（发言中断：{str(exc)[:80]}）"
        rounds.append({"speaker": speaker, "content": text})
        yield _sse_event({"type": "round", "speaker": speaker, "content": text})

    # 定稿：主理人主编把关（人民性信条前置）
    finalizer = next((r for r in ordered if r.get("finalizer")), ordered[0] if ordered else None)
    yield _sse_event({"type": "final_start"})
    final_prompt = f"{_PEOPLE_FIRST}\n\n" + tpl["final"].format(
        name=str((finalizer or {}).get("name") or "主理人"),
        field=str((finalizer or {}).get("field") or "创作"),
        theme=theme,
        extra=extra + kb_block,
        transcript=_transcript_block(rounds),
    )
    resolved = await resolve_text_provider(db, "")
    try:
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            final_prompt, resolved.model, temperature=0.7
        )
        final = _extract_json(_result_text(result))
    except Exception as exc:
        final = {"error": f"定稿失败：{str(exc)[:80]}"}
    # 结构自检：缺字段/正文过短即警告；严重问题自动重写一轮（与音乐圆桌一致）
    checks: list[str] = []
    rewrote = False
    if not final.get("error"):
        checks = _validate_final(domain, final)
        if _severe_domain_checks(checks):
            rewrote = True
            final_prompt += (
                "\n\n【上一轮自检警告】（本次为修正轮：必须逐条修正下列问题后再输出定稿，"
                "修正后的作品不得再出现同类问题）\n"
                + "\n".join(f"- {w}" for w in checks)
            )
            try:
                result = await resolved.provider.generate(  # type: ignore[attr-defined]
                    final_prompt, resolved.model, temperature=0.7
                )
                final = _extract_json(_result_text(result))
            except Exception as exc:
                final = {"error": f"定稿失败：{str(exc)[:80]}"}
            checks = [] if final.get("error") else _validate_final(domain, final)
    yield _sse_event(
        {
            "type": "final",
            "final": final,
            "rounds": rounds,
            "cast": cast,
            "domain": domain,
            "checks": checks,
            "rewrote": rewrote,
        }
    )
    yield "data: [DONE]\n\n"
