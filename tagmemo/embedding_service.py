"""embedding_service.py — 统一 Embedding 服务，替代 EmbeddingService.js (162 行)。

提供文本向量化、FIFO 缓存、多块平均、重试。
依赖 text_chunker（原版 EmbeddingService.js 导入 TextChunker.chunkText()）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import httpx

from .text_chunker import chunk_text

logger = logging.getLogger(__name__)


class EmbeddingService:
    """统一 Embedding 服务，1:1 对应原 JS EmbeddingService。"""

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self.api_key: str = cfg.get("api_key") or os.environ.get("API_Key", "")
        self.api_url: str = cfg.get("api_url") or os.environ.get("API_URL", "")
        self.model: str = (
            cfg.get("model")
            or os.environ.get("WhitelistEmbeddingModel", "text-embedding-3-small")
        )

        # FIFO 缓存 (text_hash → {vector, timestamp})
        # 与原版 Map + FIFO 淘汰一致，不使用 LRU
        self._cache: dict[str, dict] = {}
        self._cache_max_size: int = cfg.get("cache_max_size", 500)
        self._cache_ttl: float = cfg.get("cache_ttl", 7200.0)  # 2h (秒)
        self.cache_hits: int = 0
        self.cache_misses: int = 0

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float] | None:
        """获取单个文本的 Embedding（带缓存）。"""
        if not text:
            return None

        cache_key = hashlib.sha256(text.strip().encode('utf-8', errors='replace')).hexdigest()

        # 缓存命中
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached["timestamp"] <= self._cache_ttl):
            self.cache_hits += 1
            return cached["vector"]
        if cached:
            del self._cache[cache_key]  # 过期

        self.cache_misses += 1

        vector = await self._call_embedding_api(text)
        if vector is not None:
            self._cache_vector(cache_key, vector)
        return vector

    def get_from_cache_only(self, text: str) -> list[float] | None:
        """仅从缓存获取（不触发 API）。"""
        if not text:
            return None
        cache_key = hashlib.sha256(text.strip().encode('utf-8', errors='replace')).hexdigest()
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached["timestamp"] <= self._cache_ttl):
            return cached["vector"]
        return None

    def cleanup_cache(self) -> None:
        """清理过期缓存条目。"""
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v["timestamp"] > self._cache_ttl]
        for k in expired:
            del self._cache[k]

    def get_stats(self) -> dict:
        total = self.cache_hits + self.cache_misses
        return {
            "cache_size": len(self._cache),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": (
                f"{self.cache_hits / total * 100:.1f}%" if total > 0 else "N/A"
            ),
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _call_embedding_api(self, text: str) -> list[float] | None:
        """调用 Embedding API（带分块 + 重试）。"""
        if not self.api_key or not self.api_url or not self.model:
            logger.error("[EmbeddingService] API credentials not configured.")
            return None

        text_chunks = chunk_text(text)
        if not text_chunks:
            return None

        max_retries = 3
        retry_delay = 1.0

        url = self.api_url.rstrip('/')
        if not url.endswith('/embeddings'):
            url = f"{url}/v1/embeddings"
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, max_retries + 1):
            try:
                payload_json = json.dumps({"model": self.model, "input": text_chunks}, ensure_ascii=False)
                payload_json = payload_json.encode('utf-8', 'replace').decode('utf-8')
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url,
                        content=payload_json,
                        headers=headers,
                        timeout=60.0,
                    )

                if resp.status_code != 200:
                    status = resp.status_code
                    if status in (500, 503) and attempt < max_retries:
                        logger.warning(
                            "[EmbeddingService] API call failed (%d), retry %d/%d...",
                            status,
                            attempt,
                            max_retries,
                        )
                        await _async_sleep(retry_delay)
                        continue
                    logger.error("[EmbeddingService] Embedding failed: %d", status)
                    return None

                data = resp.json()
                embeddings = data.get("data")
                if not embeddings:
                    return None

                vectors = [e["embedding"] for e in embeddings if e.get("embedding")]
                if not vectors:
                    return None
                if len(vectors) == 1:
                    return vectors[0]

                # 多块向量取平均
                return self._average_vectors(vectors)

            except Exception as exc:
                if attempt < max_retries:
                    logger.warning(
                        "[EmbeddingService] API call failed, retry %d/%d: %s",
                        attempt,
                        max_retries,
                        exc,
                    )
                    await _async_sleep(retry_delay)
                    continue
                logger.error("[EmbeddingService] Embedding failed: %s", exc)
                return None

        return None

    @staticmethod
    def _average_vectors(vectors: list[list[float]]) -> list[float]:
        """多块向量取均值。"""
        dim = len(vectors[0])
        result = [0.0] * dim
        for vec in vectors:
            for i in range(dim):
                result[i] += vec[i]
        n = len(vectors)
        for i in range(dim):
            result[i] /= n
        return result

    def _cache_vector(self, key: str, vector: list[float]) -> None:
        """FIFO 缓存写入（与原版 Map + firstKey 淘汰一致）。"""
        if len(self._cache) >= self._cache_max_size:
            first_key = next(iter(self._cache))
            del self._cache[first_key]
        self._cache[key] = {"vector": vector, "timestamp": time.time()}


async def _async_sleep(seconds: float) -> None:
    """asyncio.sleep 的简单包装。"""
    import asyncio
    await asyncio.sleep(seconds)
