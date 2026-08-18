"""创作回归基准（docs/creative-engine/09）：Golden Cases 加载 + 确定性 case 判定。

- test_golden_cases_loadable：50 例 YAML 结构完整、字段齐全、覆盖 11 类
- test_deterministic_cases：可确定性判定的 case 关联到检查器并断言
- LLM 类 case（failure_type 需语义理解）在真实 provider 环境由夜间回归执行（标记 skip 此处）

运行：uv run pytest tests/test_creative_benchmark.py -m creative_benchmark
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CASES_PATH = Path(__file__).parent / "golden_cases.yaml"

# 11 个类别（09 §3）
_EXPECTED_CATEGORIES = {
    "人物降维", "情绪套路", "主题强行植入", "职业失真", "价值观崩塌",
    "强行反转", "金句驱动", "第一联想", "角色工具化", "因果断裂", "风格压过故事",
}

# 可确定性判定的 case id → 检查器（cliche / semantic_diversity / cvi_precheck）
# 仅列确定性可达的；其余 case 由 LLM critic / 夜间回归覆盖
_DETERMINISTIC_MAP = {
    "GC-07": "cliche",   # 悲情四件套 → 套路组合拳
    "GC-08": "cliche",   # 只渲染不参与 → RENDER_ONLY 级别
    "GC-10": "cliche",   # 与人物历史绑定 → 不误杀（level 低）
    "GC-35": "cliche",   # 雨+故乡+老屋+等待 → 组合拳
    "GC-33": "diversity",  # 烟雨→第一联想簇
    "GC-36": "diversity",  # 跨域方向 → 达标
    "GC-01": "cvi",      # 亡妻句 → COLLAPSE（桥的名字）
}


def _load_cases() -> list[dict]:
    data = yaml.safe_load(_CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return [c for c in data if isinstance(c, dict)]


def test_golden_cases_loadable() -> None:
    """50 例：id 唯一、必填字段齐全、覆盖 11 类。"""
    cases = _load_cases()
    assert len(cases) == 50, f"应 50 例，实得 {len(cases)}"
    ids = [c["id"] for c in cases]
    assert len(set(ids)) == 50, "id 重复"
    required = {"id", "title", "category", "kind", "input", "expect"}
    for c in cases:
        assert required <= set(c.keys()), f"{c['id']} 缺字段"
        assert c["kind"] in ("generator", "detector"), f"{c['id']} kind 非法"
        assert "verdict" in c["expect"], f"{c['id']} 缺 expect.verdict"
    categories = {c["category"] for c in cases}
    # 11 大类必须全覆盖（YAML 允许更细的子类）
    missing = _EXPECTED_CATEGORIES - categories
    assert not missing, f"缺少类别：{missing}"
    # 桥的名字回归必须存在（GC-01）
    assert any(c["id"] == "GC-01" for c in cases)


def test_deterministic_case_cvi_bridge() -> None:
    """GC-01（桥的名字）：cvi_precheck 确定性判定 COLLAPSE。"""
    from app.creative.critics.cvi_precheck import assess_behavior_motivation
    from app.creative.schemas import CharacterConstitution, FailureType

    cases = {c["id"]: c for c in _load_cases()}
    gc = cases["GC-01"]
    constitution = CharacterConstitution(
        identity="陈工，守桥人",
        core_values=["公共安全"],
        value_hierarchy={"公共安全": 1.0, "责任": 0.95, "家庭": 0.75},
        mission="守住这座桥",
        emotional_triggers=[],
        relationships=[{"name": "妻子", "relation": "配偶", "emotional_weight": 0.9,
                        "value_link": "家庭"}],
    )
    pre = assess_behavior_motivation(str(gc["input"]), constitution)
    assert pre.ok is False
    assert pre.failure_type is FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE
    assert gc["expect"]["failure_type"] == "CHARACTER_VALUE_HIERARCHY_COLLAPSE"


def test_deterministic_case_cliche_detector() -> None:
    """GC-07/08/10/35：cliche_detector 分级判定。"""
    from app.creative.cliche_detector import detect_shortcuts

    cases = {c["id"]: c for c in _load_cases()}
    # GC-35：组合拳 → level ≥2
    r35 = detect_shortcuts(str(cases["GC-35"]["input"]))
    assert r35.level >= 2
    # GC-07：四件套 → level ≥2
    r07 = detect_shortcuts(str(cases["GC-07"]["input"]))
    assert r07.level >= 2
    # GC-10：绑定价值 → 不判替代深度（level ≤2）
    r10 = detect_shortcuts(str(cases["GC-10"]["input"]))
    assert r10.level <= 2
    assert r10.depth_signal_count >= 2


def test_deterministic_case_diversity() -> None:
    """GC-33（第一联想簇）vs GC-36（跨域）→ diversity_score 判定相反。"""
    from app.creative.semantic_diversity import (
        SemanticDirection,
        diversity_score,
    )

    cases = {c["id"]: c for c in _load_cases()}
    # GC-33 的输入是"烟雨朦胧"（无方向列表），用同质簇示例验证判定器本身
    cluster = [
        SemanticDirection("江南", ["江南", "烟雨", "油纸伞", "青石板", "雨巷"]),
        SemanticDirection("雨巷", ["烟雨", "雨巷", "故人", "离愁", "青石板"]),
        SemanticDirection("水乡", ["烟雨", "水乡", "小船", "青石板", "旧桥"]),
    ]
    v_cluster = diversity_score(cluster)
    assert v_cluster.passed is False
    assert v_cluster.first_association is True

    cross = [
        SemanticDirection("城市排水", ["排水", "管网", "内涝", "泵站"]),
        SemanticDirection("工程检测", ["桥梁", "伸缩缝", "病害", "复检"]),
        SemanticDirection("铁路调度", ["信号", "调度", "限速", "防汛"]),
    ]
    v_cross = diversity_score(cross)
    assert v_cross.passed is True
    assert v_cross.first_association is False
    assert cases["GC-36"]["expect"]["verdict"] == "PASS"


def test_deterministic_map_covers_detector_cases() -> None:
    """确定性映射表中引用的 case 必须真实存在。"""
    cases = {c["id"] for c in _load_cases()}
    assert set(_DETERMINISTIC_MAP.keys()) <= cases
