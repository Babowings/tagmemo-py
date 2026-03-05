"""engine.py — TagMemo 核心引擎，替代 TagMemoEngine.js (780 行)。

从 VCPToolBox RAGDiaryPlugin 重构而来，提供纯净的记忆检索 API：
  engine.query(user_message, conversation_history) → {memory_context, metrics, results}

核心算法链：
  EPA → Residual Pyramid → TagBoost V3.7 → Shotgun Query → SVD Dedup
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .context_vector import ContextVectorManager
from .embedding_service import EmbeddingService
from .knowledge_base import KnowledgeBaseManager
from .reranker import Reranker
from .semantic_groups import SemanticGroupManager
from .text_sanitizer import TextSanitizer
from .time_parser import TimeExpressionParser

logger = logging.getLogger(__name__)


class TagMemoEngine:
    """TagMemo 核心引擎 — 1:1 对应原 TagMemoEngine.js。

    Parameters
    ----------
    config : dict
        api_key, api_url, embedding_model, chat_api_key, chat_api_url,
        chat_model, dimension, root_path, store_path, enable_semantic_groups,
        enable_time_parsing, timezone, query_cache_max_size, query_cache_ttl …
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}

        self.config: dict = {
            "api_key": cfg.get("api_key") or os.environ.get("API_Key", ""),
            "api_url": cfg.get("api_url") or os.environ.get("API_URL", ""),
            "embedding_model": (
                cfg.get("embedding_model")
                or os.environ.get("WhitelistEmbeddingModel", "text-embedding-3-small")
            ),
            "chat_api_key": (
                cfg.get("chat_api_key")
                or os.environ.get("CHAT_API_KEY")
                or cfg.get("api_key")
                or os.environ.get("API_Key", "")
            ),
            "chat_api_url": cfg.get("chat_api_url") or os.environ.get("CHAT_API_URL", ""),
            "chat_model": cfg.get("chat_model") or os.environ.get("CHAT_MODEL", "gpt-4o-mini"),
            "dimension": int(os.environ.get("VECTORDB_DIMENSION", 0)) or cfg.get("dimension", 3072),
            "root_path": cfg.get("root_path") or os.environ.get("KNOWLEDGEBASE_ROOT_PATH", ""),
            "store_path": cfg.get("store_path") or os.environ.get("KNOWLEDGEBASE_STORE_PATH", ""),
            "enable_semantic_groups": cfg.get("enable_semantic_groups", True),
            "enable_time_parsing": cfg.get("enable_time_parsing", True),
            "timezone": cfg.get("timezone") or os.environ.get("DEFAULT_TIMEZONE", "Asia/Shanghai"),
            "query_cache_max_size": (
                cfg.get("query_cache_max_size")
                or int(os.environ.get("QUERY_CACHE_MAX_SIZE", "200"))
            ),
            "query_cache_ttl": (
                cfg.get("query_cache_ttl")
                or int(os.environ.get("QUERY_CACHE_TTL_MS", "3600000"))
            ) / 1000.0,  # 转为秒
            **cfg,
        }

        # 子系统（延迟初始化）
        self.embedding_service: EmbeddingService | None = None
        self.knowledge_base: KnowledgeBaseManager | None = None
        self.context_vector_manager: ContextVectorManager | None = None
        self.semantic_group_manager: SemanticGroupManager | None = None
        self.time_parser: TimeExpressionParser | None = None

        # Reranker（可选 — 配置了 RERANK_API_URL 后自动启用）
        self.reranker = Reranker(cfg.get("rerank") or {})

        # 缓存（增强版: FIFO 淘汰 + TTL + 命中统计 + 定期清理）
        self.query_cache: dict[str, dict] = {}
        self.cache_stats: dict[str, int] = {"hits": 0, "misses": 0}
        self._cache_cleanup_task: asyncio.Task | None = None

        # RAG 参数（从 KnowledgeBaseManager 共享 + 本地热加载）
        self.rag_params: dict = {}
        self._rag_params_watcher_task: asyncio.Task | None = None

        self.initialized = False

        # 内部暂存（供 Reranker 使用）
        self._last_query_text: str = ""

    # =================================================================
    # 初始化
    # =================================================================

    async def initialize(self) -> None:
        if self.initialized:
            return
        logger.info("[TagMemoEngine] Initializing...")

        # 1. Embedding Service
        self.embedding_service = EmbeddingService({
            "api_key": self.config["api_key"],
            "api_url": self.config["api_url"],
            "model": self.config["embedding_model"],
        })

        # 2. Knowledge Base Manager
        self.knowledge_base = KnowledgeBaseManager({
            "root_path": self.config["root_path"],
            "store_path": self.config["store_path"],
            "api_key": self.config["api_key"],
            "api_url": self.config["api_url"],
            "model": self.config["embedding_model"],
            "dimension": self.config["dimension"],
        })
        await self.knowledge_base.initialize()
        self.rag_params = self.knowledge_base.rag_params

        # 3. Context Vector Manager
        self.context_vector_manager = ContextVectorManager(
            embed_fn=self.embedding_service.embed,
            get_cached_embedding=self.embedding_service.get_from_cache_only,
        )

        # 4. Semantic Group Manager（可选）
        if self.config["enable_semantic_groups"]:
            self.semantic_group_manager = SemanticGroupManager(
                embed_fn=self.embedding_service.embed,
            )
            await self.semantic_group_manager.initialize()

        # 5. Time Expression Parser（可选）
        if self.config["enable_time_parsing"]:
            self.time_parser = TimeExpressionParser()

        # 6. 启动 rag_params.json 热加载（统一 watcher，
        #    设计改进：原版 Engine + KBM 各自独立监听，Python 版合并）
        self._rag_params_watcher_task = asyncio.create_task(self._watch_rag_params())

        # 7. 启动缓存定期清理（每 10 分钟）
        self._cache_cleanup_task = asyncio.create_task(self._periodic_cache_cleanup())

        self.initialized = True
        logger.info(
            "[TagMemoEngine] Ready (Rerank: %s)",
            "ON" if self.reranker.enabled else "OFF",
        )

    # =================================================================
    # Public API – query
    # =================================================================

    async def query(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        options: dict | None = None,
    ) -> dict:
        """核心查询方法 — 输入用户消息和对话历史，返回记忆上下文。

        Returns
        -------
        dict  {memory_context: str, metrics: dict, results: list[dict]}
        """
        if not self.initialized:
            await self.initialize()

        history = conversation_history or []
        opts = options or {}
        start_ts = time.monotonic()

        diary_name: str | None = opts.get("diary_name") or opts.get("diaryName")
        use_time_aware: bool = opts.get("use_time_aware", True)
        use_semantic_groups: bool = opts.get(
            "use_semantic_groups", self.config["enable_semantic_groups"]
        )
        use_rerank: bool = opts.get("use_rerank", False)
        k_multiplier: float = float(opts.get("k_multiplier", 1.0) or 1.0)

        try:
            # 1. 更新上下文向量映射
            messages = self._build_messages_array(user_message, history)
            await self.context_vector_manager.update_context(messages, allow_api=True)

            # 2. 清洗文本
            clean_user = TextSanitizer.sanitize(user_message)
            last_ai = self._extract_last_ai_content(history)
            clean_ai = TextSanitizer.sanitize(last_ai) if last_ai else None

            # 保存查询文本供 Reranker 使用
            self._last_query_text = clean_user

            # 3. 组合查询 & 向量化
            combined_query = (
                f"[AI]: {clean_ai}\n[User]: {clean_user}" if clean_ai else clean_user
            )
            query_vector = await self.embedding_service.embed(combined_query)
            if query_vector is None:
                return {
                    "memory_context": "",
                    "metrics": {"error": "embedding_failed"},
                    "results": [],
                }

            # 4. 检查缓存
            cache_key = self._generate_cache_key(clean_user, clean_ai, diary_name)
            cached = self._get_cached(cache_key)
            if cached:
                logger.info("[TagMemoEngine] Cache hit")
                return cached

            # 5. 动态参数计算
            dynamic_params = self._calculate_dynamic_params(
                query_vector, clean_user, clean_ai
            )
            if abs(k_multiplier - 1.0) > 1e-9:
                dynamic_params["k"] = max(1, min(30, int(round(dynamic_params["k"] * k_multiplier))))
                dynamic_params["metrics"]["k_multiplier"] = k_multiplier

            # 6. 语义组增强
            final_query_vector = query_vector
            activated_groups: dict[str, dict] | None = None
            if use_semantic_groups and self.semantic_group_manager:
                activated_groups = self.semantic_group_manager.detect_and_activate_groups(
                    clean_user
                )
                if activated_groups:
                    enhanced = await self.semantic_group_manager.get_enhanced_vector(
                        clean_user, activated_groups, query_vector
                    )
                    if enhanced:
                        final_query_vector = enhanced

            # 7. Tag 感应（通过 apply_tag_boost）
            core_tags_for_search: list[str] = []
            if dynamic_params["tag_weight"] > 0 and self.knowledge_base:
                try:
                    boost_result = self.knowledge_base.apply_tag_boost(
                        query_vector, dynamic_params["tag_weight"], []
                    )
                    matched = (boost_result.get("info") or {}).get("matched_tags")
                    if matched:
                        core_tags_for_search = self._truncate_core_tags(
                            matched,
                            dynamic_params["tag_truncation_ratio"],
                        )
                except Exception as exc:
                    logger.warning("[TagMemoEngine] Tag sensing failed: %s", exc)

            # 8. 获取历史分段（用于 Shotgun Query）
            history_segments = self.context_vector_manager.segment_context(messages)

            # 9. 时间解析（可选）
            time_ranges: list[dict] = []
            if use_time_aware and self.time_parser:
                combined_for_time = "\n".join(
                    filter(None, [clean_user, clean_ai])
                )
                time_ranges = self.time_parser.parse(combined_for_time)

            # 10. 核心检索 — 时间感知 or Shotgun Query
            if time_ranges:
                results, search_meta = await self._time_aware_query(
                    diary_name=diary_name,
                    query_vector=final_query_vector,
                    history_segments=history_segments,
                    k=dynamic_params["k"],
                    tag_weight=dynamic_params["tag_weight"],
                    core_tags=core_tags_for_search,
                    time_ranges=time_ranges,
                    use_rerank=use_rerank,
                )
            else:
                results, search_meta = await self._shotgun_query(
                    diary_name=diary_name,
                    query_vector=final_query_vector,
                    history_segments=history_segments,
                    k=dynamic_params["k"],
                    tag_weight=dynamic_params["tag_weight"],
                    core_tags=core_tags_for_search,
                    use_rerank=use_rerank,
                )

            # 11. 格式化记忆上下文
            memory_context = self._format_results(
                results,
                diary_name,
                activated_groups=activated_groups,
                core_tags_for_search=core_tags_for_search,
                dynamic_params=dynamic_params,
                time_ranges=time_ranges,
            )

            latency_ms = (time.monotonic() - start_ts) * 1000
            response: dict = {
                "memory_context": memory_context,
                "metrics": {
                    **dynamic_params["metrics"],
                    "k": dynamic_params["k"],
                    "tag_weight": dynamic_params["tag_weight"],
                    "tag_truncation_ratio": dynamic_params["tag_truncation_ratio"],
                    "core_tags": core_tags_for_search,
                    "result_count": len(results),
                    "search_vector_count": search_meta.get("vector_count", 0),
                    "reranked": search_meta.get("reranked", False),
                    "activated_groups": list(activated_groups.keys()) if activated_groups else [],
                    "time_ranges": len(time_ranges),
                    "latency_ms": round(latency_ms, 1),
                    "cache_hit": False,
                },
                "results": results,
            }

            # 缓存结果
            self._set_cache(cache_key, response)
            logger.info(
                "[TagMemoEngine] Query complete: %d results in %.0fms",
                len(results),
                latency_ms,
            )
            return response

        except Exception as exc:
            latency_ms = (time.monotonic() - start_ts) * 1000
            logger.error("[TagMemoEngine] Query error: %s", exc, exc_info=True)
            return {
                "memory_context": "",
                "metrics": {"error": str(exc), "latency_ms": round(latency_ms, 1)},
                "results": [],
            }

    # =================================================================
    # Dynamic Params
    # =================================================================

    def _calculate_dynamic_params(
        self,
        query_vector: list[float],
        user_text: str | None,
        ai_text: str | None,
    ) -> dict:
        # 基础 K 值
        user_len = len(user_text) if user_text else 0
        k_base = 3
        if user_len > 100:
            k_base = 6
        elif user_len > 30:
            k_base = 4

        if ai_text:
            tokens = re.findall(r"[a-zA-Z0-9]+|[^\s\x00-\xff]", ai_text)
            unique_tokens = len(set(tokens))
            if unique_tokens > 100:
                k_base = max(k_base, 6)
            elif unique_tokens > 40:
                k_base = max(k_base, 4)

        # EPA 分析
        epa = self.knowledge_base.get_epa_analysis(query_vector)
        logic_depth = epa.get("logicDepth", 0.5)
        resonance = epa.get("resonance", 0)

        # 语义宽度
        semantic_width = ContextVectorManager.compute_semantic_width(query_vector)

        # 动态 Beta (TagWeight)
        cfg = (
            self.rag_params.get("RAGDiaryPlugin")
            or self.rag_params.get("TagMemoEngine")
            or {}
        )
        noise_penalty = cfg.get("noise_penalty", 0.05)
        beta_input = logic_depth * math.log(1 + resonance + 1) - semantic_width * noise_penalty
        beta = self._sigmoid(beta_input)

        weight_range = cfg.get("tagWeightRange", [0.05, 0.45])
        final_tag_weight = weight_range[0] + beta * (weight_range[1] - weight_range[0])

        # 动态 K
        k_adjustment = round(logic_depth * 3 + math.log1p(resonance) * 2)
        final_k = max(3, min(10, k_base + k_adjustment))

        # 动态 Tag 截断比例
        tag_truncation_base = cfg.get("tagTruncationBase", 0.6)
        tag_truncation_ratio = (
            tag_truncation_base
            + logic_depth * 0.3
            - semantic_width * 0.2
            + min(resonance, 1) * 0.1
        )
        truncation_range = cfg.get("tagTruncationRange", [0.5, 0.9])
        tag_truncation_ratio = max(
            truncation_range[0], min(truncation_range[1], tag_truncation_ratio)
        )

        logger.info(
            "[TagMemoEngine] L=%.3f, R=%.3f, S=%.3f => Beta=%.3f, TagWeight=%.3f, K=%d",
            logic_depth, resonance, semantic_width, beta, final_tag_weight, final_k,
        )

        return {
            "k": final_k,
            "tag_weight": final_tag_weight,
            "tag_truncation_ratio": tag_truncation_ratio,
            "metrics": {
                "L": logic_depth,
                "R": resonance,
                "S": semantic_width,
                "beta": beta,
            },
        }

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    @staticmethod
    def _truncate_core_tags(tags: list[str], ratio: float) -> list[str]:
        if not tags or len(tags) <= 5:
            return tags
        target_count = max(5, math.ceil(len(tags) * ratio))
        truncated = tags[:target_count]
        if len(truncated) < len(tags):
            logger.info(
                "[TagMemoEngine] Tag truncation: %d -> %d (ratio=%.2f)",
                len(tags), len(truncated), ratio,
            )
        return truncated

    # =================================================================
    # Shotgun Query
    # =================================================================

    async def _shotgun_query(
        self,
        *,
        diary_name: str | None,
        query_vector: list[float],
        history_segments: list[dict],
        k: int,
        tag_weight: float,
        core_tags: list[str],
        use_rerank: bool,
    ) -> tuple[list[dict], dict]:
        """Shotgun Query: 多向量并行搜索 + SVD 去重 + 可选 Rerank。"""
        do_rerank = use_rerank and self.reranker.enabled
        search_k = self.reranker.get_search_k(k) if do_rerank else k

        # 构建搜索向量数组
        search_vectors: list[dict] = [{"vector": query_vector, "type": "current"}]
        if history_segments:
            recent = history_segments[-3:]
            for i, seg in enumerate(recent):
                search_vectors.append({"vector": seg["vector"], "type": f"history_{i}"})

        logger.info(
            "[TagMemoEngine] Shotgun Query: %d parallel searches (K=%d%s)",
            len(search_vectors),
            search_k,
            f", rerank→{k}" if do_rerank else "",
        )

        # 并行搜索
        async def _search_one(qv: dict) -> list[dict]:
            try:
                qv_k = search_k if qv["type"] == "current" else max(2, round(search_k / 2))
                return await self.knowledge_base.search(
                    diary_name, qv["vector"], qv_k, tag_weight, core_tags,
                )
            except Exception as exc:
                logger.error(
                    "[TagMemoEngine] Shotgun search failed [%s]: %s", qv["type"], exc,
                )
                return []

        results_arrays = await asyncio.gather(*[_search_one(qv) for qv in search_vectors])
        flattened = [r for arr in results_arrays for r in arr]

        # SVD + Residual 去重
        unique_results = await self.knowledge_base.deduplicate_results(
            flattened, query_vector
        )

        # Rerank 重排序（仅在显式请求时）
        reranked = False
        if do_rerank and len(unique_results) > 1:
            final_results = await self.reranker.rerank(
                self._last_query_text or "", unique_results, k,
            )
            reranked = final_results is not unique_results
        else:
            final_results = unique_results[:k]

        tagged_results = [{**r, "source": "rag"} for r in final_results]

        search_meta = {
            "vector_count": len(search_vectors),
            "raw_result_count": len(flattened),
            "deduplicated_count": len(unique_results),
            "reranked": reranked,
        }
        return tagged_results, search_meta

    # =================================================================
    # Time-Aware Query
    # =================================================================

    async def _time_aware_query(
        self,
        *,
        diary_name: str | None,
        query_vector: list[float],
        history_segments: list[dict],
        k: int,
        tag_weight: float,
        core_tags: list[str],
        time_ranges: list[dict],
        use_rerank: bool,
    ) -> tuple[list[dict], dict]:
        """时间感知检索: 语义搜索 + 时间范围扫描，合并去重。"""

        # 1. 标准 Shotgun Query
        rag_results, _ = await self._shotgun_query(
            diary_name=diary_name,
            query_vector=query_vector,
            history_segments=history_segments,
            k=k,
            tag_weight=tag_weight,
            core_tags=core_tags,
            use_rerank=use_rerank,
        )

        # 2. 时间范围检索
        time_results = await self._get_time_range_diaries(diary_name, time_ranges)

        # 3. 合并去重（以文本内容前 200 字符去重）
        all_entries: dict[str, dict] = {}
        for entry in rag_results:
            key = (entry.get("text") or "").strip()[:200]
            if key and key not in all_entries:
                all_entries[key] = entry
        for entry in time_results:
            key = (entry.get("text") or "").strip()[:200]
            if key and key not in all_entries:
                all_entries[key] = entry

        merged = list(all_entries.values())
        logger.info(
            "[TagMemoEngine] TimeAware: %d semantic + %d temporal = %d unique",
            len(rag_results),
            len(time_results),
            len(merged),
        )

        search_meta = {
            "vector_count": 1,
            "raw_result_count": len(rag_results) + len(time_results),
            "deduplicated_count": len(merged),
            "time_ranges_used": len(time_ranges),
        }
        return merged, search_meta

    async def _get_time_range_diaries(
        self, diary_name: str | None, time_ranges: list[dict]
    ) -> list[dict]:
        """从磁盘按时间范围检索日记文件。

        解析文件首行时间戳 [YYYY-MM-DD] 或 YYYY.MM.DD，筛选在范围内的条目。
        """
        root_path = self.config.get("root_path")
        if not root_path:
            return []

        tz = ZoneInfo(self.config.get("timezone", "Asia/Shanghai"))
        diaries_in_range: list[dict] = []

        # 确定要扫描的目录
        dirs_to_scan: list[str] = []
        if diary_name:
            dirs_to_scan.append(os.path.join(root_path, diary_name))
        else:
            try:
                for entry in os.scandir(root_path):
                    if entry.is_dir():
                        dirs_to_scan.append(entry.path)
            except OSError:
                return []

        date_pattern = re.compile(r"^\[?(\d{4}[-.]\d{2}[-.]\d{2})\]?")

        for dir_path in dirs_to_scan:
            try:
                for fname in os.listdir(dir_path):
                    if not fname.lower().endswith((".txt", ".md")):
                        continue
                    try:
                        file_path = os.path.join(dir_path, fname)
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        first_line = content.split("\n", 1)[0]
                        m = date_pattern.match(first_line)
                        if not m:
                            continue

                        date_str = m.group(1).replace(".", "-")
                        diary_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                            tzinfo=tz
                        )

                        for tr in time_ranges:
                            tr_start = tr.get("start")
                            tr_end = tr.get("end")
                            if not tr_start or not tr_end:
                                continue
                            if tr_start <= diary_date <= tr_end:
                                diaries_in_range.append({
                                    "date": date_str,
                                    "text": content[:2000],
                                    "sourceFile": fname,
                                    "source": "time",
                                })
                                break  # 一个文件只加一次
                    except Exception:
                        pass  # 忽略单个文件错误
            except OSError as exc:
                if not str(exc).startswith("[Errno 2]"):
                    logger.warning(
                        "[TagMemoEngine] Time scan error for %s: %s", dir_path, exc,
                    )

        return diaries_in_range

    # =================================================================
    # Result Formatting
    # =================================================================

    def _format_results(
        self,
        results: list[dict],
        diary_name: str | None,
        *,
        activated_groups: dict[str, dict] | None = None,
        core_tags_for_search: list[str] | None = None,
        dynamic_params: dict | None = None,
        time_ranges: list[dict] | None = None,
    ) -> str:
        if not results:
            return "没有找到相关的记忆片段。"

        display_name = f"{diary_name} 日记本" if diary_name else "全部记忆"
        parts: list[str] = []

        rag_entries = [r for r in results if r.get("source") == "rag"]
        time_entries = [r for r in results if r.get("source") == "time"]
        has_time = len(time_entries) > 0

        if has_time and time_ranges:
            def _fmt_date(d: datetime | str) -> str:
                if isinstance(d, str):
                    return d[:10]
                return d.strftime("%Y-%m-%d")

            range_str = ", ".join(
                f"{_fmt_date(tr['start'])} ~ {_fmt_date(tr['end'])}"
                for tr in time_ranges
                if tr.get("start") and tr.get("end")
            )
            parts.append(f"[--- 「{display_name}」多时间感知检索结果 ---]")
            parts.append(f"[时间范围: {range_str}]")
            parts.append(
                f"[统计: {len(results)} 条记忆 "
                f"(语义 {len(rag_entries)}, 时间 {len(time_entries)})]"
            )
        else:
            parts.append(f"[--- 从「{display_name}」中检索到 {len(results)} 条相关记忆片段 ---]")

        # 语义组信息
        if activated_groups:
            group_info = "; ".join(
                f"{name}({data['strength'] * 100:.0f}%, "
                f"匹配: {', '.join(data.get('matched_words', []))})"
                for name, data in activated_groups.items()
            )
            parts.append(f"[语义组激活: {group_info}]")

        # 核心标签
        if core_tags_for_search:
            parts.append(f"[TagMemo 记忆标签: {', '.join(core_tags_for_search)}]")

        # 语义相关记忆
        if has_time and rag_entries:
            parts.append("")
            parts.append("【语义相关记忆】")
            for i, r in enumerate(rag_entries, 1):
                score_str = f" [{r['score'] * 100:.1f}%]" if r.get("score") else ""
                source_str = f" ({r['sourceFile']})" if r.get("sourceFile") else ""
                parts.append(f"{i}. {r.get('text', '').strip()}{score_str}{source_str}")

        # 时间范围记忆
        if has_time and time_entries:
            parts.append("")
            parts.append("【时间范围记忆】")
            time_entries.sort(key=lambda r: r.get("date", ""), reverse=True)
            for i, r in enumerate(time_entries, 1):
                date_prefix = f"[{r['date']}] " if r.get("date") else ""
                source_str = f" ({r['sourceFile']})" if r.get("sourceFile") else ""
                # 去除首行日期标记
                body = re.sub(r"^\[.*?\]\s*-\s*.*?\n?", "", r.get("text", "")).strip()[:500]
                parts.append(f"{i}. {date_prefix}{body}{source_str}")

        # 标准格式（非时间感知）
        if not has_time:
            for i, r in enumerate(results, 1):
                score_str = f" [相关度: {r['score'] * 100:.1f}%]" if r.get("score") else ""
                source_str = f" (来源: {r['sourceFile']})" if r.get("sourceFile") else ""
                parts.append(f"{i}. {r.get('text', '').strip()}{score_str}{source_str}")

        parts.append("[--- 记忆片段结束 ---]")
        return "\n".join(parts)

    # =================================================================
    # Cache (增强版 — FIFO 淘汰 + TTL)
    # =================================================================

    def _generate_cache_key(
        self, user_text: str | None, ai_text: str | None, diary_name: str | None
    ) -> str:
        raw = json.dumps(
            {
                "u": (user_text or "")[:200],
                "a": (ai_text or "")[:200],
                "d": diary_name or "*",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            },
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _get_cached(self, key: str) -> dict | None:
        entry = self.query_cache.get(key)
        if entry is None:
            self.cache_stats["misses"] += 1
            return None
        if time.monotonic() - entry["ts"] > self.config["query_cache_ttl"]:
            del self.query_cache[key]
            self.cache_stats["misses"] += 1
            return None
        self.cache_stats["hits"] += 1
        result = entry["value"].copy()
        result["metrics"] = {**result.get("metrics", {}), "cache_hit": True}
        return result

    def _set_cache(self, key: str, value: dict) -> None:
        # FIFO 淘汰（与原版 Map.keys().next().value 一致）
        max_size = self.config.get("query_cache_max_size", 200)
        if len(self.query_cache) >= max_size:
            oldest = next(iter(self.query_cache))
            del self.query_cache[oldest]
        self.query_cache[key] = {"value": value, "ts": time.monotonic()}

    async def _periodic_cache_cleanup(self) -> None:
        """定期清理过期缓存条目（每 10 分钟）。"""
        try:
            while True:
                await asyncio.sleep(600)  # 10 分钟
                self._evict_expired_cache()
        except asyncio.CancelledError:
            pass

    def _evict_expired_cache(self) -> None:
        now = time.monotonic()
        ttl = self.config["query_cache_ttl"]
        expired = [k for k, v in self.query_cache.items() if now - v["ts"] > ttl]
        for k in expired:
            del self.query_cache[k]
        if expired:
            logger.info(
                "[TagMemoEngine] Cache eviction: removed %d expired, %d remaining",
                len(expired),
                len(self.query_cache),
            )

    def clear_cache(self) -> None:
        """清空查询缓存。"""
        self.query_cache.clear()
        self.cache_stats = {"hits": 0, "misses": 0}
        logger.info("[TagMemoEngine] Query cache cleared")

    def get_cache_stats(self) -> dict:
        """获取缓存统计。"""
        total = self.cache_stats["hits"] + self.cache_stats["misses"]
        return {
            "size": len(self.query_cache),
            "max_size": self.config.get("query_cache_max_size", 200),
            "ttl_ms": self.config["query_cache_ttl"] * 1000,
            "hits": self.cache_stats["hits"],
            "misses": self.cache_stats["misses"],
            "hit_rate": (
                f"{self.cache_stats['hits'] / total * 100:.1f}%"
                if total > 0 else "N/A"
            ),
            "embedding_cache": (
                self.embedding_service.get_stats() if self.embedding_service else {}
            ),
        }

    def get_rerank_status(self) -> dict:
        """获取 Reranker 状态信息。"""
        return {
            "enabled": self.reranker.enabled,
            "model": self.reranker.model,
            "multiplier": self.reranker.multiplier,
            "max_tokens": self.reranker.max_tokens,
        }

    async def delete_memory(
        self,
        file_paths: list[str] | None = None,
        diary_name: str | None = None,
        dry_run: bool = False,
        cleanup_orphans: bool = True,
    ) -> dict:
        """删除记忆数据（按文件路径或 diaryName）。"""
        if not self.initialized:
            await self.initialize()
        if self.knowledge_base is None:
            raise RuntimeError("Knowledge base is not initialized")

        result = self.knowledge_base.delete_memories(
            file_paths=file_paths,
            diary_name=diary_name,
            dry_run=dry_run,
            cleanup_orphans=cleanup_orphans,
        )
        if not dry_run and result.get("deleted_files", 0) > 0:
            self.clear_cache()
            result["cache_cleared"] = True
        else:
            result["cache_cleared"] = False
        return result

    # =================================================================
    # RAG Params Hot-Reload
    # =================================================================

    async def _watch_rag_params(self) -> None:
        """监听 rag_params.json 变更，替代原版 chokidar watcher。

        设计改进：原版 Engine + KBM 各自独立监听，Python 版合并为一处。
        使用 asyncio polling（轻量，避免额外 watchdog 线程）。
        """
        params_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "rag_params.json",
        )
        last_mtime: float = 0.0
        try:
            while True:
                await asyncio.sleep(2)  # 2 秒轮询
                try:
                    st = os.stat(params_path)
                    if st.st_mtime != last_mtime and last_mtime != 0.0:
                        logger.info("[TagMemoEngine] rag_params.json changed, reloading...")
                        with open(params_path, "r", encoding="utf-8") as f:
                            self.rag_params = json.load(f)
                        # 同步到 KnowledgeBaseManager
                        if self.knowledge_base:
                            self.knowledge_base.rag_params = self.rag_params
                        # 参数变更清空缓存
                        self.clear_cache()
                        logger.info("[TagMemoEngine] RAG params reloaded")
                    last_mtime = st.st_mtime
                except FileNotFoundError:
                    pass
                except json.JSONDecodeError as exc:
                    logger.error("[TagMemoEngine] Failed to parse rag_params: %s", exc)
        except asyncio.CancelledError:
            pass

    async def reload_params(self) -> None:
        """手动重新加载 RAG 参数。"""
        params_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "rag_params.json",
        )
        with open(params_path, "r", encoding="utf-8") as f:
            self.rag_params = json.load(f)
        if self.knowledge_base:
            self.knowledge_base.rag_params = self.rag_params
        self.clear_cache()
        logger.info("[TagMemoEngine] RAG params manually reloaded")

    # =================================================================
    # Helpers
    # =================================================================

    @staticmethod
    def _build_messages_array(
        user_message: str, conversation_history: list[dict]
    ) -> list[dict]:
        messages = list(conversation_history)
        if user_message:
            messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _extract_last_ai_content(history: list[dict]) -> str | None:
        """反向搜索最后一条 assistant 消息内容。"""
        for i in range(len(history) - 1, -1, -1):
            msg = history[i]
            if msg.get("role") == "assistant" and msg.get("content"):
                content = msg["content"]
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    text_part = next(
                        (p.get("text", "") for p in content if p.get("type") == "text"),
                        "",
                    )
                    return text_part or None
        return None

    # =================================================================
    # Lifecycle
    # =================================================================

    async def shutdown(self) -> None:
        """优雅关闭：取消后台任务 → 关闭知识库 → 清空缓存。"""
        logger.info("[TagMemoEngine] Shutting down...")

        # 取消定时器
        if self._cache_cleanup_task:
            self._cache_cleanup_task.cancel()
            try:
                await self._cache_cleanup_task
            except asyncio.CancelledError:
                pass
            self._cache_cleanup_task = None

        # 取消 rag_params watcher
        if self._rag_params_watcher_task:
            self._rag_params_watcher_task.cancel()
            try:
                await self._rag_params_watcher_task
            except asyncio.CancelledError:
                pass
            self._rag_params_watcher_task = None

        # 关闭知识库
        if self.knowledge_base:
            await self.knowledge_base.shutdown()

        # 清空缓存
        self.query_cache.clear()
        logger.info("[TagMemoEngine] Shutdown complete.")
