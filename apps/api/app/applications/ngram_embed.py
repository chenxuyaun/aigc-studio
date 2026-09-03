"""共享 n-gram 哈希伪 embedding（中文 1/2-gram + 英文单词 → 512 维 L2 归一化向量）。

单一实现来源：openai_gateway 的 /embeddings 端点与记忆 top-k 检索共用。
纯内存计算，无外部依赖；换真实向量服务时仅需替换此函数。
"""

from __future__ import annotations

import hashlib
import math
import re

_LOCAL_EMBED_DIM = 512


def local_embed(text: str) -> list[float]:
    """字符级 1/2-gram 特征哈希向量（中文不分词，词典外词也能命中）。

    中文连续字符取 1-gram + 2-gram；英文按单词。L2 归一化后余弦相似度
    即特征重合度。原实现位于 api/v1/openai_gateway._local_embed，抽此处共享。
    """
    vec = [0.0] * _LOCAL_EMBED_DIM
    s = text.lower()
    zh = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s)
    grams: list[str] = re.findall(r"[a-z0-9]+", s)
    for i, ch in enumerate(zh):
        if "\u4e00" <= ch <= "\u9fff":
            grams.append(ch)
            if i + 1 < len(zh) and "\u4e00" <= zh[i + 1] <= "\u9fff":
                grams.append(zh[i : i + 2])
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16) % _LOCAL_EMBED_DIM
        vec[h] += 2.0 if len(g) >= 2 else 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """两个已 L2 归一化向量的余弦相似度。"""
    return sum(x * y for x, y in zip(a, b))
