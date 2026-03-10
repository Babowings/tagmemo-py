"""knowledge_base.py — 知识库管理器，替代 KnowledgeBaseManager.js (925 行)。

核心职责：
- 多路向量索引管理（1 全局 tagIndex + N diary chunkIndex）
- SQLite CRUD（better-sqlite3 → sqlite3，同步模型）
- 文件监听 + 批量 ingestion（chokidar → watchdog + 手动启动扫描）
- TagBoost V3.7 核心算法
- Tag 共现矩阵构建
- 延迟索引保存（threading.Timer）
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

import numpy as np

from .embedding_utils import get_embeddings_batch
from .epa import EPAModule
from .path_utils import resolve_project_path
from .residual_pyramid import ResidualPyramid
from .result_deduplicator import ResultDeduplicator
from .text_chunker import chunk_text
from .vector_index import VectorIndex

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 装饰性 Emoji（轻量清理，比 TextSanitizer 更简单）
# ------------------------------------------------------------------
_DECORATIVE_EMOJI_RE = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    r"\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
    r"\u2600-\u26FF\u2700-\u27BF]"
)


class KnowledgeBaseManager:
    """多路索引 + TagBoost V3.7 + EPA + Residual Pyramid，1:1 对应原 JS 版 KBM。"""

    # =================================================================
    # 构造 & 初始化
    # =================================================================

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}

        self.config = {
            "root_path":       resolve_project_path(cfg.get("root_path") or os.environ.get("KNOWLEDGEBASE_ROOT_PATH", ""), "data/dailynote"),
            "store_path":      resolve_project_path(cfg.get("store_path") or os.environ.get("KNOWLEDGEBASE_STORE_PATH", ""), "VectorStore"),
            "api_key":         cfg.get("api_key",         os.environ.get("API_Key", "")),
            "api_url":         cfg.get("api_url",         os.environ.get("API_URL", "")),
            "model":           cfg.get("model",           os.environ.get("WhitelistEmbeddingModel", "text-embedding-3-small")),
            "dimension":       int(cfg.get("dimension",   os.environ.get("VECTORDB_DIMENSION", "3072"))),

            "batch_window":     int(os.environ.get("KNOWLEDGEBASE_BATCH_WINDOW_MS", "2000")) / 1000.0,
            "max_batch_size":   int(os.environ.get("KNOWLEDGEBASE_MAX_BATCH_SIZE", "50")),
            "index_save_delay": int(os.environ.get("KNOWLEDGEBASE_INDEX_SAVE_DELAY", "120000")) / 1000.0,
            "tag_index_save_delay": int(os.environ.get("KNOWLEDGEBASE_TAG_INDEX_SAVE_DELAY", "300000")) / 1000.0,
            "index_idle_ttl": int(os.environ.get("KNOWLEDGEBASE_INDEX_IDLE_TTL_MS", "7200000")) / 1000.0,
            "index_idle_sweep_interval": int(os.environ.get("KNOWLEDGEBASE_INDEX_IDLE_SWEEP_MS", "600000")) / 1000.0,

            "ignore_folders":  [f.strip() for f in os.environ.get("IGNORE_FOLDERS", "").split(",") if f.strip()],
            "ignore_prefixes": [p.strip() for p in os.environ.get("IGNORE_PREFIXES", "").split(",") if p.strip()],
            "ignore_suffixes": [s.strip() for s in os.environ.get("IGNORE_SUFFIXES", "").split(",") if s.strip()],

            "tag_blacklist":       set(t.strip() for t in os.environ.get("TAG_BLACKLIST", "").split(",") if t.strip()),
            "tag_blacklist_super": [t.strip() for t in os.environ.get("TAG_BLACKLIST_SUPER", "").split(",") if t.strip()],
            "tag_expand_max_count": int(os.environ.get("TAG_EXPAND_MAX_COUNT", "30")),
            "full_scan_on_startup": os.environ.get("KNOWLEDGEBASE_FULL_SCAN_ON_STARTUP", "true").lower() == "true",

            "lang_confidence_enabled": os.environ.get("LANG_CONFIDENCE_GATING_ENABLED", "true").lower() == "true",
            "lang_penalty_unknown":    float(os.environ.get("LANG_PENALTY_UNKNOWN", "0.05")),
            "lang_penalty_cross_domain": float(os.environ.get("LANG_PENALTY_CROSS_DOMAIN", "0.1")),
        }
        # 合并用户传入的额外键
        for k, v in cfg.items():
            if k not in self.config:
                self.config[k] = v

        self.db: sqlite3.Connection | None = None
        self.diary_indices: dict[str, VectorIndex] = {}
        self.diary_index_last_used: dict[str, float] = {}
        self.tag_index: VectorIndex | None = None
        self.watcher = None  # watchdog.Observer
        self.initialized = False
        self.diary_name_vector_cache: dict[str, list[float]] = {}
        self.pending_files: set[str] = set()
        self.file_retry_count: dict[str, int] = {}
        self._batch_timer: threading.Timer | None = None
        self._is_processing = False
        self._save_timers: dict[str, threading.Timer] = {}
        self._idle_sweep_timer: threading.Timer | None = None
        self.tag_cooccurrence_matrix: dict[int, dict[int, int]] | None = None
        self.epa: EPAModule | None = None
        self.residual_pyramid: ResidualPyramid | None = None
        self.result_deduplicator: ResultDeduplicator | None = None
        self.rag_params: dict = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化数据库、索引、EPA、文件 watcher。"""
        if self.initialized:
            return
        dim = self.config["dimension"]
        logger.info("[KnowledgeBase] Initializing (Dim: %d)...", dim)

        os.makedirs(self.config["store_path"], exist_ok=True)
        os.makedirs(self.config["root_path"], exist_ok=True)

        db_path = os.path.join(self.config["store_path"], "knowledge_base.sqlite")
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

        # 全局 Tag 索引
        tag_idx_path = os.path.join(self.config["store_path"], "index_global_tags.usearch")
        tag_capacity = 50000
        try:
            if os.path.exists(tag_idx_path):
                self.tag_index = VectorIndex.load(
                    tag_idx_path, dim, tag_capacity,
                    db_path=db_path, table_type="tags",
                )
                logger.info("[KnowledgeBase] Tag index loaded.")
            else:
                self.tag_index = VectorIndex(dim, tag_capacity)
                self._recover_tags(db_path)
        except Exception:
            self.tag_index = VectorIndex(dim, tag_capacity)
            self._recover_tags(db_path)

        reconcile_result = self.reconcile_missing_files(dry_run=False)
        if reconcile_result.get("missing_files", 0) > 0:
            logger.warning(
                "[KnowledgeBase] Reconciled %d missing files from DB on startup.",
                reconcile_result.get("missing_files", 0),
            )

        self._hydrate_diary_name_cache()
        self._build_cooccurrence_matrix()

        # EPA / Pyramid / Dedup
        self.epa = EPAModule(self.db, {"dimension": dim, "vexus_index": self.tag_index})
        self.epa.initialize()

        self.residual_pyramid = ResidualPyramid(self.tag_index, self.db, {"dimension": dim})
        self.result_deduplicator = ResultDeduplicator(self.db, {"dimension": dim})

        self._start_watcher()
        await self.load_rag_params()
        self._start_idle_sweep()

        self.initialized = True
        logger.info("[KnowledgeBase] System Ready")

    # =================================================================
    # Schema
    # =================================================================

    def _init_schema(self) -> None:
        assert self.db is not None
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                diary_name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                mtime INTEGER NOT NULL,
                size INTEGER NOT NULL,
                updated_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                vector BLOB,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                vector BLOB
            );
            CREATE TABLE IF NOT EXISTS file_tags (
                file_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (file_id, tag_id),
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT,
                vector BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_files_diary ON files(diary_name);
            CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
            CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag_id);
            CREATE INDEX IF NOT EXISTS idx_file_tags_composite ON file_tags(tag_id, file_id);
        """)

    # =================================================================
    # RAG Params
    # =================================================================

    async def load_rag_params(self) -> None:
        import json
        params_path = os.path.join(
            str(Path(__file__).resolve().parent.parent), "rag_params.json"
        )
        try:
            with open(params_path, "r", encoding="utf-8") as f:
                self.rag_params = json.load(f)
            logger.info("[KnowledgeBase] RAG params loaded")
        except Exception:
            self.rag_params = {"KnowledgeBaseManager": {}}

    # =================================================================
    # Index Management
    # =================================================================

    def _get_or_load_diary_index(self, diary_name: str) -> VectorIndex:
        self.diary_index_last_used[diary_name] = time.time()
        if diary_name in self.diary_indices:
            return self.diary_indices[diary_name]
        safe_name = hashlib.md5(diary_name.encode()).hexdigest()
        idx = self._load_or_build_index(f"diary_{safe_name}", 50000, "chunks", diary_name)
        self.diary_indices[diary_name] = idx
        return idx

    def _start_idle_sweep(self) -> None:
        interval = float(self.config.get("index_idle_sweep_interval", 0) or 0)
        if interval <= 0 or self._idle_sweep_timer is not None:
            return

        def _run() -> None:
            self._idle_sweep_timer = None
            try:
                self._evict_idle_indices()
            finally:
                if self.db is not None:
                    self._start_idle_sweep()

        timer = threading.Timer(interval, _run)
        timer.daemon = True
        self._idle_sweep_timer = timer
        timer.start()

    def _evict_idle_indices(self, *, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        ttl = float(self.config.get("index_idle_ttl", 0) or 0)
        if ttl <= 0:
            return

        for diary_name, last_used in list(self.diary_index_last_used.items()):
            if current_time - last_used < ttl:
                continue
            if diary_name not in self.diary_indices:
                self.diary_index_last_used.pop(diary_name, None)
                continue

            timer = self._save_timers.pop(diary_name, None)
            if timer is not None:
                timer.cancel()

            self._save_index_to_disk(diary_name)
            self.diary_indices.pop(diary_name, None)
            self.diary_index_last_used.pop(diary_name, None)

    def _load_or_build_index(
        self, file_name: str, capacity: int, table_type: str, filter_diary: str | None = None,
    ) -> VectorIndex:
        dim = self.config["dimension"]
        idx_path = os.path.join(self.config["store_path"], f"index_{file_name}.usearch")
        db_path = os.path.join(self.config["store_path"], "knowledge_base.sqlite")
        try:
            if os.path.exists(idx_path):
                return VectorIndex.load(idx_path, dim, capacity, db_path=db_path, table_type=table_type)
            else:
                return VectorIndex(dim, capacity)
        except Exception:
            idx = VectorIndex(dim, capacity)
            idx.recover_from_sqlite(db_path, table_type, filter_diary_name=filter_diary)
            return idx

    def _recover_tags(self, db_path: str) -> None:
        """后台从 SQLite 恢复 Tag 索引。"""
        assert self.tag_index is not None
        try:
            count = self.tag_index.recover_from_sqlite(db_path, "tags")
            logger.info("[KnowledgeBase] Tag recovery complete: %d vectors", count)
            self._schedule_index_save("global_tags")
        except Exception as exc:
            logger.error("[KnowledgeBase] Tag recovery failed: %s", exc)

    def _hydrate_diary_name_cache(self) -> None:
        assert self.db is not None
        dim = self.config["dimension"]
        expected_bytes = dim * 4
        try:
            rows = self.db.execute(
                "SELECT key, vector FROM kv_store WHERE key LIKE 'diary_name:%'"
            ).fetchall()
            count = 0
            for key, blob in rows:
                name = key.split(":", 1)[1]
                if blob and len(blob) == expected_bytes:
                    vec = np.frombuffer(blob, dtype=np.float32).copy().tolist()
                    self.diary_name_vector_cache[name] = vec
                    count += 1
            if count:
                logger.info("[KnowledgeBase] Hydrated %d diary name vectors.", count)
        except Exception:
            pass

    # =================================================================
    # Search
    # =================================================================

    async def search(
        self,
        arg1,
        arg2=None,
        arg3: int = 5,
        arg4: float = 0.0,
        arg5: list[str] | None = None,
        arg6: float = 1.33,
    ) -> list[dict]:
        diary_name: str | None = None
        query_vec = None
        k = 5
        tag_boost = 0.0
        core_tags = arg5 or []
        core_boost_factor = arg6

        if isinstance(arg1, str) and isinstance(arg2, list):
            diary_name = arg1
            query_vec = arg2
            k = arg3 or 5
            tag_boost = arg4 or 0.0
            core_tags = arg5 or []
            core_boost_factor = arg6 or 1.33
        elif arg1 is None and isinstance(arg2, list):
            # search(None, vector, k, tag_boost, core_tags, coreBoostFactor)
            diary_name = None
            query_vec = arg2
            k = arg3 or 5
            tag_boost = arg4 or 0.0
            core_tags = arg5 or []
            core_boost_factor = arg6 or 1.33
        elif isinstance(arg1, str):
            return []
        elif isinstance(arg1, list):
            query_vec = arg1
            k = arg2 or 5
            tag_boost = arg3 or 0.0
            core_tags = arg4 or []
            core_boost_factor = arg5 or 1.33

        if not query_vec:
            return []
        try:
            if diary_name:
                return self._search_specific_index(diary_name, query_vec, k, tag_boost, core_tags, core_boost_factor)
            else:
                return self._search_all_indices(query_vec, k, tag_boost, core_tags, core_boost_factor)
        except Exception as exc:
            logger.error("[KnowledgeBase] Search Error: %s", exc)
            return []

    def _search_specific_index(
        self, diary_name: str, vector: list[float], k: int,
        tag_boost: float, core_tags: list[str], core_boost_factor: float = 1.33,
    ) -> list[dict]:
        assert self.db is not None
        idx = self._get_or_load_diary_index(diary_name)
        stats = idx.stats()
        if stats["total_vectors"] == 0:
            return []

        search_vec, tag_info = self._prepare_search_vector(vector, tag_boost, core_tags, core_boost_factor)
        if len(search_vec) != self.config["dimension"]:
            return []

        results = idx.search(search_vec, k)
        return self._hydrate_results(results, tag_info, with_updated_at=True)

    def _search_all_indices(
        self, vector: list[float], k: int, tag_boost: float, core_tags: list[str], core_boost_factor: float = 1.33,
    ) -> list[dict]:
        assert self.db is not None
        search_vec, tag_info = self._prepare_search_vector(vector, tag_boost, core_tags, core_boost_factor)

        all_diaries = self.db.execute("SELECT DISTINCT diary_name FROM files").fetchall()
        all_results: list[dict] = []
        for (diary_name,) in all_diaries:
            try:
                idx = self._get_or_load_diary_index(diary_name)
                all_results.extend(idx.search(search_vec, k))
            except Exception:
                continue

        all_results.sort(key=lambda r: r["score"], reverse=True)
        top_k = all_results[:k]
        return self._hydrate_results(top_k, tag_info, with_updated_at=False)

    def _prepare_search_vector(
        self, vector: list[float], tag_boost: float, core_tags: list[str], core_boost_factor: float = 1.33,
    ) -> tuple[np.ndarray, dict | None]:
        vec = np.array(vector, dtype=np.float32)
        tag_info: dict | None = None
        if tag_boost > 0:
            boost = self._apply_tag_boost_v3(vec, tag_boost, core_tags, core_boost_factor)
            vec = boost["vector"]
            tag_info = boost["info"]
        return vec, tag_info

    def _hydrate_results(
        self, results: list[dict], tag_info: dict | None, *, with_updated_at: bool,
    ) -> list[dict]:
        assert self.db is not None
        if not results:
            return []
        ids = [r["id"] for r in results]
        placeholders = ",".join("?" * len(ids))
        if with_updated_at:
            sql = f"""
                SELECT c.id, c.content AS text, f.path AS source_file, f.updated_at
                FROM chunks c JOIN files f ON c.file_id = f.id
                WHERE c.id IN ({placeholders})
            """
        else:
            sql = f"""
                SELECT c.id, c.content AS text, f.path AS source_file
                FROM chunks c JOIN files f ON c.file_id = f.id
                WHERE c.id IN ({placeholders})
            """
        cursor = self.db.execute(sql, ids)
        col_names = [d[0] for d in cursor.description]
        row_map: dict[int, dict] = {}
        for row in cursor.fetchall():
            row_dict = dict(zip(col_names, row))
            row_map[row_dict["id"]] = row_dict

        hydrated: list[dict] = []
        for r in results:
            row = row_map.get(r["id"])
            if not row:
                continue
            item: dict = {
                "text": row["text"],
                "score": r["score"],
                "sourceFile": os.path.basename(row["source_file"]),
                "matchedTags": tag_info["matched_tags"] if tag_info else [],
                "boostFactor": tag_info["boost_factor"] if tag_info else 0,
                "tagMatchScore": tag_info.get("totalSpikeScore", 0) if tag_info else 0,
                "tagMatchCount": len(tag_info["matched_tags"]) if tag_info else 0,
                "coreTagsMatched": tag_info["core_tags_matched"] if tag_info else [],
            }
            if r.get("vector") is not None:
                item["vector"] = r["vector"]
            if with_updated_at:
                item["fullPath"] = row["source_file"]
            if with_updated_at and "updated_at" in row:
                item["updated_at"] = row["updated_at"]
            hydrated.append(item)
        return hydrated

    # =================================================================
    # TagBoost V3.7
    # =================================================================

    def _apply_tag_boost_v3(
        self,
        vector: np.ndarray,
        base_tag_boost: float,
        core_tags: list[str],
        core_boost_factor: float = 1.33,
    ) -> dict:
        """TagMemo V3.7 核心算法 — 1:1 对应原 JS _applyTagBoostV3。"""
        assert self.db is not None and self.epa is not None and self.residual_pyramid is not None
        dim = self.config["dimension"]
        original = vector.astype(np.float32)

        try:
            epa_result = self.epa.project(original)
            resonance = self.epa.detect_cross_domain_resonance(original)
            query_world = (epa_result.get("dominant_axes") or [{}])[0].get("label", "Unknown")

            pyramid = self.residual_pyramid.analyze(original)
            features = pyramid.get("features", {})

            cfg = self.rag_params.get("KnowledgeBaseManager", {})
            logic_depth = epa_result.get("logic_depth", 0.5)
            entropy_penalty = epa_result.get("entropy", 0.5)
            resonance_boost = math.log(1 + resonance.get("resonance", 0))

            act_range = cfg.get("activationMultiplier", [0.5, 1.5])
            activation = act_range[0] + features.get("tag_memo_activation", 0.5) * (act_range[1] - act_range[0])
            dynamic_boost = (logic_depth * (1 + resonance_boost) / (1 + entropy_penalty * 0.5)) * activation

            boost_range = cfg.get("dynamicBoostRange", [0.3, 2.0])
            effective_tag_boost = base_tag_boost * max(boost_range[0], min(boost_range[1], dynamic_boost))

            core_metric = logic_depth * 0.5 + (1 - features.get("coverage", 0.5)) * 0.5
            core_range = cfg.get("coreBoostRange", [1.20, 1.40])
            dynamic_core_boost = core_range[0] + core_metric * (core_range[1] - core_range[0])

            logger.info(
                "[TagMemo] World=%s, Depth=%.3f, Resonance=%.3f, Coverage=%.3f",
                query_world, logic_depth, resonance.get("resonance", 0), features.get("coverage", 0),
            )

            # 收集金字塔 Tags
            all_tags: list[dict] = []
            seen_ids: set[int] = set()
            safe_core = [t for t in core_tags if isinstance(t, str)]
            core_tag_set = {t.lower() for t in safe_core}

            for level in (pyramid.get("levels") or []):
                for t in (level.get("tags") or []):
                    if not t or t.get("id") in seen_ids:
                        continue
                    tag_name = (t.get("name") or "").lower()
                    is_core = bool(tag_name and tag_name in core_tag_set)
                    individual_relevance = t.get("similarity", 0.5)
                    core_boost_val = (dynamic_core_boost * (0.95 + individual_relevance * 0.1)) if is_core else 1.0

                    lang_penalty = 1.0
                    if self.config["lang_confidence_enabled"]:
                        t_name = t.get("name", "")
                        is_tech_noise = (
                            not re.search(r"[\u4e00-\u9fa5]", t_name)
                            and bool(re.fullmatch(r"[A-Za-z0-9\-_.\s]+", t_name))
                            and len(t_name) > 3
                        )
                        is_tech_world = (
                            query_world != "Unknown"
                            and bool(re.fullmatch(r"[A-Za-z0-9\-_.]+", query_world))
                        )
                        if is_tech_noise and not is_tech_world:
                            is_social = bool(re.search(
                                r"Politics|Society|History|Economics|Culture", query_world, re.IGNORECASE
                            ))
                            comp = cfg.get("languageCompensator", {})
                            base_pen = (
                                comp.get("penaltyUnknown", self.config["lang_penalty_unknown"])
                                if query_world == "Unknown"
                                else comp.get("penaltyCrossDomain", self.config["lang_penalty_cross_domain"])
                            )
                            lang_penalty = math.sqrt(base_pen) if is_social else base_pen

                    layer_decay = 0.7 ** level.get("level", 0)
                    all_tags.append({
                        **t,
                        "adjusted_weight": (t.get("contribution") or t.get("weight") or 0) * layer_decay * lang_penalty * core_boost_val,
                        "is_core": is_core,
                    })
                    seen_ids.add(t["id"])

            # 共现拉回
            if all_tags and self.tag_cooccurrence_matrix:
                top_tags = all_tags[:5]
                for parent in top_tags:
                    related = self.tag_cooccurrence_matrix.get(parent["id"])
                    if not related:
                        continue
                    sorted_rel = sorted(related.items(), key=lambda x: x[1], reverse=True)[:4]
                    for rel_id, _ in sorted_rel:
                        if rel_id not in seen_ids:
                            all_tags.append({
                                "id": rel_id,
                                "adjusted_weight": parent["adjusted_weight"] * 0.5,
                                "is_pullback": True,
                            })
                            seen_ids.add(rel_id)

            # Core Tag 补全
            if core_tag_set:
                matched_names = {(t.get("name") or "").lower() for t in all_tags if t.get("name")}
                missing = [ct for ct in core_tag_set if ct not in matched_names]
                if missing:
                    try:
                        ph = ",".join("?" * len(missing))
                        rows = self.db.execute(
                            f"SELECT id, name, vector FROM tags WHERE name IN ({ph})", missing
                        ).fetchall()
                        max_base = max((t["adjusted_weight"] / 1.33 for t in all_tags), default=1.0)
                        for row_id, row_name, row_vec in rows:
                            if row_id not in seen_ids:
                                all_tags.append({
                                    "id": row_id, "name": row_name,
                                    "adjusted_weight": max_base * dynamic_core_boost,
                                    "is_core": True, "is_virtual": True,
                                })
                                seen_ids.add(row_id)
                    except Exception:
                        pass

            if not all_tags:
                return {"vector": original, "info": None}

            # 批量获取向量
            all_ids = [t["id"] for t in all_tags]
            ph = ",".join("?" * len(all_ids))
            tag_rows = self.db.execute(
                f"SELECT id, name, vector FROM tags WHERE id IN ({ph})", all_ids
            ).fetchall()
            tag_data: dict[int, dict] = {}
            for tid, tname, tvec in tag_rows:
                tag_data[tid] = {"id": tid, "name": tname, "vector": tvec}

            # 语义去重
            dedup_tags: list[dict] = []
            sorted_tags = sorted(all_tags, key=lambda t: t["adjusted_weight"], reverse=True)
            dedup_threshold = cfg.get("deduplicationThreshold", 0.88)

            for tag in sorted_tags:
                data = tag_data.get(tag["id"])
                if not data or not data["vector"]:
                    continue
                vec_a = np.frombuffer(data["vector"], dtype=np.float32).copy()
                is_redundant = False

                for existing in dedup_tags:
                    e_data = tag_data.get(existing["id"])
                    if not e_data or not e_data["vector"]:
                        continue
                    vec_b = np.frombuffer(e_data["vector"], dtype=np.float32).copy()
                    sim = float(np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b) + 1e-9))
                    if sim > dedup_threshold:
                        is_redundant = True
                        existing["adjusted_weight"] += tag["adjusted_weight"] * 0.2
                        if tag.get("is_core"):
                            existing["is_core"] = True
                        break

                if not is_redundant:
                    if not tag.get("name") and data.get("name"):
                        tag["name"] = data["name"]
                    dedup_tags.append(tag)

            # 构建上下文向量
            context_vec = np.zeros(dim, dtype=np.float64)
            total_weight = 0.0
            for t in dedup_tags:
                data = tag_data.get(t["id"])
                if data and data["vector"]:
                    v = np.frombuffer(data["vector"], dtype=np.float32).copy().astype(np.float64)
                    context_vec += v * t["adjusted_weight"]
                    total_weight += t["adjusted_weight"]

            if total_weight > 0:
                context_vec /= total_weight
                mag = np.linalg.norm(context_vec)
                if mag > 1e-9:
                    context_vec /= mag
            else:
                return {"vector": original, "info": None}

            # 融合
            alpha = min(1.0, effective_tag_boost)
            fused = ((1 - alpha) * original.astype(np.float64)
                     + alpha * context_vec)
            fused_mag = np.linalg.norm(fused)
            if fused_mag > 1e-9:
                fused /= fused_mag
            fused = fused.astype(np.float32)

            # 构建 matchedTags 列表
            def _build_matched_tags() -> list[str]:
                if not dedup_tags:
                    return []
                max_w = max(t["adjusted_weight"] for t in dedup_tags)
                result: list[str] = []
                tech_thresh = cfg.get("techTagThreshold", 0.08)
                normal_thresh = cfg.get("normalTagThreshold", 0.015)
                for t in dedup_tags:
                    if t.get("is_core"):
                        if t.get("name"):
                            result.append(t["name"])
                        continue
                    t_name = t.get("name", "")
                    is_tech = not re.search(r"[\u4e00-\u9fa5]", t_name) and bool(re.fullmatch(r"[A-Za-z0-9\-_.\s]+", t_name))
                    threshold = max_w * (tech_thresh if is_tech else normal_thresh)
                    if t["adjusted_weight"] > threshold and t_name:
                        result.append(t_name)
                return result

            return {
                "vector": fused,
                "info": {
                    "core_tags_matched": [t["name"] for t in dedup_tags if t.get("is_core") and t.get("name")],
                    "matched_tags": _build_matched_tags(),
                    "boost_factor": effective_tag_boost,
                    "epa": {"logicDepth": logic_depth, "entropy": entropy_penalty, "resonance": resonance.get("resonance", 0)},
                    "pyramid": {"coverage": features.get("coverage", 0), "novelty": features.get("novelty", 0), "depth": features.get("depth", 0)},
                    "totalSpikeScore": sum(t["adjusted_weight"] for t in dedup_tags),
                },
            }

        except Exception as exc:
            logger.error("[KnowledgeBase] TagMemo V3 CRITICAL FAIL: %s", exc)
            return {"vector": original, "info": None}

    # 公开 wrappers（供 Engine 调用）
    def apply_tag_boost(
        self,
        vector: list[float] | np.ndarray,
        tag_boost: float,
        core_tags: list[str] | None = None,
        core_boost_factor: float = 1.33,
    ) -> dict:
        vec = np.array(vector, dtype=np.float32) if not isinstance(vector, np.ndarray) else vector.astype(np.float32)
        return self._apply_tag_boost_v3(vec, tag_boost, core_tags or [], core_boost_factor)

    def get_epa_analysis(self, vector: list[float] | np.ndarray) -> dict:
        if not self.epa or not self.epa.initialized:
            return {"logicDepth": 0.5, "resonance": 0, "entropy": 0.5, "dominantAxes": []}
        vec = np.array(vector, dtype=np.float32) if not isinstance(vector, np.ndarray) else vector.astype(np.float32)
        projection = self.epa.project(vec)
        resonance_result = self.epa.detect_cross_domain_resonance(vec)
        return {
            "logicDepth": projection.get("logic_depth", 0.5),
            "entropy": projection.get("entropy", 0.5),
            "resonance": resonance_result.get("resonance", 0),
            "dominantAxes": projection.get("dominant_axes", []),
        }

    async def deduplicate_results(self, candidates: list[dict], query_vector: list[float]) -> list[dict]:
        if not self.result_deduplicator:
            return candidates
        return self.result_deduplicator.deduplicate(candidates, query_vector)

    def get_diary_name_vector(self, diary_name: str) -> list[float] | None:
        return self.diary_name_vector_cache.get(diary_name)

    def get_vector_by_text(self, diary_name: str, text: str) -> list[float] | None:
        if self.db is None or not diary_name or not text:
            return None
        row = self.db.execute(
            """
            SELECT c.vector
            FROM chunks c
            JOIN files f ON c.file_id = f.id
            WHERE f.diary_name = ? AND c.content = ?
            LIMIT 1
            """,
            (diary_name, text),
        ).fetchone()
        if not row or not row[0]:
            return None
        return np.frombuffer(row[0], dtype=np.float32).copy().tolist()

    async def get_plugin_description_vector(
        self,
        desc_text: str,
        get_embedding_fn: Callable[[str], Awaitable[list[float] | None]] | None,
    ) -> list[float] | None:
        if self.db is None or not desc_text:
            return None

        key = f"plugin_desc_hash:{hashlib.sha256(desc_text.encode('utf-8')).hexdigest()}"
        expected_bytes = int(self.config.get("dimension", 0) or 0) * 4

        try:
            row = self.db.execute(
                "SELECT vector FROM kv_store WHERE key = ?",
                (key,),
            ).fetchone()
            if row and row[0] and expected_bytes and len(row[0]) == expected_bytes:
                return np.frombuffer(row[0], dtype=np.float32).copy().tolist()
        except Exception as exc:
            logger.warning("[KnowledgeBase] Plugin description cache read failed: %s", exc)

        if not callable(get_embedding_fn):
            return None

        try:
            vec = await get_embedding_fn(desc_text)
            if not vec:
                return None
            self.db.execute(
                "INSERT OR REPLACE INTO kv_store (key, vector) VALUES (?, ?)",
                (key, np.array(vec, dtype=np.float32).tobytes()),
            )
            self.db.commit()
            return vec
        except Exception as exc:
            logger.warning("[KnowledgeBase] Plugin description cache write failed: %s", exc)
            return None

    def get_chunks_by_file_paths(self, file_paths: list[str]) -> list[dict]:
        if self.db is None or not file_paths:
            return []

        normalized_paths = [self._normalize_rel_path(path) for path in file_paths if path]
        normalized_paths = list(dict.fromkeys(normalized_paths))
        if not normalized_paths:
            return []

        batch_size = 500
        dim = int(self.config.get("dimension", 0) or 0)
        expected_bytes = dim * 4 if dim > 0 else 0
        all_rows: list[dict] = []

        for start in range(0, len(normalized_paths), batch_size):
            batch = normalized_paths[start:start + batch_size]
            placeholders = self._make_placeholders(len(batch))
            rows = self.db.execute(
                f"""
                SELECT c.id, c.content, c.vector, f.path
                FROM chunks c
                JOIN files f ON c.file_id = f.id
                WHERE f.path IN ({placeholders})
                ORDER BY f.path, c.chunk_index
                """,
                tuple(batch),
            ).fetchall()
            for chunk_id, content, vector_blob, path in rows:
                vector = None
                if vector_blob and expected_bytes and len(vector_blob) == expected_bytes:
                    vector = np.frombuffer(vector_blob, dtype=np.float32).copy().tolist()
                all_rows.append(
                    {
                        "id": int(chunk_id),
                        "text": str(content),
                        "vector": vector,
                        "sourceFile": str(path),
                    }
                )

        return all_rows

    # =================================================================
    # File Watching & Ingestion
    # =================================================================

    def _start_watcher(self) -> None:
        """启动文件监听。watchdog 无 ignoreInitial，手动启动扫描。"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            kbm = self

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory:
                        kbm._on_file_event(event.src_path)

                def on_modified(self, event):
                    if not event.is_directory:
                        kbm._on_file_event(event.src_path)

                def on_deleted(self, event):
                    if not event.is_directory:
                        kbm._handle_delete(event.src_path)

            # 手动启动扫描（replacenaces chokidar ignoreInitial: false）
            if self.config["full_scan_on_startup"]:
                for root, _dirs, files in os.walk(self.config["root_path"]):
                    for fname in files:
                        if fname.lower().endswith((".md", ".txt")):
                            self._on_file_event(os.path.join(root, fname))

            observer = Observer()
            observer.schedule(_Handler(), self.config["root_path"], recursive=True)
            observer.daemon = True
            observer.start()
            self.watcher = observer
        except ImportError:
            logger.warning("[KnowledgeBase] watchdog not installed, file monitoring disabled.")

    def _on_file_event(self, file_path: str) -> None:
        """过滤 + 加入 pending 队列。"""
        if not re.search(r"\.(md|txt)$", file_path, re.IGNORECASE):
            return
        rel_path = os.path.relpath(file_path, self.config["root_path"])
        parts = rel_path.replace("\\", "/").split("/")
        diary_name = parts[0] if len(parts) > 1 else "Root"
        if diary_name in self.config["ignore_folders"]:
            return
        fname = os.path.basename(rel_path)
        if any(fname.startswith(p) for p in self.config["ignore_prefixes"]):
            return
        if any(fname.endswith(s) for s in self.config["ignore_suffixes"]):
            return

        with self._lock:
            self.pending_files.add(file_path)
            if len(self.pending_files) >= self.config["max_batch_size"]:
                self._flush_batch_async()
            else:
                self._schedule_batch()

    def _schedule_batch(self) -> None:
        if self._batch_timer is not None:
            self._batch_timer.cancel()
        self._batch_timer = threading.Timer(self.config["batch_window"], self._flush_batch_async)
        self._batch_timer.daemon = True
        self._batch_timer.start()

    def _flush_batch_async(self) -> None:
        """在新线程中调用异步 _flush_batch。"""
        import asyncio
        threading.Thread(target=lambda: asyncio.run(self._flush_batch()), daemon=True).start()

    async def _flush_batch(self) -> None:
        if self._is_processing:
            return
        with self._lock:
            if not self.pending_files:
                return
            batch_files = list(self.pending_files)[:self.config["max_batch_size"]]
            if self._batch_timer:
                self._batch_timer.cancel()
                self._batch_timer = None
        self._is_processing = True
        logger.info("[KnowledgeBase] Processing %d files...", len(batch_files))

        try:
            assert self.db is not None
            docs_by_diary: dict[str, list[dict]] = {}

            for file_path in batch_files:
                try:
                    stat = os.stat(file_path)
                    rel_path = os.path.relpath(file_path, self.config["root_path"]).replace("\\", "/")
                    parts = rel_path.split("/")
                    diary_name = parts[0] if len(parts) > 1 else "Root"

                    row = self.db.execute(
                        "SELECT checksum, mtime, size FROM files WHERE path = ?", (rel_path,)
                    ).fetchone()

                    if row and row[1] == stat.st_mtime_ns / 1_000_000 and row[2] == stat.st_size:
                        continue

                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    checksum = hashlib.md5(content.encode()).hexdigest()
                    if row and row[0] == checksum:
                        self.db.execute(
                            "UPDATE files SET mtime = ?, size = ? WHERE path = ?",
                            (stat.st_mtime_ns / 1_000_000, stat.st_size, rel_path),
                        )
                        self.db.commit()
                        continue

                    docs_by_diary.setdefault(diary_name, []).append({
                        "rel_path": rel_path,
                        "diary_name": diary_name,
                        "checksum": checksum,
                        "mtime": stat.st_mtime_ns / 1_000_000,
                        "size": stat.st_size,
                        "chunks": chunk_text(content),
                        "tags": self._extract_tags(content),
                    })
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning("Read error %s: %s", file_path, exc)

            if not docs_by_diary:
                with self._lock:
                    for f in batch_files:
                        self.pending_files.discard(f)
                        self.file_retry_count.pop(f, None)
                self._is_processing = False
                return

            # 收集所有 chunk 文本 + 需要向量化的新 Tag
            all_chunks_meta: list[dict] = []
            unique_tags: set[str] = set()
            for d_name, docs in docs_by_diary.items():
                for doc in docs:
                    valid_chunks = [self._prepare_text(c) for c in doc["chunks"]]
                    valid_chunks = [c for c in valid_chunks if c != "[EMPTY_CONTENT]"]
                    doc["chunks"] = valid_chunks
                    for ci, txt in enumerate(valid_chunks):
                        all_chunks_meta.append({"text": txt, "diary_name": d_name, "doc": doc, "chunk_idx": ci})
                    unique_tags.update(doc["tags"])

            new_tags_set: set[str] = set()
            tag_cache: dict[str, dict] = {}
            for t in unique_tags:
                row = self.db.execute("SELECT id, vector FROM tags WHERE name = ?", (t,)).fetchone()
                if row and row[1]:
                    tag_cache[t] = {"id": row[0], "vector": row[1]}
                else:
                    cleaned = self._prepare_text(t)
                    if cleaned != "[EMPTY_CONTENT]":
                        new_tags_set.add(cleaned)

            embed_cfg = {"api_key": self.config["api_key"], "api_url": self.config["api_url"], "model": self.config["model"]}

            chunk_vectors: list[list[float] | None] = []
            if all_chunks_meta:
                chunk_vectors = await get_embeddings_batch([m["text"] for m in all_chunks_meta], embed_cfg)

            new_tags = list(new_tags_set)
            tag_vectors: list[list[float] | None] = []
            if new_tags:
                for i in range(0, len(new_tags), 100):
                    tag_vectors.extend(await get_embeddings_batch(new_tags[i:i + 100], embed_cfg))

            # ---- 事务内只做 SQLite 操作 ----
            updates: dict[str, list[dict]] = {}
            tag_updates: list[dict] = []
            deletions: dict[str, list[int]] = {}

            with self.db:
                # 插入新 Tag
                for i, t in enumerate(new_tags):
                    if i >= len(tag_vectors) or tag_vectors[i] is None:
                        break
                    vec_bytes = np.array(tag_vectors[i], dtype=np.float32).tobytes()
                    self.db.execute("INSERT OR IGNORE INTO tags (name, vector) VALUES (?, ?)", (t, vec_bytes))
                    self.db.execute("UPDATE tags SET vector = ? WHERE name = ?", (vec_bytes, t))
                    row = self.db.execute("SELECT id FROM tags WHERE name = ?", (t,)).fetchone()
                    if row:
                        tag_cache[t] = {"id": row[0], "vector": vec_bytes}
                        tag_updates.append({"id": row[0], "vec": vec_bytes})

                # 关联向量到 chunks_meta
                meta_map: dict[tuple[str, int], dict] = {}
                for idx_i, meta in enumerate(all_chunks_meta):
                    meta["vector"] = chunk_vectors[idx_i] if idx_i < len(chunk_vectors) else None
                    meta_map[(meta["doc"]["rel_path"], meta["chunk_idx"])] = meta

                # 处理各 diary 的文档
                for d_name, docs in docs_by_diary.items():
                    updates.setdefault(d_name, [])
                    for doc in docs:
                        f_row = self.db.execute("SELECT id FROM files WHERE path = ?", (doc["rel_path"],)).fetchone()
                        now = int(time.time())
                        if f_row:
                            file_id = f_row[0]
                            old_chunks = self.db.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,)).fetchall()
                            if old_chunks:
                                deletions.setdefault(d_name, []).extend(c[0] for c in old_chunks)
                            self.db.execute(
                                "UPDATE files SET checksum=?, mtime=?, size=?, updated_at=? WHERE id=?",
                                (doc["checksum"], doc["mtime"], doc["size"], now, file_id),
                            )
                            self.db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
                            self.db.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
                        else:
                            cursor = self.db.execute(
                                "INSERT INTO files (path, diary_name, checksum, mtime, size, updated_at) VALUES (?,?,?,?,?,?)",
                                (doc["rel_path"], doc["diary_name"], doc["checksum"], doc["mtime"], doc["size"], now),
                            )
                            file_id = cursor.lastrowid

                        for ci, txt in enumerate(doc["chunks"]):
                            meta = meta_map.get((doc["rel_path"], ci))
                            if meta and meta.get("vector"):
                                vec_bytes = np.array(meta["vector"], dtype=np.float32).tobytes()
                                cur = self.db.execute(
                                    "INSERT INTO chunks (file_id, chunk_index, content, vector) VALUES (?,?,?,?)",
                                    (file_id, ci, txt, vec_bytes),
                                )
                                updates[d_name].append({"id": cur.lastrowid, "vec": vec_bytes})

                        for t in doc["tags"]:
                            t_info = tag_cache.get(t)
                            if t_info:
                                self.db.execute(
                                    "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?,?)",
                                    (file_id, t_info["id"]),
                                )

            # ---- 事务外操作索引（与原版保持相同边界） ----
            # 删除旧 chunk 向量
            for d_name, chunk_ids in deletions.items():
                idx = self._get_or_load_diary_index(d_name)
                for cid in chunk_ids:
                    try:
                        idx.remove(cid)
                    except Exception:
                        pass

            # 更新 Tag 索引
            assert self.tag_index is not None
            for u in tag_updates:
                try:
                    self.tag_index.add(u["id"], np.frombuffer(u["vec"], dtype=np.float32).copy())
                except Exception as exc:
                    if "Duplicate" in str(exc) or "already" in str(exc).lower():
                        try:
                            self.tag_index.remove(u["id"])
                            self.tag_index.add(u["id"], np.frombuffer(u["vec"], dtype=np.float32).copy())
                        except Exception:
                            pass
            self._schedule_index_save("global_tags")

            # 更新 diary 索引
            for d_name, chunks in updates.items():
                idx = self._get_or_load_diary_index(d_name)
                for u in chunks:
                    try:
                        idx.add(u["id"], np.frombuffer(u["vec"], dtype=np.float32).copy())
                    except Exception as exc:
                        if "Duplicate" in str(exc) or "already" in str(exc).lower():
                            try:
                                idx.remove(u["id"])
                                idx.add(u["id"], np.frombuffer(u["vec"], dtype=np.float32).copy())
                            except Exception:
                                pass
                self._schedule_index_save(d_name)

            logger.info("[KnowledgeBase] Batch complete. Updated %d diary indices.", len(updates))
            self._build_cooccurrence_matrix()

            with self._lock:
                for f in batch_files:
                    self.pending_files.discard(f)
                    self.file_retry_count.pop(f, None)

        except Exception as exc:
            logger.error("[KnowledgeBase] Batch failed: %s", exc)
            with self._lock:
                max_file_retries = 3
                for f in batch_files:
                    count = self.file_retry_count.get(f, 0) + 1
                    if count >= max_file_retries:
                        self.pending_files.discard(f)
                        self.file_retry_count.pop(f, None)
                    else:
                        self.pending_files.add(f)
                        self.file_retry_count[f] = count
        finally:
            self._is_processing = False
            with self._lock:
                if self.pending_files:
                    self._flush_batch_async()

    # =================================================================
    # Helpers
    # =================================================================

    @staticmethod
    def _prepare_text(text: str) -> str:
        """装饰性 Emoji 清理 + 空白规范化。"""
        cleaned = _DECORATIVE_EMOJI_RE.sub(" ", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r" *\n *", "\n", cleaned)
        cleaned = re.sub(r"\n{2,}", "\n", cleaned)
        cleaned = cleaned.strip()
        return cleaned if cleaned else "[EMPTY_CONTENT]"

    def _extract_tags(self, content: str) -> list[str]:
        tag_lines = re.findall(r"Tag:\s*(.+)$", content, re.IGNORECASE | re.MULTILINE)
        if not tag_lines:
            return []
        all_tags: list[str] = []
        for line in tag_lines:
            all_tags.extend(
                t.strip() for t in re.split(r"[,，、;|｜]", line) if t.strip()
            )
        tags = [self._prepare_text(t.rstrip("。.").strip()) for t in all_tags]
        tags = [t for t in tags if t != "[EMPTY_CONTENT]"]

        if self.config["tag_blacklist_super"]:
            super_re = re.compile("|".join(re.escape(p) for p in self.config["tag_blacklist_super"]))
            tags = [super_re.sub("", t).strip() for t in tags]

        tags = [t for t in tags if t and t not in self.config["tag_blacklist"]]
        return list(dict.fromkeys(tags))  # 去重保序

    @staticmethod
    def _make_placeholders(count: int) -> str:
        return ",".join("?" for _ in range(count))

    def _normalize_rel_path(self, file_path: str) -> str:
        normalized_input = str(file_path).replace("\\", "/")
        root = Path(self.config["root_path"]).resolve()
        input_path = Path(normalized_input)
        if input_path.is_absolute():
            try:
                return str(input_path.resolve().relative_to(root)).replace("\\", "/")
            except ValueError:
                return normalized_input.lstrip("/")
        return normalized_input.lstrip("/")

    def reconcile_missing_files(self, dry_run: bool = False) -> dict:
        if self.db is None:
            return {
                "dry_run": dry_run,
                "missing_files": 0,
                "target_files": [],
                "deleted_files": 0,
            }

        rows = self.db.execute("SELECT path FROM files").fetchall()
        root = Path(self.config["root_path"]).resolve()
        missing_paths: list[str] = []

        for row in rows:
            rel = str(row[0]).replace("\\", "/")
            target = (root / rel).resolve()
            if not target.exists() or target.is_dir() or root not in target.parents:
                missing_paths.append(rel)

        missing_paths = list(dict.fromkeys(missing_paths))
        if not missing_paths:
            return {
                "dry_run": dry_run,
                "missing_files": 0,
                "target_files": [],
                "deleted_files": 0,
            }

        if dry_run:
            return {
                "dry_run": True,
                "missing_files": len(missing_paths),
                "target_files": missing_paths,
                "deleted_files": 0,
            }

        deletion = self.delete_memories(file_paths=missing_paths, dry_run=False, cleanup_orphans=True)
        return {
            "dry_run": False,
            "missing_files": len(missing_paths),
            "target_files": missing_paths,
            "deleted_files": int(deletion.get("deleted_files", 0)),
        }

    def delete_memories(
        self,
        file_paths: list[str] | None = None,
        diary_name: str | None = None,
        dry_run: bool = False,
        cleanup_orphans: bool = True,
    ) -> dict:
        if self.db is None:
            return {
                "dry_run": dry_run,
                "matched_files": 0,
                "deleted_files": 0,
                "deleted_chunks": 0,
                "deleted_file_tags": 0,
                "deleted_tags": 0,
                "target_files": [],
                "touched_diaries": [],
            }

        normalized_paths = [self._normalize_rel_path(p) for p in (file_paths or []) if p]
        normalized_paths = list(dict.fromkeys(normalized_paths))
        conditions: list[str] = []
        params: list = []
        if normalized_paths:
            placeholders = self._make_placeholders(len(normalized_paths))
            conditions.append(f"path IN ({placeholders})")
            params.extend(normalized_paths)
        if diary_name:
            conditions.append("diary_name = ?")
            params.append(diary_name)
        if not conditions:
            raise ValueError("At least one of file_paths or diary_name is required")

        where_clause = " OR ".join(f"({c})" for c in conditions)
        target_rows = self.db.execute(
            f"SELECT id, path, diary_name FROM files WHERE {where_clause}",
            tuple(params),
        ).fetchall()

        if not target_rows:
            return {
                "dry_run": dry_run,
                "matched_files": 0,
                "deleted_files": 0,
                "deleted_chunks": 0,
                "deleted_file_tags": 0,
                "deleted_tags": 0,
                "target_files": [],
                "touched_diaries": [],
            }

        file_ids = [int(r[0]) for r in target_rows]
        target_files = [str(r[1]) for r in target_rows]
        file_diary_map = {int(r[0]): str(r[2]) for r in target_rows}
        touched_diaries = sorted(set(file_diary_map.values()))

        placeholders_ids = self._make_placeholders(len(file_ids))
        chunk_rows = self.db.execute(
            f"SELECT id, file_id FROM chunks WHERE file_id IN ({placeholders_ids})",
            tuple(file_ids),
        ).fetchall()
        chunk_ids_by_diary: dict[str, list[int]] = {}
        for chunk_id, file_id in chunk_rows:
            d_name = file_diary_map.get(int(file_id))
            if d_name:
                chunk_ids_by_diary.setdefault(d_name, []).append(int(chunk_id))

        file_tag_count = self.db.execute(
            f"SELECT COUNT(*) FROM file_tags WHERE file_id IN ({placeholders_ids})",
            tuple(file_ids),
        ).fetchone()[0]

        if dry_run:
            return {
                "dry_run": True,
                "matched_files": len(file_ids),
                "matched_chunks": len(chunk_rows),
                "matched_file_tags": int(file_tag_count),
                "target_files": target_files,
                "touched_diaries": touched_diaries,
            }

        deleted_chunks = 0
        deleted_file_tags = 0
        deleted_files = 0
        orphan_tag_ids: list[int] = []
        deleted_tags = 0

        with self.db:
            deleted_chunks = self.db.execute(
                f"DELETE FROM chunks WHERE file_id IN ({placeholders_ids})",
                tuple(file_ids),
            ).rowcount
            deleted_file_tags = self.db.execute(
                f"DELETE FROM file_tags WHERE file_id IN ({placeholders_ids})",
                tuple(file_ids),
            ).rowcount
            deleted_files = self.db.execute(
                f"DELETE FROM files WHERE id IN ({placeholders_ids})",
                tuple(file_ids),
            ).rowcount

            if cleanup_orphans:
                orphan_rows = self.db.execute(
                    "SELECT id FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM file_tags)"
                ).fetchall()
                orphan_tag_ids = [int(r[0]) for r in orphan_rows]
                if orphan_tag_ids:
                    placeholders_tags = self._make_placeholders(len(orphan_tag_ids))
                    deleted_tags = self.db.execute(
                        f"DELETE FROM tags WHERE id IN ({placeholders_tags})",
                        tuple(orphan_tag_ids),
                    ).rowcount

        for d_name, chunk_ids in chunk_ids_by_diary.items():
            idx = self._get_or_load_diary_index(d_name)
            for cid in chunk_ids:
                try:
                    idx.remove(cid)
                except Exception:
                    pass
            self._schedule_index_save(d_name)

        if cleanup_orphans and orphan_tag_ids and self.tag_index is not None:
            for tag_id in orphan_tag_ids:
                try:
                    self.tag_index.remove(tag_id)
                except Exception:
                    pass
            self._schedule_index_save("global_tags")

        self._build_cooccurrence_matrix()
        return {
            "dry_run": False,
            "matched_files": len(file_ids),
            "deleted_files": int(deleted_files),
            "deleted_chunks": int(deleted_chunks),
            "deleted_file_tags": int(deleted_file_tags),
            "deleted_tags": int(deleted_tags),
            "target_files": target_files,
            "touched_diaries": touched_diaries,
        }

    def _handle_delete(self, file_path: str) -> None:
        if self.db is None:
            return
        try:
            rel_path = os.path.relpath(file_path, self.config["root_path"]).replace("\\", "/")
            self.delete_memories(file_paths=[rel_path], cleanup_orphans=True)
        except Exception:
            pass

    def _schedule_index_save(self, name: str) -> None:
        if name in self._save_timers:
            return
        delay = self.config["tag_index_save_delay"] if name == "global_tags" else self.config["index_save_delay"]

        def _do_save():
            self._save_index_to_disk(name)
            self._save_timers.pop(name, None)

        timer = threading.Timer(delay, _do_save)
        timer.daemon = True
        self._save_timers[name] = timer
        timer.start()

    def _save_index_to_disk(self, name: str) -> None:
        try:
            if name == "global_tags":
                assert self.tag_index is not None
                self.tag_index.save(os.path.join(self.config["store_path"], "index_global_tags.usearch"))
            else:
                safe = hashlib.md5(name.encode()).hexdigest()
                idx = self.diary_indices.get(name)
                if idx:
                    idx.save(os.path.join(self.config["store_path"], f"index_diary_{safe}.usearch"))
        except Exception as exc:
            logger.error("[KnowledgeBase] Save failed for %s: %s", name, exc)

    def _build_cooccurrence_matrix(self) -> None:
        if self.db is None:
            return
        try:
            rows = self.db.execute("""
                SELECT ft1.tag_id AS tag1, ft2.tag_id AS tag2, COUNT(ft1.file_id) AS weight
                FROM file_tags ft1
                JOIN file_tags ft2 ON ft1.file_id = ft2.file_id AND ft1.tag_id < ft2.tag_id
                GROUP BY ft1.tag_id, ft2.tag_id
            """).fetchall()
            matrix: dict[int, dict[int, int]] = {}
            for tag1, tag2, weight in rows:
                matrix.setdefault(tag1, {})[tag2] = weight
                matrix.setdefault(tag2, {})[tag1] = weight
            self.tag_cooccurrence_matrix = matrix
        except Exception:
            self.tag_cooccurrence_matrix = {}

    # =================================================================
    # Shutdown
    # =================================================================

    async def shutdown(self) -> None:
        logger.info("[KnowledgeBase] Shutting down...")
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        if self._idle_sweep_timer:
            self._idle_sweep_timer.cancel()
            self._idle_sweep_timer = None
        for name, timer in list(self._save_timers.items()):
            timer.cancel()
            self._save_index_to_disk(name)
        self._save_timers.clear()
        if self.db:
            self.db.close()
            self.db = None
        logger.info("[KnowledgeBase] Shutdown complete.")
