"""提示词生成器 / 优化器的 Mock 逻辑。

无需真实模型 Key：根据结构化输入用启发式模板合成提示词与诊断，
使 Mock 模式下也能完整体验业务流程。接入真实 LLM 后替换此实现即可。
"""

from __future__ import annotations

from app.schemas.prompt_tools import (
    DiagnosisItem,
    OptimizeResult,
    PromptGenerateRequest,
    PromptOptimizeRequest,
    StructuredPrompt,
)

_MODEL_LABEL = {
    "llm": "通用大语言模型",
    "image": "图片生成模型",
    "video": "视频生成模型",
    "speech": "语音生成模型",
    "code": "编程模型",
}


def generate_structured_prompt(req: PromptGenerateRequest) -> StructuredPrompt:
    scene = req.scene or req.idea or "内容创作"
    audience = req.audience or "广泛受众"
    lang = req.output_language or "中文"
    style = req.style or "清晰专业"
    model_label = _MODEL_LABEL.get(req.target_model, "通用大语言模型")

    role = f"你是一位资深的{scene}专家，擅长面向{audience}产出高质量成果。"
    background = f"任务场景：{scene}；目标模型：{model_label}；目标受众：{audience}。"
    goal = req.goal or req.idea or f"围绕「{scene}」产出高质量结果。"
    input_desc = "用户提供的主题、素材与关键要求。"

    steps = [
        "理解并拆解用户需求，识别关键信息与约束",
        "确定核心表达重点与整体结构",
        f"以{style}的风格" + (f"、{req.tone}的语气" if req.tone else "") + "组织内容",
        "对照输出格式与约束逐条自检，必要时修正",
    ]
    output_format = req.output_format or ("结构清晰的分段文本，重点突出，便于直接使用")
    length_note = f"篇幅：{req.length}。" if req.length else ""
    constraints = req.constraints or "内容真实、聚焦主题、无歧义；避免冗余与空话。"
    constraints = (length_note + constraints).strip()
    quality_check = "完成后检查：目标是否达成、格式是否符合、是否存在歧义或遗漏。"

    steps_text = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    full_prompt = (
        f"# 角色\n{role}\n\n"
        f"# 背景\n{background}\n\n"
        f"# 目标\n{goal}\n\n"
        f"# 输入\n{input_desc}\n\n"
        f"# 执行步骤\n{steps_text}\n\n"
        f"# 输出格式\n{output_format}\n\n"
        f"# 约束条件\n{constraints}\n\n"
        f"# 质量检查\n{quality_check}\n\n"
        f"请用{lang}输出。"
    )

    return StructuredPrompt(
        role=role,
        background=background,
        goal=goal,
        input=input_desc,
        steps=steps,
        output_format=output_format,
        constraints=constraints,
        quality_check=quality_check,
        full_prompt=full_prompt,
    )


def _level(score: int) -> str:
    if score >= 80:
        return "优秀"
    if score >= 60:
        return "一般"
    return "待改进"


def _clamp(n: int) -> int:
    return max(5, min(98, n))


def optimize_prompt(req: PromptOptimizeRequest) -> OptimizeResult:
    p = req.prompt.strip()
    n = len(p)

    has_role = any(k in p for k in ["你是", "作为", "角色", "assistant", "expert", "专家"])
    has_goal = any(k in p for k in ["目标", "请", "生成", "写", "设计", "帮我", "创建"])
    has_format = any(k in p for k in ["格式", "输出", "JSON", "列表", "分段", "表格", "字数"])
    has_constraint = any(k in p for k in ["约束", "不要", "禁止", "限制", "必须", "避免"])
    has_context = n > 60 or any(k in p for k in ["背景", "场景", "受众", "面向"])

    clarity = _clamp(50 + (25 if has_goal else 0) + (15 if n > 30 else 0))
    context = _clamp(45 + (30 if has_context else 0) + (10 if has_role else 0))
    fmt = _clamp(88 if has_format else 42)
    fit = _clamp(60 + (20 if has_role else 0))
    constraint = _clamp(85 if has_constraint else 40)
    redundancy = _clamp(90 if n < 400 else 60)  # 越简洁越好
    safety = _clamp(92)

    diagnosis = [
        DiagnosisItem(
            dimension="目标清晰度",
            score=clarity,
            level=_level(clarity),
            note="目标较明确" if clarity >= 70 else "建议用一句话点明要产出什么",
        ),
        DiagnosisItem(
            dimension="上下文完整度",
            score=context,
            level=_level(context),
            note="上下文尚可" if context >= 70 else "缺少背景/受众等信息",
        ),
        DiagnosisItem(
            dimension="输出格式",
            score=fmt,
            level=_level(fmt),
            note="已声明输出格式" if has_format else "未指定输出格式，模型可能自由发挥",
        ),
        DiagnosisItem(
            dimension="模型适配",
            score=fit,
            level=_level(fit),
            note="基本适配目标模型" if fit >= 70 else "建议明确角色与任务类型",
        ),
        DiagnosisItem(
            dimension="约束充分度",
            score=constraint,
            level=_level(constraint),
            note="已包含约束" if has_constraint else "缺少明确的限制与禁止项",
        ),
        DiagnosisItem(
            dimension="冗余程度",
            score=redundancy,
            level=_level(redundancy),
            note="表达简洁" if redundancy >= 70 else "偏长，建议精简重复表述",
        ),
        DiagnosisItem(
            dimension="安全风险", score=safety, level=_level(safety), note="未见明显风险"
        ),
    ]
    score_before = _clamp(sum(d.score for d in diagnosis) // len(diagnosis))

    suggestions: list[str] = []
    if not has_role:
        suggestions.append("补充明确的角色设定（“你是一位……”），让模型进入专业视角。")
    if not has_format:
        suggestions.append("显式声明输出格式（分段 / 列表 / JSON / 字数），减少不确定性。")
    if not has_constraint:
        suggestions.append("加入约束与禁止项，界定边界，避免跑题。")
    if not has_context:
        suggestions.append("补充背景、场景与目标受众，提升上下文完整度。")
    if n > 400:
        suggestions.append("精简冗余表述，突出关键信息。")
    if not suggestions:
        suggestions.append("提示词已较完整，可按下方标准版进一步结构化。")

    goal_line = p if has_goal else f"请完成以下任务：{p}"
    concise = f"{goal_line}\n输出：结构清晰、聚焦重点。"
    standard = (
        "# 角色\n你是该领域的资深专家。\n\n"
        f"# 任务\n{goal_line}\n\n"
        "# 输出格式\n分段清晰，重点前置。\n\n"
        "# 约束\n真实、聚焦、无歧义，避免冗余。"
    )
    professional = (
        "# 角色\n你是该领域的资深专家，具备严谨的方法论。\n\n"
        f"# 背景\n（补充场景与受众）\n\n# 任务\n{goal_line}\n\n"
        "# 执行步骤\n1. 拆解需求\n2. 组织核心信息\n3. 按格式产出并自检\n\n"
        "# 输出格式\n结构化分段，必要处用列表。\n\n"
        "# 约束\n真实、聚焦、无歧义；避免冗余与空话。\n\n"
        "# 质量检查\n核对目标达成、格式符合、无遗漏。"
    )

    score_after = _clamp(score_before + 25)
    return OptimizeResult(
        score_before=score_before,
        score_after=score_after,
        diagnosis=diagnosis,
        suggestions=suggestions,
        concise=concise,
        standard=standard,
        professional=professional,
    )
