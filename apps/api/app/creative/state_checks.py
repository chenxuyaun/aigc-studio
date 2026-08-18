"""状态一致性确定性检查（05 §7 / 09 §4 单元测试 11/12/13）。

零 LLM：直接查 StoryState 数据结构，返回问题清单。
- check_timeline_consistency：timeline.events 章节自洽（非降序，插叙需显式标注）
- check_fact_conflicts：facts 去重/非空
- check_knowledge_leak：知识状态不得早于事件发生（谁不该知道却知道了）
- check_loop_leak：open_loops 超 N 章未回收（LOOP_LEAK）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.creative.schemas import StoryState


@dataclass
class StateCheckReport:
    ok: bool = True
    problems: list[str] = field(default_factory=list)

    def add(self, problem: str) -> None:
        self.problems.append(problem)
        self.ok = False

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": self.problems}


def check_timeline_consistency(state: StoryState) -> StateCheckReport:
    """timeline.events 按出现顺序 chapter 应非降序（正文按章推进）。

    插叙/倒叙允许回退，但需在 event 描述中显式含「回忆/倒叙/插叙」等标记；
    无标记的回退视为时间线矛盾。
    """
    r = StateCheckReport()
    prev_chapter = 0
    for i, ev in enumerate(state.timeline.events):
        if ev.chapter < prev_chapter and not any(
            m in ev.event for m in ("回忆", "倒叙", "插叙", "回放")
        ):
            r.add(
                f"时间线矛盾：events[{i}] 章节 {ev.chapter} 早于前序 {prev_chapter}"
                f"（无插叙标记）：{ev.event[:60]}"
            )
        prev_chapter = max(prev_chapter, ev.chapter)
    return r


def check_fact_conflicts(state: StoryState) -> StateCheckReport:
    """facts 基础一致性：非空、无重复、无自相矛盾（同时含肯定与「未」否定）。"""
    r = StateCheckReport()
    facts = state.world_state.facts
    if len(facts) != len(set(facts)):
        r.add(f"facts 存在重复：{len(facts) - len(set(facts))} 条")
    for i, f in enumerate(facts):
        if not f.strip():
            r.add(f"facts[{i}] 为空")
        # 自相矛盾启发式：同一事实文本同时出现「已」与「未」
        if "已" in f and ("未" in f or "没有" in f):
            r.add(f"facts[{i}] 疑似自相矛盾（同时含已/未）：{f[:60]}")
    return r


def check_knowledge_leak(state: StoryState) -> StateCheckReport:
    """知识泄漏：角色知道某事的章节早于该事件发生章节。

    timeline.events[].chapter = 事件发生章；knowledge_entry.since_chapter = 知道起始章。
    since < 事件章 且 事件与该 know 描述相关 → 泄漏嫌疑。
    保守匹配：事件文本出现在 know 文本中，或 know 文本出现在事件文本中。
    """
    r = StateCheckReport()
    for k in state.knowledge_state:
        for ev in state.timeline.events:
            if ev.chapter <= 0 or k.since_chapter <= 0:
                continue
            if k.since_chapter < ev.chapter and (
                k.knows in ev.event or ev.event in k.knows
            ):
                r.add(
                    f"知识泄漏：{k.character} 自第{k.since_chapter}章知道「{k.knows[:40]}」，"
                    f"但事件发生于第{ev.chapter}章"
                )
                break
    return r


def check_loop_leak(state: StoryState, *, max_unchanged_chapters: int = 10) -> StateCheckReport:
    """伏笔遗忘：open_loops 在最新章节之后超过 N 章未回收。"""
    r = StateCheckReport()
    latest = max((ev.chapter for ev in state.timeline.events), default=0)
    for loop in state.open_loops:
        if loop.planted_chapter > 0 and latest - loop.planted_chapter > max_unchanged_chapters:
            r.add(
                f"伏笔遗忘（LOOP_LEAK）：loop「{loop.desc[:40]}」"
                f"自第{loop.planted_chapter}章开放，已 {latest - loop.planted_chapter} 章未回收"
            )
    return r


def run_state_checks(
    state: StoryState, *, max_loop_gap: int = 10
) -> dict[str, StateCheckReport]:
    """全部确定性检查聚合（供 StateValidator / 章节收尾调用）。"""
    return {
        "timeline": check_timeline_consistency(state),
        "facts": check_fact_conflicts(state),
        "knowledge": check_knowledge_leak(state),
        "loops": check_loop_leak(state, max_unchanged_chapters=max_loop_gap),
    }


