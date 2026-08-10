"""公共文本/JSON 工具：收敛全站重复的 result 提取 / JSON 解析 / SSE 格式化。

此前 _result_text（5 份）、_extract_json（4 份）、_load_json（4 份）、
_sse_event（3 份）在各服务里逐字复制——统一收口到本模块，行为保持不变。
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------- Provider 结果文本提取 ----------


def result_text(result: Any) -> str:
    """从 Provider 返回结果提取纯文本（dict 的 text/content 优先，其次 .content）。"""
    if isinstance(result, dict):
        return str(result.get("text") or result.get("content") or "")
    if hasattr(result, "content"):
        return str(result.content)
    return str(result)


# ---------- JSON 提取（容忍 markdown 代码块与前后噪声） ----------


def extract_json(raw: str) -> dict[str, Any]:
    """从模型输出提取 JSON 对象：剥代码块围栏，取首个 {…} 区间。

    提取失败抛 ValueError（调用方自行降级）。
    """
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def load_json(raw: str | None, default: Any = None) -> Any:
    """宽容解析 JSON 字符串；失败返回 default（不抛异常）。"""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


# ---------- SSE 事件 ----------


def sse_event(ev: dict[str, Any]) -> str:
    """SSE 事件行：data: {json}\n\n（ensure_ascii=False 保留中文）。"""
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
