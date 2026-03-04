"""reranker.py — 可选的 Rerank 重排序中间件，替代 Reranker.js (263 行)。

功能：
- 断路器 (Circuit Breaker): 1 分钟内 5 次失败 → 熔断跳过
- Token 预算: 查询截断 + 文档批次分割
- 批次处理: 按 maxTokens 限制自动分批
- 超时重试 + 降级: 失败批次保留原序，>50% 失败率提前终止
- 全局 rerank_score 重排序
"""

from __future__ import annotations

import logging
import os
import re
import time

import httpx

logger = logging.getLogger(__name__)


class Reranker:
    """Rerank 重排序中间件，1:1 对应原 JS Reranker。"""

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self.url = cfg.get("url", os.environ.get("RERANK_API_URL", ""))
        self.api_key = cfg.get("api_key", os.environ.get("RERANK_API_KEY", ""))
        self.model = cfg.get("model", os.environ.get("RERANK_MODEL", "jina-reranker-v2-base-multilingual"))
        self.max_tokens = cfg.get("max_tokens", int(os.environ.get("RERANK_MAX_TOKENS", "8000")))
        self.multiplier = cfg.get("multiplier", float(os.environ.get("RERANK_K_MULTIPLIER", "3")))
        self.timeout = cfg.get("timeout", int(os.environ.get("RERANK_TIMEOUT_MS", "30000"))) / 1000.0

        # 断路器
        self.circuit_breaker_threshold = cfg.get("circuit_breaker_threshold", 5)
        self.circuit_breaker_window = cfg.get("circuit_breaker_window_ms", 60000) / 1000.0
        self.circuit_breaker_cooldown = cfg.get("circuit_breaker_cooldown_ms", 300000) / 1000.0
        self._failure_records: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.api_key and self.model)

    def get_search_k(self, original_k: int) -> int:
        return max(1, round(original_k * self.multiplier))

    # ------------------------------------------------------------------
    # 核心
    # ------------------------------------------------------------------

    async def rerank(self, query: str, documents: list[dict], top_k: int) -> list[dict]:
        """对文档列表进行 Rerank 重排序。失败时降级返回原序。"""
        if not self.enabled:
            logger.warning("[Reranker] Not configured, skipping")
            return documents[:top_k]

        if not documents:
            return []
        if len(documents) <= 1:
            return documents

        # 断路器检查
        if self._is_circuit_open():
            logger.warning("[Reranker] Circuit breaker OPEN — too many recent failures, skipping rerank")
            return documents[:top_k]

        # 查询截断
        max_query_tokens = int(self.max_tokens * 0.3)
        truncated_query = query
        query_tokens = self._estimate_tokens(query)

        if query_tokens > max_query_tokens:
            logger.warning("[Reranker] Query too long (%d tokens), truncating to %d", query_tokens, max_query_tokens)
            ratio = max_query_tokens / query_tokens
            target_len = int(len(query) * ratio * 0.9)
            truncated_query = query[:target_len] + "..."
            query_tokens = self._estimate_tokens(truncated_query)

        # 批次分割
        max_doc_tokens = self.max_tokens - query_tokens - 1000
        batches = self._split_into_batches(documents, max_doc_tokens)

        if not batches:
            logger.warning("[Reranker] No valid batches, returning original")
            return documents[:top_k]

        logger.info("[Reranker] Processing %d batch(es), query=%d tokens", len(batches), query_tokens)

        # 逐批次 Rerank API
        rerank_url = f"{self.url.rstrip('/')}/v1/rerank"
        all_reranked: list[dict] = []
        failed_batches = 0

        async with httpx.AsyncClient() as client:
            for i, batch in enumerate(batches):
                doc_texts = [d["text"] for d in batch]
                try:
                    body = {
                        "model": self.model,
                        "query": truncated_query,
                        "documents": doc_texts,
                        "top_n": len(doc_texts),
                    }
                    resp = await client.post(
                        rerank_url,
                        json=body,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        timeout=self.timeout,
                        follow_redirects=False,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("results")
                        if isinstance(results, list):
                            for r in results:
                                idx = r.get("index")
                                if idx is not None and idx < len(batch):
                                    doc = dict(batch[idx])
                                    doc["rerank_score"] = r.get("relevance_score", 0)
                                    all_reranked.append(doc)
                        else:
                            logger.warning("[Reranker] Batch %d returned invalid data", i + 1)
                            all_reranked.extend(batch)
                            failed_batches += 1
                    else:
                        raise RuntimeError(f"API Error {resp.status_code}: {resp.text[:500]}")

                except Exception as exc:
                    failed_batches += 1
                    self._record_failure(exc, i)
                    all_reranked.extend(batch)

                    if failed_batches / (i + 1) > 0.5 and i > 2:
                        logger.warning("[Reranker] Too many failures, terminating early")
                        for j in range(i + 1, len(batches)):
                            all_reranked.extend(batches[j])
                        break

        self._cleanup_failure_records()

        # 全局排序
        all_reranked.sort(key=lambda d: d.get("rerank_score", d.get("score", -1)), reverse=True)
        final = all_reranked[:top_k]
        success_rate = ((len(batches) - failed_batches) / len(batches) * 100) if batches else 0
        logger.info("[Reranker] Complete: %d docs (success rate: %.1f%%)", len(final), success_rate)
        return final

    # ------------------------------------------------------------------
    # Token 预算
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """中英混合 Token 估算：中文 ~1.5 token/char，英文 ~0.25 token/char。"""
        if not text:
            return 0
        chinese = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
        other = len(text) - chinese
        return int(chinese * 1.5 + other * 0.25 + 0.5)

    def _split_into_batches(self, documents: list[dict], max_doc_tokens: int) -> list[list[dict]]:
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        current_tokens = 0

        for doc in documents:
            doc_tokens = self._estimate_tokens(doc.get("text", ""))
            if doc_tokens > max_doc_tokens:
                logger.warning("[Reranker] Document too large (%d tokens), skipping", doc_tokens)
                continue
            if current_tokens + doc_tokens > max_doc_tokens and current_batch:
                batches.append(current_batch)
                current_batch = [doc]
                current_tokens = doc_tokens
            else:
                current_batch.append(doc)
                current_tokens += doc_tokens

        if current_batch:
            batches.append(current_batch)
        return batches

    # ------------------------------------------------------------------
    # 断路器
    # ------------------------------------------------------------------

    def _is_circuit_open(self) -> bool:
        now = time.time()
        recent = sum(1 for ts in self._failure_records.values() if now - ts < self.circuit_breaker_window)
        return recent >= self.circuit_breaker_threshold

    def _record_failure(self, error: Exception, batch_index: int) -> None:
        now = time.time()
        key = f"fail_{now}_{batch_index}"
        self._failure_records[key] = now

        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            data = error.response.text[:200]
            logger.error("[Reranker] API Error - Status: %d, Data: %s", status, data)
        elif isinstance(error, httpx.TimeoutException):
            logger.error("[Reranker] Timeout after %.0fms", self.timeout * 1000)
        else:
            logger.error("[Reranker] Error: %s", error)

    def _cleanup_failure_records(self) -> None:
        now = time.time()
        expired = [k for k, ts in self._failure_records.items() if now - ts > self.circuit_breaker_cooldown]
        for k in expired:
            del self._failure_records[k]
