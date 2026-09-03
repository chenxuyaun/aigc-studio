"""AI 腔检测：分级（套话/机械句式/连接词/宣传腔/空洞修饰）。"""

from __future__ import annotations

from app.services.ai_voice_checker import check_ai_voice


def test_detects_cliche_high_level():
    issues = check_ai_voice("众所周知，这家店的味道很好。")
    assert any(i["kind"] == "cliche" and i["level"] == "high" for i in issues)
    assert issues[0]["level"] == "high", "严重问题应排最前"


def test_detects_clickbait_high_level():
    issues = check_ai_voice("这部作品不容错过，震撼来袭！")
    assert any(i["kind"] == "clickbait" and i["level"] == "high" for i in issues)


def test_detects_pattern_and_connective_medium():
    issues = check_ai_voice("它不仅好看，而且实用。与此同时，价格也不贵。")
    kinds = {i["kind"] for i in issues}
    assert "pattern" in kinds
    assert "connective" in kinds
    assert all(i["level"] == "medium" for i in issues if i["kind"] in ("pattern", "connective"))


def test_detects_filler_info_level():
    issues = check_ai_voice("这个方案日益完善，不断优化。")
    fillers = [i for i in issues if i["kind"] == "filler"]
    assert fillers
    assert all(i["level"] == "info" for i in fillers)


def test_sorted_by_severity():
    issues = check_ai_voice("众所周知，我们不仅要有决心，还要有行动。")
    levels = [i["level"] for i in issues]
    assert levels == sorted(
        levels, key=lambda x: {"high": 2, "medium": 1, "info": 0}[x], reverse=True
    )


def test_clean_text_no_hits():
    assert check_ai_voice("老陈把半袋钱塞进麻袋口，像潮声在胸口滚。") == []
    assert check_ai_voice("") == []


# ── Personal Voice Engine：对照用户文风档案检测 ──


def test_voice_avoid_hits_personal_avoid():
    dna = {"avoid": ["赋能", "抓手"]}
    issues = check_ai_voice("这个平台为用户赋能，提供了清晰的发展抓手。", voice_dna=dna)
    avoid_hits = [i for i in issues if i["kind"] == "voice_avoid"]
    assert len(avoid_hits) == 2
    assert all(i["level"] == "high" for i in avoid_hits)
    assert "赋能" in avoid_hits[0]["suggestion"] or "赋能" in avoid_hits[1]["suggestion"]


def test_voice_avoid_short_words_ignored():
    # 1 字忌讳词不检测（防误报）
    issues = check_ai_voice("这事确实离谱。", voice_dna={"avoid": ["的"]})
    assert not any(i["kind"] == "voice_avoid" for i in issues)


def test_voice_rhythm_flags_long_sentences_when_prefer_short():
    text = "这个项目的核心目标在于通过精细化的流程再造与跨部门协同来全面提升整体运营效率并显著降低长期成本。"
    issues = check_ai_voice(text, voice_dna={"sentence_length": "short"})
    assert any(i["kind"] == "voice_rhythm" and i["level"] == "medium" for i in issues)


def test_voice_rhythm_absent_when_no_short_pref():
    text = "这个项目的核心目标在于通过精细化的流程再造与跨部门协同来全面提升整体运营效率并显著降低长期成本。"
    issues = check_ai_voice(text, voice_dna={"sentence_length": "long"})
    assert not any(i["kind"] == "voice_rhythm" for i in issues)


def test_voice_dna_none_preserves_legacy_behavior():
    # 不传 voice_dna 时与旧行为一致（无 voice_* 命中）
    issues = check_ai_voice("众所周知，这家店的味道很好。")
    assert not any(i["kind"].startswith("voice_") for i in issues)
    assert any(i["kind"] == "cliche" for i in issues)
