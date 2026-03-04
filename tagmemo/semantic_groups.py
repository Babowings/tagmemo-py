"""semantic_groups.py — 语义组管理器，替代 SemanticGroupManager.js (306 行)。

功能：
- 词元激活 + 组向量预计算 + 查询增强
- .edit.json 同步机制（智能合并）
- 向量缓存目录管理（JSON 文件）
- 原子写入（temp + os.replace）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Callable, Awaitable

import numpy as np

logger = logging.getLogger(__name__)


class SemanticGroupManager:
    """语义组管理器，1:1 对应原 JS SemanticGroupManager。"""

    def __init__(
        self,
        embed_fn: Callable[[str], Awaitable[list[float] | None]],
        data_dir: str | None = None,
    ) -> None:
        if not embed_fn:
            raise ValueError("SemanticGroupManager requires embed_fn")
        self.embed_fn = embed_fn
        self.data_dir = data_dir or os.path.join(
            str(Path(__file__).resolve().parent.parent), "data", "semantic_groups"
        )
        self.groups: dict[str, dict] = {}
        self.config: dict = {}
        self.group_vector_cache: dict[str, list[float]] = {}
        self._save_lock = False

        self.groups_file_path = os.path.join(self.data_dir, "semantic_groups.json")
        self.vectors_dir_path = os.path.join(self.data_dir, "semantic_vectors")
        self.edit_file_path = os.path.join(self.data_dir, "semantic_groups.edit.json")

    # =================================================================
    # Initialize
    # =================================================================

    async def initialize(self) -> None:
        os.makedirs(self.vectors_dir_path, exist_ok=True)
        self._synchronize_from_edit_file()
        await self._load_groups()

    # =================================================================
    # Edit File Sync
    # =================================================================

    def _synchronize_from_edit_file(self) -> None:
        try:
            with open(self.edit_file_path, "r", encoding="utf-8") as f:
                edit_data = json.load(f)
            logger.info("[SemanticGroup] 发现 .edit.json 文件，开始同步...")
        except (FileNotFoundError, json.JSONDecodeError):
            return
        except Exception as exc:
            logger.error("[SemanticGroup] 同步 .edit.json 失败: %s", exc)
            return

        main_data: dict | None = None
        try:
            with open(self.groups_file_path, "r", encoding="utf-8") as f:
                main_data = json.load(f)
        except FileNotFoundError:
            pass
        except Exception as exc:
            raise exc

        if self._are_core_different(edit_data, main_data):
            logger.info("[SemanticGroup] .edit.json 与主文件核心内容不同，执行智能合并...")
            merged = self._merge_group_data(edit_data, main_data)
            with open(self.groups_file_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            logger.info("[SemanticGroup] 同步完成。")
        else:
            logger.info("[SemanticGroup] .edit.json 与主文件内容相同，无需同步。")

    @staticmethod
    def _are_core_different(edit_data: dict, main_data: dict | None) -> bool:
        if main_data is None:
            return True
        if json.dumps(edit_data.get("config", {}), sort_keys=True) != json.dumps(main_data.get("config", {}), sort_keys=True):
            return True
        eg = edit_data.get("groups", {})
        mg = main_data.get("groups", {})
        if set(eg.keys()) != set(mg.keys()):
            return True
        for name in eg:
            if name not in mg:
                return True
            e, m = eg[name], mg[name]
            if sorted(e.get("words", [])) != sorted(m.get("words", [])):
                return True
            if sorted(e.get("auto_learned", [])) != sorted(m.get("auto_learned", [])):
                return True
            if (e.get("weight", 1.0)) != (m.get("weight", 1.0)):
                return True
        return False

    @staticmethod
    def _merge_group_data(edit_data: dict, main_data: dict | None) -> dict:
        if main_data is None:
            return edit_data
        merged = json.loads(json.dumps(main_data))
        merged["config"] = edit_data.get("config", {})
        eg = edit_data.get("groups", {})
        new_groups: dict[str, dict] = {}
        for name, egroup in eg.items():
            existing = merged.get("groups", {}).get(name)
            if existing:
                existing["words"] = egroup.get("words", [])
                existing["auto_learned"] = egroup.get("auto_learned", [])
                existing["weight"] = egroup.get("weight", 1.0)
                new_groups[name] = existing
            else:
                new_groups[name] = egroup
        merged["groups"] = new_groups
        return merged

    # =================================================================
    # Load / Save
    # =================================================================

    async def _load_groups(self) -> None:
        try:
            with open(self.groups_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.config = data.get("config", {})
            self.groups = data.get("groups", {})
            logger.info("[SemanticGroup] 语义组配置加载成功。")

            needs_resave = False
            for group_name, group in list(self.groups.items()):
                if group.get("vector") and not group.get("vector_id"):
                    # 迁移内联向量 → 外部文件
                    vid = str(uuid.uuid4())
                    vec_path = os.path.join(self.vectors_dir_path, f"{vid}.json")
                    with open(vec_path, "w", encoding="utf-8") as vf:
                        json.dump(group["vector"], vf)
                    self.group_vector_cache[group_name] = group["vector"]
                    group["vector_id"] = vid
                    group.pop("vector", None)
                    needs_resave = True
                elif group.get("vector_id"):
                    try:
                        vec_path = os.path.join(self.vectors_dir_path, f"{group['vector_id']}.json")
                        with open(vec_path, "r", encoding="utf-8") as vf:
                            self.group_vector_cache[group_name] = json.load(vf)
                    except FileNotFoundError:
                        logger.error('[SemanticGroup] 组 "%s" 向量文件丢失 (ID: %s)', group_name, group["vector_id"])
                        del group["vector_id"]
                        needs_resave = True

            if needs_resave:
                self._save_groups()
            await self.precompute_group_vectors()

        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.error("[SemanticGroup] 加载语义组配置失败: %s", exc)

    def _save_groups(self) -> None:
        if self._save_lock:
            raise RuntimeError("Save already in progress")
        self._save_lock = True
        temp_path = f"{self.groups_file_path}.{uuid.uuid4()}.tmp"
        try:
            groups_copy = json.loads(json.dumps(self.groups))
            for g in groups_copy.values():
                g.pop("vector", None)
            data = {"config": self.config, "groups": groups_copy}
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.groups_file_path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        finally:
            self._save_lock = False

    async def update_groups_data(self, new_data: dict) -> None:
        old_groups = self.groups
        self.config = new_data.get("config", self.config)
        self.groups = new_data.get("groups", self.groups)

        # 清理孤立向量文件
        old_ids = {g.get("vector_id") for g in old_groups.values() if g.get("vector_id")}
        new_ids = {g.get("vector_id") for g in self.groups.values() if g.get("vector_id")}
        for vid in old_ids - new_ids:
            try:
                os.unlink(os.path.join(self.vectors_dir_path, f"{vid}.json"))
            except OSError:
                pass
        await self.precompute_group_vectors()

    # =================================================================
    # Core: Group Activation
    # =================================================================

    def detect_and_activate_groups(self, text: str) -> dict[str, dict]:
        activated: dict[str, dict] = {}
        for group_name, group_data in self.groups.items():
            all_words = list(group_data.get("words", [])) + list(group_data.get("auto_learned", []))
            matched = [w for w in all_words if self._flexible_match(text, w)]
            if matched:
                activated[group_name] = {
                    "strength": len(matched) / len(all_words) if all_words else 0,
                    "matched_words": matched,
                    "all_words": all_words,
                }
                self._update_group_stats(group_name)
        return activated

    @staticmethod
    def _flexible_match(text: str, word: str) -> bool:
        return word.lower() in text.lower()

    def _update_group_stats(self, group_name: str) -> None:
        g = self.groups.get(group_name)
        if g:
            from datetime import datetime, timezone
            g["last_activated"] = datetime.now(timezone.utc).isoformat()
            g["activation_count"] = g.get("activation_count", 0) + 1

    # =================================================================
    # Precompute Group Vectors
    # =================================================================

    @staticmethod
    def _get_words_hash(words: list[str]) -> str | None:
        if not words:
            return None
        return hashlib.sha256(json.dumps(sorted(words)).encode()).hexdigest()

    async def precompute_group_vectors(self) -> bool:
        logger.info("[SemanticGroup] 检查并预计算组向量...")
        changes_made = False

        for group_name, group_data in list(self.groups.items()):
            all_words = list(group_data.get("words", [])) + list(group_data.get("auto_learned", []))
            if not all_words:
                if group_data.get("vector_id"):
                    try:
                        os.unlink(os.path.join(self.vectors_dir_path, f"{group_data['vector_id']}.json"))
                    except OSError:
                        pass
                    self.groups[group_name].pop("vector_id", None)
                    self.groups[group_name].pop("words_hash", None)
                    self.group_vector_cache.pop(group_name, None)
                    changes_made = True
                continue

            current_hash = self._get_words_hash(all_words)
            vector_exists = group_name in self.group_vector_cache

            if current_hash != group_data.get("words_hash") or not vector_exists:
                description = f"{group_name}相关主题：{', '.join(all_words)}"
                vector = await self.embed_fn(description)

                if vector:
                    # 删除旧向量文件
                    if group_data.get("vector_id"):
                        try:
                            os.unlink(os.path.join(self.vectors_dir_path, f"{group_data['vector_id']}.json"))
                        except OSError:
                            pass
                    vid = str(uuid.uuid4())
                    vec_path = os.path.join(self.vectors_dir_path, f"{vid}.json")
                    with open(vec_path, "w", encoding="utf-8") as f:
                        json.dump(vector, f)
                    self.group_vector_cache[group_name] = vector
                    self.groups[group_name]["vector_id"] = vid
                    self.groups[group_name]["words_hash"] = current_hash
                    self.groups[group_name].pop("vector", None)
                    changes_made = True
                    logger.info('[SemanticGroup] "%s" 组向量已计算 (ID: %s)', group_name, vid)

        if changes_made:
            self._save_groups()
        else:
            logger.info("[SemanticGroup] 所有组向量均是最新。")
        return changes_made

    # =================================================================
    # Enhanced Vector
    # =================================================================

    async def get_enhanced_vector(
        self,
        original_query: str,
        activated_groups: dict[str, dict],
        precomputed_query_vector: list[float] | None = None,
    ) -> list[float] | None:
        query_vector = precomputed_query_vector
        if query_vector is None:
            query_vector = await self.embed_fn(original_query)
        if query_vector is None:
            return None
        if not activated_groups:
            return query_vector

        vectors: list[list[float]] = [query_vector]
        weights: list[float] = [1.0]

        for group_name, data in activated_groups.items():
            gv = self.group_vector_cache.get(group_name)
            if gv:
                vectors.append(gv)
                weights.append((self.groups.get(group_name, {}).get("weight", 1.0)) * data["strength"])

        if len(vectors) == 1:
            return query_vector

        enhanced = self._weighted_average_vectors(vectors, weights)
        logger.info("[SemanticGroup] 查询向量已与 %d 个语义组混合。", len(activated_groups))
        return enhanced

    @staticmethod
    def _weighted_average_vectors(vectors: list[list[float]], weights: list[float]) -> list[float] | None:
        if not vectors:
            return None
        dim = len(vectors[0])
        result = np.zeros(dim, dtype=np.float64)
        total_weight = 0.0
        for i, v in enumerate(vectors):
            if v is None or len(v) != dim:
                continue
            arr = np.asarray(v, dtype=np.float64)
            result += arr * weights[i]
            total_weight += weights[i]
        if total_weight == 0:
            return vectors[0]
        result /= total_weight
        return result.tolist()
