"""result_deduplicator.py — 基于 SVD 和残差金字塔的结果智能去重器，替代 ResultDeduplicator.js (151 行)。

功能：
1. 分析候选结果集的潜在主题 (加权 PCA)
2. 贪心选择最具新颖性的结果（残差正交投影）
3. 保证语义多样性
"""

from __future__ import annotations

import math
import sqlite3

import numpy as np

from .epa import EPAModule
from .residual_pyramid import ResidualPyramid


class ResultDeduplicator:
    """结果去重器，1:1 对应原 JS ResultDeduplicator。"""

    def __init__(self, db: sqlite3.Connection, config: dict | None = None) -> None:
        cfg = config or {}
        self.db = db
        self.config = {
            "dimension": cfg.get("dimension", 3072),
            "max_results": cfg.get("max_results", 20),
            "topic_count": cfg.get("topic_count", 8),
            "min_energy_ratio": 0.1,
            "redundancy_threshold": 0.85,
            **cfg,
        }

        self.epa = EPAModule(db, {
            "dimension": self.config["dimension"],
            "max_basis_dim": self.config["topic_count"],
            "cluster_count": 16,
        })

        self.residual_calculator = ResidualPyramid(None, db, {
            "dimension": self.config["dimension"],
        })

    # ------------------------------------------------------------------
    # 核心去重
    # ------------------------------------------------------------------

    def deduplicate(
        self,
        candidates: list[dict],
        query_vector: np.ndarray,
    ) -> list[dict]:
        """对候选结果去重，保留语义多样性。"""
        if not candidates:
            return []

        valid = [c for c in candidates if c.get("vector") is not None or c.get("_vector") is not None]
        if len(valid) <= 5:
            return candidates

        vectors = []
        for c in valid:
            v = c.get("vector") or c.get("_vector")
            vectors.append(np.asarray(v, dtype=np.float32))

        # 1. 计算潜在主题（加权 PCA）
        cluster_data = {
            "vectors": vectors,
            "weights": [1.0] * len(vectors),
            "labels": ["candidate"] * len(vectors),
        }
        svd_result = self.epa.compute_weighted_pca(cluster_data)
        topics = svd_result["U"]
        energies = svd_result["S"]

        total_energy = sum(energies)
        cum = 0.0
        significant_count = 0
        for e in energies:
            cum += e
            significant_count += 1
            if total_energy > 1e-12 and cum / total_energy > 0.95:
                break

        # 2. 贪心选择：先选与 query 最相似的
        n_query = _normalize(query_vector)
        best_idx = -1
        best_sim = -1.0
        for i, v in enumerate(vectors):
            sim = float(np.dot(_normalize(v), n_query))
            if sim > best_sim:
                best_sim = sim
                best_idx = i

        selected_indices: set[int] = set()
        selected_results: list[dict] = []

        if best_idx != -1:
            selected_indices.add(best_idx)
            selected_results.append(valid[best_idx])

        # 3. 残差贪心：每轮选 novelty × relevance 最高的
        max_rounds = self.config["max_results"] - 1
        current_basis = [vectors[best_idx]] if best_idx != -1 else []

        for _round in range(max_rounds):
            max_score = -1.0
            next_best = -1

            for i, v in enumerate(vectors):
                if i in selected_indices:
                    continue

                # 计算相对现有已选集的残差
                if current_basis:
                    basis_arr = np.array(current_basis, dtype=np.float32)
                    proj_result = ResidualPyramid.compute_orthogonal_projection(v, basis_arr)
                    residual = np.array(proj_result["residual"], dtype=np.float64)
                    novelty_energy = float(np.dot(residual, residual))
                else:
                    novelty_energy = float(np.dot(v.astype(np.float64), v.astype(np.float64)))

                original_score = valid[i].get("score", 0.5)
                score = novelty_energy * (original_score + 0.5)

                if score > max_score:
                    max_score = score
                    next_best = i

            if next_best == -1 or max_score < 0.01:
                break

            selected_indices.add(next_best)
            selected_results.append(valid[next_best])
            current_basis.append(vectors[next_best])

        return selected_results


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------

def _normalize(vec: np.ndarray) -> np.ndarray:
    v = vec.astype(np.float64)
    mag = np.linalg.norm(v)
    if mag > 1e-9:
        v /= mag
    return v
