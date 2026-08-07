"""Mock 媒体渲染：无需任何真实模型 Key，即可产出可保存、可预览的字节。

- 图片 / 视频封面：生成带提示词的 SVG。
- 语音：生成一小段静音 WAV（可播放）。
"""

from __future__ import annotations

import html
import struct

_PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]


def _pick_color(seed: str) -> str:
    return _PALETTE[sum(ord(c) for c in seed) % len(_PALETTE)]


def render_image_svg(
    prompt: str,
    width: int = 768,
    height: int = 768,
    label: str = "Mock Image",
    *,
    reference_hint: str = "",
    seed: str = "",
) -> bytes:
    color = _pick_color(seed or prompt or label)
    text = html.escape((prompt or "示例图片")[:60])
    ref = html.escape((reference_hint or "")[:36])
    ref_line = (
        f"<text x='50%' y='66%' fill='rgba(255,255,255,0.7)' font-size='14' "
        f"font-family='sans-serif' text-anchor='middle'>ref: {ref}</text>"
        if ref
        else ""
    )
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}'>"
        f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        f"<stop offset='0' stop-color='{color}'/><stop offset='1' stop-color='#111827'/>"
        f"</linearGradient></defs>"
        f"<rect width='{width}' height='{height}' fill='url(#g)'/>"
        f"<text x='50%' y='46%' fill='white' font-size='28' font-family='sans-serif' "
        f"text-anchor='middle'>{label}</text>"
        f"<text x='50%' y='56%' fill='rgba(255,255,255,0.82)' font-size='18' "
        f"font-family='sans-serif' text-anchor='middle'>{text}</text>"
        f"{ref_line}"
        f"</svg>"
    )
    return svg.encode("utf-8")


def render_video_poster(prompt: str) -> bytes:
    return render_image_svg(prompt, 1280, 720, label="Mock Video")


def render_silence_wav(seconds: float = 0.4, sample_rate: int = 8000) -> bytes:
    """生成一段静音 PCM WAV（可在浏览器 <audio> 播放）。"""
    n = int(seconds * sample_rate)
    data = b"\x00\x00" * n  # 16-bit 静音样本
    block_align = 2
    byte_rate = sample_rate * block_align
    header = b"RIFF"
    header += struct.pack("<I", 36 + len(data))
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, block_align, 16)
    header += b"data"
    header += struct.pack("<I", len(data))
    return header + data


def _to_int(value: object, default: int) -> int:
    """上游参数（object）安全转 int；不可转时回落默认值。"""
    return int(value) if isinstance(value, (int, float, str)) else default


def render_for(task_type: str, prompt: str, **params: object) -> tuple[bytes, str, str]:
    """按任务类型返回 (bytes, mime_type, 扩展名)。"""
    if task_type == "image":
        width = _to_int(params.get("width", 768), 768)
        height = _to_int(params.get("height", 768), 768)
        ref = str(
            params.get("reference_photo_id")
            or params.get("reference_asset_id")
            or ""
        )
        label = "Mock Image + Ref" if ref else "Mock Image"
        # seed 固定时颜色稳定（可复现）；无 seed 时用提示词定色（默认行为）
        seed = params.get("seed")
        seed_str = str(seed) if seed is not None else prompt
        return (
            render_image_svg(
                prompt, width, height, label=label, reference_hint=ref, seed=seed_str
            ),
            "image/svg+xml",
            "svg",
        )
    if task_type == "video":
        return render_video_poster(prompt), "image/svg+xml", "svg"
    if task_type == "audio":
        return render_silence_wav(), "audio/wav", "wav"
    raise ValueError(f"不支持的媒体任务类型: {task_type}")
