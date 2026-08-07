"""知识库最小版：分块 + 关键词打分检索（纯 Python，无向量库依赖）。

- 中文按单字切分、英文按词切分，保证无分词依赖也可用
- 打分取「问题 token 与块 token 的交集计数」，取分最高的前 k 块
"""

from __future__ import annotations

import re
from collections import Counter

CHUNK_SIZE = 700
CHUNK_OVERLAP = 100
MAX_CHUNKS_PER_DOC = 200  # 单文档最多参与检索的块数，防超大文档拖慢打分

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
_WS_RE = re.compile(r"\s+")


def tokenize(text: str) -> list[str]:
    """英文按词、中文按单字切分，统一小写。"""
    return _TOKEN_RE.findall(text.lower())


def chunk_text(content: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按固定窗口滑窗分块，保留少量重叠避免切断语义。"""
    if not content:
        return []
    text = _WS_RE.sub(" ", content).strip()
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    step = size - overlap
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks[:MAX_CHUNKS_PER_DOC]


def score_overlap(query_tokens: Counter[str], chunk: str) -> int:
    """交集计数：问题中出现的 token 在块里有多少个（去重计数）。"""
    chunk_tokens = Counter(tokenize(chunk))
    return sum(min(query_tokens[t], chunk_tokens[t]) for t in query_tokens)


def retrieve(
    chunks: list[tuple[str, str, str]],
    query: str,
    top_k: int = 3,
    min_score: int = 1,
) -> list[tuple[str, str, str, int]]:
    """从 [(doc_id, title, text), ...] 中检索，返回 [(doc_id, title, text, score), ...] 降序。"""
    q_tokens = Counter(tokenize(query))
    if not q_tokens:
        return []
    scored = [
        (doc_id, title, text, score_overlap(q_tokens, text))
        for doc_id, title, text in chunks
    ]
    hits = sorted((s for s in scored if s[3] >= min_score), key=lambda s: -s[3])
    return hits[:top_k]
