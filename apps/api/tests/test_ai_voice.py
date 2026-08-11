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
