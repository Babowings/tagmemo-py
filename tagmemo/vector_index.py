"""vector_index.py — usearch 适配层，替代 rust-vexus-lite (642 行 Rust)。

对 usearch.Index 的封装，1:1 对应原 VexusIndex API。
同时包含 SVD / Gram-Schmidt / Handshake / EPA-project 等数值方法，
原版由 Rust nalgebra 实现，此处用 numpy 替代。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import numpy as np
from usearch.index import Index


class VectorIndex:
    """usearch 向量索引封装，替代 rust-vexus-lite 的 VexusIndex。

    关键设计决策（与原 Rust 版保持一致）：
    - metric = 'l2sq'  (lib.rs:73 MetricKind::L2sq)
    - dtype = 'f32'    (lib.rs:74 ScalarKind::F32)
    - connectivity = 16 (lib.rs:75)
    - score = 1.0 - l2sq_distance  (lib.rs:252)
    """

    # ------------------------------------------------------------------
    # 构造 / 加载 / 保存
    # ------------------------------------------------------------------

    def __init__(self, dim: int, capacity: int = 10_000) -> None:
        self.dim = dim
        self._initial_capacity = capacity
        self.index = Index(
            ndim=dim,
            metric="l2sq",
            dtype="f32",
            connectivity=16,
            expansion_add=128,
            expansion_search=64,
        )
        # usearch >=2.23 自动扩容，无需手动 reserve

    @classmethod
    def load(
        cls,
        path: str,
        dim: int,
        capacity: int = 10_000,
        *,
        db_path: str | None = None,
        table_type: str | None = None,
        filter_diary_name: str | None = None,
    ) -> VectorIndex:
        """从磁盘加载索引文件。

        如果加载失败且提供了 ``db_path``，自动从 SQLite 重建（fallback）。
        """
        instance = cls.__new__(cls)
        instance.dim = dim
        instance._initial_capacity = capacity
        try:
            restored = Index.restore(path, view=False)
            if restored is None:
                raise FileNotFoundError(f"Index.restore returned None for {path}")
            instance.index = restored
        except Exception:
            # Fallback：建空索引 + 从 SQLite 重建
            instance.index = Index(
                ndim=dim,
                metric="l2sq",
                dtype="f32",
                connectivity=16,
                expansion_add=128,
                expansion_search=64,
            )
            if db_path:
                count = instance.recover_from_sqlite(
                    db_path, table_type or "tags", filter_diary_name
                )
                print(f"[VectorIndex] Rebuilt index from SQLite: {count} vectors")
        return instance

    def save(self, path: str) -> None:
        """原子写入：先写临时文件，再 ``os.replace``（与 Rust lib.rs:132-140 一致）。"""
        temp_path = f"{path}.tmp"
        self.index.save(temp_path)
        os.replace(temp_path, path)  # 原子替换，Windows 安全

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, id: int, vector: np.ndarray) -> None:
        """添加单条向量。usearch >=2.23 自动扩容。"""
        self.index.add(id, vector.astype(np.float32))

    def add_batch(self, ids: list[int], vectors: np.ndarray) -> None:
        """批量添加（对应 Rust add_batch）。usearch >=2.23 自动扩容。

        注意：usearch C++ 核心使用 uint64_t 作为 label_t，
        原版 Rust 也用 u64，此处统一用 np.uint64。
        """
        self.index.add(np.array(ids, dtype=np.uint64), vectors.astype(np.float32))

    def remove(self, id: int) -> None:
        self.index.remove(id)

    def search(self, query: np.ndarray, k: int) -> list[dict]:
        """搜索最近 k 个向量，返回 [{id, score}]。

        score = 1.0 - l2sq_dist，与原版 Rust (lib.rs:252) 完全一致。
        对于归一化向量 l2sq ∈ [0, 4]，score ∈ [-3, 1]。
        结果仅用于排序（越大越好），绝对值不影响功能。
        """
        matches = self.index.search(query.astype(np.float32), k)
        return [
            {"id": int(key), "score": 1.0 - float(dist)}
            for key, dist in zip(matches.keys, matches.distances)
        ]

    def stats(self) -> dict:
        return {
            "total_vectors": len(self.index),
            "dimensions": self.dim,
            "capacity": self.index.capacity,
        }

    # ------------------------------------------------------------------
    # SQLite 恢复
    # ------------------------------------------------------------------

    def recover_from_sqlite(
        self,
        db_path: str,
        table_type: str,
        filter_diary_name: str | None = None,
    ) -> int:
        """从 SQLite 重建索引（对应 Rust RecoverTask）。"""
        conn = sqlite3.connect(db_path)
        try:
            if table_type == "tags":
                rows = conn.execute(
                    "SELECT id, vector FROM tags WHERE vector IS NOT NULL"
                ).fetchall()
            elif table_type == "chunks" and filter_diary_name:
                rows = conn.execute(
                    "SELECT c.id, c.vector FROM chunks c "
                    "JOIN files f ON c.file_id = f.id "
                    "WHERE f.diary_name = ? AND c.vector IS NOT NULL",
                    (filter_diary_name,),
                ).fetchall()
            else:
                return 0

            count = 0
            expected_bytes = self.dim * 4  # float32 = 4 bytes
            for row_id, vector_blob in rows:
                if vector_blob and len(vector_blob) == expected_bytes:
                    # ⚠️ .copy() 必须！np.frombuffer 返回只读数组
                    vec = np.frombuffer(vector_blob, dtype=np.float32).copy()
                    self.add(row_id, vec)
                    count += 1
            return count
        finally:
            conn.close()

    # ==================================================================
    # 数值计算方法 — 替代 Rust nalgebra 实现
    # ==================================================================

    @staticmethod
    def compute_svd(vectors: np.ndarray, max_k: int) -> dict:
        """替代 Rust compute_svd (lib.rs:302-352)。

        输入 n×dim 矩阵，返回前 k 个主成分（V^T 的行）。
        注意：EPA 实际使用 Gram + eigh，此方法保留作为通用工具（ResultDeduplicator 使用）。
        """
        mat = vectors.astype(np.float64)
        _U, S, Vt = np.linalg.svd(mat, full_matrices=False)
        k = min(len(S), max_k)
        return {
            "u": Vt[:k],          # ndarray shape (k, dim)
            "s": S[:k].tolist(),
            "k": k,
            "dim": vectors.shape[1],
        }

    @staticmethod
    def compute_orthogonal_projection(
        query: np.ndarray, tag_vectors: np.ndarray
    ) -> dict:
        """替代 Rust compute_orthogonal_projection (lib.rs:355-413)。

        经典 Gram-Schmidt 正交投影。
        """
        dim = len(query)
        q = query.astype(np.float64)
        basis: list[np.ndarray] = []
        coefficients = np.zeros(len(tag_vectors), dtype=np.float64)
        projection = np.zeros(dim, dtype=np.float64)

        for i, tag_vec in enumerate(tag_vectors):
            v = tag_vec.astype(np.float64).copy()
            for u in basis:
                v -= np.dot(v, u) * u
            mag = np.linalg.norm(v)
            if mag > 1e-6:
                v /= mag
                coeff = np.dot(q, v)
                coefficients[i] = abs(coeff)
                projection += coeff * v
                basis.append(v)

        residual = q - projection
        return {
            "projection": projection.tolist(),
            "residual": residual.tolist(),
            "basis_coefficients": coefficients.tolist(),
        }

    @staticmethod
    def compute_handshakes(query: np.ndarray, tag_vectors: np.ndarray) -> dict:
        """替代 Rust compute_handshakes (lib.rs:416-462)。"""
        deltas = query.astype(np.float64) - tag_vectors.astype(np.float64)
        magnitudes = np.linalg.norm(deltas, axis=1)
        safe_mags = np.where(magnitudes > 1e-9, magnitudes, 1.0)
        directions = deltas / safe_mags[:, np.newaxis]
        directions[magnitudes <= 1e-9] = 0.0
        return {
            "magnitudes": magnitudes.tolist(),
            "directions": directions.flatten().tolist(),
        }

    @staticmethod
    def project(
        vector: np.ndarray, basis: np.ndarray, mean: np.ndarray
    ) -> dict:
        """替代 Rust .project() (lib.rs:465-518) — EPA 投影。"""
        centered = (vector - mean).astype(np.float64)
        projs = basis.astype(np.float64) @ centered
        energies = projs ** 2
        total_energy = float(energies.sum())

        if total_energy > 1e-12:
            probabilities = energies / total_energy
            mask = probabilities > 1e-9
            entropy = float(-np.sum(probabilities[mask] * np.log2(probabilities[mask])))
        else:
            probabilities = np.zeros_like(projs)
            entropy = 0.0

        return {
            "projections": projs.tolist(),
            "probabilities": probabilities.tolist(),
            "entropy": entropy,
            "total_energy": total_energy,
        }
