"""text_chunker.py — 智能文本切分器，替代 TextChunker.js (103 行)。

基于 tiktoken Token 计数的文本分块，保持句子完整性 + 重叠窗口。
"""

from __future__ import annotations

import os
import re

import tiktoken

# 编码器（与原版 cl100k_base 一致）
_encoding = tiktoken.get_encoding("cl100k_base")

# 从环境变量读取配置（与原版 config.env 一致）
_embedding_max_token = int(os.environ.get("WhitelistEmbeddingModelMaxToken", "8000"))
_safe_max_tokens = int(_embedding_max_token * 0.85)
_default_overlap_tokens = int(_safe_max_tokens * 0.1)


def chunk_text(
    text: str,
    max_tokens: int = _safe_max_tokens,
    overlap_tokens: int = _default_overlap_tokens,
) -> list[str]:
    """智能文本切分。

    Parameters
    ----------
    text : str
        需要切分的原始文本。
    max_tokens : int
        每个切片的最大 token 数。
    overlap_tokens : int
        切片间的重叠 token 数。

    Returns
    -------
    list[str]
        切分后的文本块数组。
    """
    if not text:
        return []

    # 按句子边界拆分（保留分隔符）
    # 注意：Python re 默认支持 Unicode，中文标点 。？！ 均为单个 codepoint，
    # lookbehind 断言要求固定长度（字符数而非字节数），此处每个字符均为 1，安全。
    sentences = re.split(r"(?<=[。？！.!?\n])", text)
    # 移除空串
    sentences = [s for s in sentences if s]

    chunks: list[str] = []
    current_chunk = ""
    current_tokens = 0

    for i, sentence in enumerate(sentences):
        sentence_tokens = len(_encoding.encode(sentence))

        # 单句超长 → 强制拆分
        if sentence_tokens > max_tokens:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""
                current_tokens = 0
            chunks.extend(_force_split_long_text(sentence, max_tokens, overlap_tokens))
            continue

        # 当前块加上新句子会溢出 → 推入 chunks，用重叠窗口启动新块
        if current_tokens + sentence_tokens > max_tokens:
            chunks.append(current_chunk.strip())

            # 从之前的句子中回溯，构建 overlap 前缀
            overlap_chunk = ""
            overlap_count = 0
            for j in range(i - 1, -1, -1):
                prev = sentences[j]
                prev_tokens = len(_encoding.encode(prev))
                if overlap_count + prev_tokens > overlap_tokens:
                    break
                overlap_chunk = prev + overlap_chunk
                overlap_count += prev_tokens

            current_chunk = overlap_chunk
            current_tokens = overlap_count

        current_chunk += sentence
        current_tokens += sentence_tokens

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _force_split_long_text(
    text: str, max_tokens: int, overlap_tokens: int
) -> list[str]:
    """当单句超过 max_tokens 时，按 token 位置强制拆分。"""
    chunks: list[str] = []
    tokens = _encoding.encode(text)
    start = 0

    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))

        if end < len(tokens):
            chunk_tokens = tokens[start:end]
            chunk_str = _encoding.decode(chunk_tokens)

            # 尝试在尾部找一个自然断点
            break_points = "\n。！？，；： \t"
            best_break = -1
            search_start = max(0, len(chunk_str) - 200)
            for idx in range(len(chunk_str) - 1, search_start - 1, -1):
                if chunk_str[idx] in break_points:
                    best_break = idx + 1
                    break

            if best_break > 0:
                chunk_str = chunk_str[:best_break]
                new_tokens = _encoding.encode(chunk_str)
                end = start + len(new_tokens)

            chunk_str = chunk_str.strip()
            if chunk_str:
                chunks.append(chunk_str)
        else:
            chunk_tokens = tokens[start:]
            chunk_str = _encoding.decode(chunk_tokens).strip()
            if chunk_str:
                chunks.append(chunk_str)

        start = max(start + 1, end - overlap_tokens)

    return chunks
