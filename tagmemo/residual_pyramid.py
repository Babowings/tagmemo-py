"""residual_pyramid.py — 残差金字塔模块，替代 ResidualPyramid.js (392 行)。

基于 Gram-Schmidt 正交化计算多层级语义残差，精确分析语义能量谱。
有状态类，构造时注入 tagIndex (VectorIndex) 和 db (sqlite3.Connection)。
"""

from __future__ import annotations

import logging
import math
import sqlite3

import numpy as np

from .vector_index import VectorIndex

logger = logging.getLogger(__name__)


class ResidualPyramid:
    """残差金字塔，1:1 对应原 JS ResidualPyramid。"""

    def __init__(
        self,
        tag_index: VectorIndex | None,
        db: sqlite3.Connection,
        config: dict | None = None,
    ) -> None:
        cfg = config or {}
        self.tag_index = tag_index
        self.db = db
        self.config = {
            "max_levels": cfg.get("max_levels", 3),
            "top_k": cfg.get("top_k", 10),
            "min_energy_ratio": cfg.get("min_energy_ratio", 0.1),
            "dimension": cfg.get("dimension", 3072),
            **cfg,
        }

    # ------------------------------------------------------------------
    # 核心：残差金字塔分析
    # ------------------------------------------------------------------

    def analyze(self, query_vector: np.ndarray) -> dict:
        """计算查询向量的残差金字塔。"""
        dim = self.config["dimension"]
        vec = np.asarray(query_vector, dtype=np.float32)

        # 初始总能量
        original_energy = float(np.dot(vec, vec))
        if original_energy < 1e-12:
            return self._empty_result(dim)

        current_residual = vec.copy()
        levels: list[dict] = []
        total_explained_energy = 0.0

        for level in range(self.config["max_levels"]):
            # 1. 搜索当前残差的最近 Tags
            try:
                tag_results = self.tag_index.search(current_residual, self.config["top_k"])
            except Exception as exc:
                logger.warning("[Residual] Search failed at level %d: %s", level, exc)
                break
            if not tag_results:
                break

            # 2. 获取 Tag 向量
            tag_ids = [r["id"] for r in tag_results]
            raw_tags = self._get_tag_vectors(tag_ids)
            if not raw_tags:
                break

            # 3. Gram-Schmidt 正交投影
            tag_vectors = np.array([t["vector"] for t in raw_tags], dtype=np.float32)
            proj_result = self.compute_orthogonal_projection(current_residual, tag_vectors)

            projection = np.array(proj_result["projection"], dtype=np.float64)
            residual = np.array(proj_result["residual"], dtype=np.float64)
            basis_coefficients = proj_result["basis_coefficients"]

            # 4. 能量计算
            residual_energy = float(np.dot(residual, residual))
            current_energy = float(np.dot(current_residual.astype(np.float64), current_residual.astype(np.float64)))
            energy_explained = max(0.0, current_energy - residual_energy) / original_energy

            # 5. 握手分析
            handshakes = VectorIndex.compute_handshakes(current_residual, tag_vectors)
            handshake_features = self._analyze_handshakes(handshakes, dim)

            # 构建本层结果
            level_tags = []
            for i, t in enumerate(raw_tags):
                res_entry = next((r for r in tag_results if r["id"] == t["id"]), None)
                level_tags.append({
                    "id": t["id"],
                    "name": t["name"],
                    "similarity": res_entry["score"] if res_entry else 0.0,
                    "contribution": float(basis_coefficients[i]),
                    "handshake_magnitude": handshakes["magnitudes"][i],
                })

            proj_mag = float(np.linalg.norm(projection))
            res_mag = math.sqrt(residual_energy)

            levels.append({
                "level": level,
                "tags": level_tags,
                "projection_magnitude": proj_mag,
                "residual_magnitude": res_mag,
                "residual_energy_ratio": residual_energy / original_energy,
                "energy_explained": energy_explained,
                "handshake_features": handshake_features,
            })

            total_explained_energy += energy_explained
            current_residual = residual.astype(np.float32)

            # 6. 能量阈值截断
            if (residual_energy / original_energy) < self.config["min_energy_ratio"]:
                break

        features = self._extract_pyramid_features(levels, total_explained_energy)
        return {
            "levels": levels,
            "total_explained_energy": total_explained_energy,
            "final_residual": current_residual,
            "features": features,
        }

    # ------------------------------------------------------------------
    # 正交投影 — 公共方法（ResultDeduplicator 跨模块调用）
    # ------------------------------------------------------------------

    @staticmethod
    def compute_orthogonal_projection(
        vector: np.ndarray, tag_vectors: np.ndarray
    ) -> dict:
        """Gram-Schmidt 正交投影，委托给 VectorIndex.compute_orthogonal_projection。"""
        return VectorIndex.compute_orthogonal_projection(vector, tag_vectors)

    # ------------------------------------------------------------------
    # 握手分析
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_handshakes(handshakes: dict, dim: int) -> dict | None:
        """分析握手差值的统计特征。"""
        magnitudes = handshakes["magnitudes"]
        directions_flat = handshakes["directions"]
        n = len(magnitudes)
        if n == 0:
            return None

        # 将扁平 directions 重塑为 (n, dim)
        directions = np.array(directions_flat, dtype=np.float64).reshape(n, dim)

        # 1. 方向一致性 (Coherence)
        avg_dir = directions.mean(axis=0)
        direction_coherence = float(np.linalg.norm(avg_dir))

        # 2. 内部张力 (采样前 5 对)
        limit = min(n, 5)
        pairwise_sum = 0.0
        pair_count = 0
        for i in range(limit):
            for j in range(i + 1, limit):
                pairwise_sum += abs(float(np.dot(directions[i], directions[j])))
                pair_count += 1
        avg_pairwise_sim = pairwise_sum / pair_count if pair_count > 0 else 0.0

        return {
            "direction_coherence": direction_coherence,
            "pattern_strength": avg_pairwise_sim,
            "novelty_signal": direction_coherence,
            "noise_signal": (1 - direction_coherence) * (1 - avg_pairwise_sim),
        }

    # ------------------------------------------------------------------
    # 综合特征
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pyramid_features(
        levels: list[dict], total_explained_energy: float
    ) -> dict:
        if not levels:
            return {
                "depth": 0, "coverage": 0.0, "novelty": 1.0,
                "coherence": 0.0, "tag_memo_activation": 0.0,
            }

        handshake = levels[0].get("handshake_features")
        coverage = min(1.0, total_explained_energy)
        coherence = handshake["pattern_strength"] if handshake else 0.0

        residual_ratio = 1.0 - coverage
        directional_novelty = handshake["novelty_signal"] if handshake else 0.0
        novelty = residual_ratio * 0.7 + directional_novelty * 0.3

        noise = handshake.get("noise_signal", 0.0) if handshake else 0.0

        return {
            "depth": len(levels),
            "coverage": coverage,
            "novelty": novelty,
            "coherence": coherence,
            "tag_memo_activation": coverage * coherence * (1 - noise),
            "expansion_signal": novelty,
        }

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _get_tag_vectors(self, ids: list[int]) -> list[dict]:
        """从 SQLite 批量获取 Tag 向量。"""
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.execute(
            f"SELECT id, name, vector FROM tags WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

        dim = self.config["dimension"]
        expected_bytes = dim * 4
        result = []
        for row in rows:
            blob = row[2]
            if blob and len(blob) == expected_bytes:
                vec = np.frombuffer(blob, dtype=np.float32).copy()
                result.append({"id": row[0], "name": row[1], "vector": vec})
        return result

    def _empty_result(self, dim: int) -> dict:
        return {
            "levels": [],
            "total_explained_energy": 0.0,
            "final_residual": np.zeros(dim, dtype=np.float32),
            "features": {
                "depth": 0, "coverage": 0.0, "novelty": 1.0,
                "coherence": 0.0, "tag_memo_activation": 0.0,
            },
        }
