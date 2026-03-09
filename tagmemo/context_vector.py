"""context_vector.py — 上下文向量映射管理，替代 ContextVectorManager.js (256 行)。

功能：
1. 维护当前会话消息的向量映射
2. 模糊匹配处理微小编辑（Dice 系数 bigram）
3. 语义分段 (TagMemo V4)
4. 计算语义宽度
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Callable, Awaitable

import numpy as np

from .text_sanitizer import TextSanitizer


class ContextVectorManager:
    """上下文向量管理器，1:1 对应原 JS ContextVectorManager。"""

    def __init__(
        self,
        embed_fn: Callable[[str], Awaitable[list[float] | None]] | None = None,
        get_cached_embedding: Callable[[str], list[float] | None] | None = None,
    ) -> None:
        self.embed_fn = embed_fn or (lambda _: asyncio.coroutine(lambda: None)())  # type: ignore
        self.get_cached_embedding = get_cached_embedding or (lambda _: None)

        self.vector_map: dict[str, dict] = {}  # hash → {vector, role, original_text, timestamp}
        self.history_assistant_vectors: list[list[float]] = []
        self.history_user_vectors: list[list[float]] = []

        self.fuzzy_threshold = 0.85
        self.decay_rate = 0.75
        self.max_context_window = 10

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        import re
        cleaned = TextSanitizer.sanitize(text)
        return re.sub(r"\s+", " ", cleaned.lower()).strip()

    @staticmethod
    def _generate_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _calculate_similarity(str1: str, str2: str) -> float:
        """Dice 系数 bigram 相似度。"""
        if str1 == str2:
            return 1.0
        if len(str1) < 2 or len(str2) < 2:
            return 0.0
        b1 = {str1[i:i + 2] for i in range(len(str1) - 1)}
        b2 = {str2[i:i + 2] for i in range(len(str2) - 1)}
        intersect = len(b1 & b2)
        return (2.0 * intersect) / (len(b1) + len(b2))

    def _find_fuzzy_match(self, normalized_text: str) -> list[float] | None:
        for entry in self.vector_map.values():
            sim = self._calculate_similarity(normalized_text, self._normalize(entry["original_text"]))
            if sim >= self.fuzzy_threshold:
                return entry["vector"]
        return None

    # ------------------------------------------------------------------
    # 核心：更新上下文
    # ------------------------------------------------------------------

    async def update_context(self, messages: list[dict], *, allow_api: bool = False) -> None:
        if not isinstance(messages, list):
            return

        new_assistant: list[dict] = []
        new_user: list[dict] = []

        # findLastIndex
        last_user_idx = -1
        last_ai_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if last_user_idx < 0 and messages[i].get("role") == "user":
                last_user_idx = i
            if last_ai_idx < 0 and messages[i].get("role") == "assistant":
                last_ai_idx = i
            if last_user_idx >= 0 and last_ai_idx >= 0:
                break

        async def _process(msg: dict, index: int) -> None:
            role = msg.get("role", "")
            if role == "system":
                return
            if index == last_user_idx or index == last_ai_idx:
                return

            content = msg.get("content", "")
            if isinstance(content, list):
                # multimodal: find text part
                content = next((p.get("text", "") for p in content if p.get("type") == "text"), "")
            if not content or len(content) < 2:
                return

            normalized = self._normalize(content)
            h = self._generate_hash(normalized)
            vector: list[float] | None = None

            if h in self.vector_map:
                vector = self.vector_map[h]["vector"]
            else:
                vector = self._find_fuzzy_match(normalized)
                if vector is None:
                    vector = self.get_cached_embedding(content)
                if vector is None and allow_api:
                    vector = await self.embed_fn(content)
                if vector is not None:
                    self.vector_map[h] = {
                        "vector": vector,
                        "role": role,
                        "original_text": content,
                        "timestamp": time.time(),
                    }

            if vector is not None:
                entry = {"vector": vector, "index": index, "role": role}
                if role == "assistant":
                    new_assistant.append(entry)
                elif role == "user":
                    new_user.append(entry)

        await asyncio.gather(*[_process(m, i) for i, m in enumerate(messages)])

        self.history_assistant_vectors = [e["vector"] for e in sorted(new_assistant, key=lambda x: x["index"])]
        self.history_user_vectors = [e["vector"] for e in sorted(new_user, key=lambda x: x["index"])]

    # ------------------------------------------------------------------
    # 逻辑深度
    # ------------------------------------------------------------------

    @staticmethod
    def compute_logic_depth(vector: list[float] | np.ndarray | None, top_k: int = 64) -> float:
        if vector is None:
            return 0.0
        v = np.asarray(vector, dtype=np.float32)
        dim = v.size
        if dim == 0:
            return 0.0

        energies = np.square(v, dtype=np.float32)
        total_energy = float(np.sum(energies))
        if total_energy < 1e-9:
            return 0.0

        actual_top_k = min(top_k, dim)
        if actual_top_k <= 0:
            return 0.0

        sorted_energies = np.sort(energies)[::-1]
        top_k_energy = float(np.sum(sorted_energies[:actual_top_k]))
        concentration = top_k_energy / total_energy
        expected_uniform = actual_top_k / dim

        if expected_uniform >= 1.0:
            return 1.0

        logic_depth = (concentration - expected_uniform) / (1 - expected_uniform)
        return max(0.0, min(1.0, logic_depth))

    # ------------------------------------------------------------------
    # 语义宽度
    # ------------------------------------------------------------------

    @staticmethod
    def compute_semantic_width(vector: list[float] | np.ndarray | None) -> float:
        if vector is None:
            return 0.0
        v = np.asarray(vector, dtype=np.float32)
        dim = v.size
        if dim == 0:
            return 0.0

        entropy = 0.0
        for value in v:
            probability = float(value * value)
            if probability > 1e-12:
                entropy -= probability * float(np.log(probability))

        max_entropy = float(np.log(dim))
        if max_entropy <= 0:
            return 0.0
        return entropy / max_entropy

    # ------------------------------------------------------------------
    # 语义分段
    # ------------------------------------------------------------------

    def segment_context(self, messages: list[dict], similarity_threshold: float = 0.70) -> list[dict]:
        sequence: list[dict] = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = next((p.get("text", "") for p in content if p.get("type") == "text"), "")
            if not content or len(content) < 2:
                continue
            normalized = self._normalize(content)
            h = self._generate_hash(normalized)
            entry = self.vector_map.get(h)
            if entry and entry.get("vector"):
                sequence.append({
                    "index": i,
                    "role": msg["role"],
                    "text": content,
                    "vector": entry["vector"],
                })

        if not sequence:
            return []

        segments: list[dict] = []
        cur_seg: dict = {
            "vectors": [sequence[0]["vector"]],
            "texts": [sequence[0]["text"]],
            "start_index": sequence[0]["index"],
            "end_index": sequence[0]["index"],
            "roles": [sequence[0]["role"]],
        }

        for i in range(1, len(sequence)):
            prev_v = np.asarray(sequence[i - 1]["vector"], dtype=np.float32)
            curr_v = np.asarray(sequence[i]["vector"], dtype=np.float32)
            sim = self._cosine_similarity(prev_v, curr_v)

            if sim >= similarity_threshold:
                cur_seg["vectors"].append(sequence[i]["vector"])
                cur_seg["texts"].append(sequence[i]["text"])
                cur_seg["end_index"] = sequence[i]["index"]
                cur_seg["roles"].append(sequence[i]["role"])
            else:
                segments.append(self._finalize_segment(cur_seg))
                cur_seg = {
                    "vectors": [sequence[i]["vector"]],
                    "texts": [sequence[i]["text"]],
                    "start_index": sequence[i]["index"],
                    "end_index": sequence[i]["index"],
                    "roles": [sequence[i]["role"]],
                }

        segments.append(self._finalize_segment(cur_seg))
        return segments

    @staticmethod
    def _finalize_segment(seg: dict) -> dict:
        vecs = [np.asarray(v, dtype=np.float32) for v in seg["vectors"]]
        avg = np.mean(vecs, axis=0).astype(np.float32)
        mag = np.linalg.norm(avg)
        if mag > 1e-9:
            avg /= mag
        return {
            "vector": avg.tolist(),
            "text": "\n".join(seg["texts"]),
            "roles": list(set(seg["roles"])),
            "range": [seg["start_index"], seg["end_index"]],
            "count": len(vecs),
        }

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        dot = float(np.dot(a, b))
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def cleanup(self, max_size: int = 1000) -> None:
        if len(self.vector_map) > max_size:
            self.vector_map.clear()
