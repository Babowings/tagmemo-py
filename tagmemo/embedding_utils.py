"""embedding_utils.py — 并发批量 Embedding API 调用，替代 EmbeddingUtils.js (110 行)。

提供 ``get_embeddings_batch()``：将大量文本按 token / 条数分批，
通过 ``asyncio.Semaphore`` 控制并发数调用远端 Embedding API。
"""

from __future__ import annotations

import asyncio
import os
import logging

import httpx
import tiktoken

logger = logging.getLogger(__name__)

# 编码器
_encoding = tiktoken.get_encoding("cl100k_base")

# 配置（与 JS 版一致）
_embedding_max_token = int(os.environ.get("WhitelistEmbeddingModelMaxToken", "8000"))
_safe_max_tokens = int(_embedding_max_token * 0.85)
_MAX_BATCH_ITEMS = 100
_DEFAULT_CONCURRENCY = int(os.environ.get("TAG_VECTORIZE_CONCURRENCY", "5"))


# ------------------------------------------------------------------
# 内部：发送单个 batch
# ------------------------------------------------------------------

async def _send_batch(
    client: httpx.AsyncClient,
    batch_texts: list[str],
    config: dict,
    batch_number: int,
) -> list[list[float]]:
    """发送单批文本到 Embedding API，带重试（3 次指数退避 + 429 特殊处理）。"""
    retry_attempts = 3
    base_delay = 1.0  # seconds

    url = f"{config['api_url'].rstrip('/')}/v1/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    for attempt in range(1, retry_attempts + 1):
        try:
            resp = await client.post(
                url,
                json={"model": config["model"], "input": batch_texts},
                headers=headers,
                timeout=60.0,
            )

            if resp.status_code == 429:
                wait = 5.0 * attempt
                logger.warning(
                    "[Embedding] Batch %d rate limited (429). Retrying in %.0fs...",
                    batch_number,
                    wait,
                )
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200:
                raise RuntimeError(
                    f"API Error {resp.status_code}: {resp.text[:500]}"
                )

            data = resp.json()

            if not data or data.get("error"):
                err_msg = (
                    data.get("error", {}).get("message")
                    if isinstance(data.get("error"), dict)
                    else str(data.get("error", "Unknown error"))
                )
                raise RuntimeError(f"API Error: {err_msg}")

            items = data.get("data")
            if not isinstance(items, list):
                raise RuntimeError("Invalid API response: missing 'data' array")

            # 按 index 排序后返回 embedding 列表
            items.sort(key=lambda x: x["index"])
            return [item["embedding"] for item in items]

        except Exception as exc:
            logger.warning(
                "[Embedding] Batch %d, attempt %d failed: %s",
                batch_number,
                attempt,
                exc,
            )
            if attempt == retry_attempts:
                raise
            await asyncio.sleep(base_delay * (2 ** attempt))

    return []  # unreachable, but keeps mypy happy


# ------------------------------------------------------------------
# 公开 API
# ------------------------------------------------------------------

async def get_embeddings_batch(
    texts: list[str],
    config: dict,
    *,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> list[list[float] | None]:
    """并发批量获取 Embedding 向量。

    Parameters
    ----------
    texts : list[str]
        待向量化的文本列表。
    config : dict
        必须包含 ``api_url``, ``api_key``, ``model``。
    concurrency : int
        最大并发 batch 数（默认读取环境变量 TAG_VECTORIZE_CONCURRENCY）。

    Returns
    -------
    list[list[float] | None]
        与输入文本严格一一对应的向量列表；失败或超长文本位置为 ``None``。
    """
    if not texts:
        return []

    # 1. 按 token 数 / 条数分批，同时记录原始位置
    batches: list[dict[str, list]] = []
    current_batch: list[str] = []
    current_indices: list[int] = []
    current_tokens = 0
    oversize_indices: set[int] = set()

    for idx, text in enumerate(texts):
        text_tokens = len(_encoding.encode(text))
        if text_tokens > _safe_max_tokens:
            oversize_indices.add(idx)
            continue

        token_full = len(current_batch) > 0 and (current_tokens + text_tokens > _safe_max_tokens)
        item_full = len(current_batch) >= _MAX_BATCH_ITEMS

        if token_full or item_full:
            batches.append({"texts": current_batch, "indices": current_indices})
            current_batch = [text]
            current_indices = [idx]
            current_tokens = text_tokens
        else:
            current_batch.append(text)
            current_indices.append(idx)
            current_tokens += text_tokens

    if current_batch:
        batches.append({"texts": current_batch, "indices": current_indices})

    if not batches:
        return [None] * len(texts)

    # 2. 受控并发（Semaphore 替代 JS worker pool）
    # 共享单个 AsyncClient 以复用连接池，与原版 JS worker pool 共享 fetch 实例一致
    sem = asyncio.Semaphore(concurrency)
    results: list[dict | None] = [None] * len(batches)

    async with httpx.AsyncClient() as client:

        async def _worker(idx: int) -> None:
            async with sem:
                batch = batches[idx]
                try:
                    vectors = await _send_batch(client, batch["texts"], config, idx + 1)
                except Exception as exc:
                    logger.error(
                        "[Embedding] Batch %d failed permanently: %s",
                        idx + 1,
                        exc,
                    )
                    vectors = None
                results[idx] = {"vectors": vectors, "indices": batch["indices"]}

        await asyncio.gather(*[_worker(i) for i in range(len(batches))])

    # 3. 按原始顺序回填，保证 output.length === input.length
    final_results: list[list[float] | None] = [None] * len(texts)
    for r in results:
        if not r or not r["vectors"]:
            continue
        for vec_idx, original_idx in enumerate(r["indices"]):
            final_results[original_idx] = r["vectors"][vec_idx] if vec_idx < len(r["vectors"]) else None

    for oversize_idx in oversize_indices:
        final_results[oversize_idx] = None

    return final_results
