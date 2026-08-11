"""通用创作圆桌引擎：领域模板 + 限流 + prompt 构造。"""

from __future__ import annotations

from app.services import roundtable_service


def test_domains_available() -> None:
    """六个内容创作领域齐备，每个都有完整模板。"""
    keys = (
        "label",
        "cast",
        "task_first",
        "task_mid",
        "task_critic",
        "task_reply",
        "task_fix",
        "final",
    )
    for d in ("copy", "prompt", "character_card", "image", "video", "comic"):
        tpl = roundtable_service._DOMAINS[d]
        for key in keys:
            assert tpl[key], f"{d}.{key} 缺失"


def test_rate_limit() -> None:
    """通用圆桌限流：每用户每分钟 4 场。"""
    roundtable_service._hits.clear()
    uid = "rt-rate-test"
    for _ in range(4):
        assert roundtable_service.rate_allowed(uid) is True
    assert roundtable_service.rate_allowed(uid) is False
    roundtable_service._hits.clear()


def test_speaker_prompt_carries_history() -> None:
    """发言者 prompt 携带主题 + 前序发言。"""
    prompt = roundtable_service._speaker_prompt(
        "写一篇告别推文",
        "受众：老顾客",
        [{"speaker": "策划", "content": "用老剪刀开场"}],
        "补充你的方案",
    )
    assert "写一篇告别推文" in prompt
    assert "老剪刀开场" in prompt
    assert "补充你的方案" in prompt


def test_transcript_truncate() -> None:
    """定稿记录截断保护。"""
    rounds = [{"speaker": "甲", "content": "x" * 300}] * 10
    block = roundtable_service._transcript_block(rounds, limit=500)
    assert len(block) <= 600


def test_extract_json_tolerant() -> None:
    """容错解析：markdown 包裹 / 前后杂文本 / 非法输入。"""
    assert roundtable_service._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    text = '前缀 {"a": 1} 后缀'
    assert roundtable_service._extract_json(text) == {"a": 1}
    assert "error" in roundtable_service._extract_json("不是 JSON")
