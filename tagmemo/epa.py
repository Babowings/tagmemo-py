"""epa.py — 嵌入投影分析模块 (EPA)，替代 EPAModule.js (486 行)。

核心算法：
- 加权 PCA（Gram 矩阵 + eigh，替代 Power Iteration + Deflation）
- 鲁棒 K-Means（余弦相似度、质心归一化）
- EPA 投影（去中心化 → 基底点积 → 能量/熵）
- 跨域共振检测
- 缓存序列化（base64 ↔ numpy）
"""

from __future__ import annotations

import base64
import json
import logging
import math
import sqlite3

import numpy as np

from .vector_index import VectorIndex

logger = logging.getLogger(__name__)


class EPAModule:
    """嵌入投影分析模块，1:1 对应原 JS EPAModule。"""

    def __init__(self, db: sqlite3.Connection, config: dict | None = None) -> None:
        cfg = config or {}
        self.db = db
        self.config = {
            "max_basis_dim": cfg.get("max_basis_dim", 64),
            "min_variance_ratio": cfg.get("min_variance_ratio", 0.01),
            "cluster_count": cfg.get("cluster_count", 32),
            "dimension": cfg.get("dimension", 3072),
            "strict_orthogonalization": cfg.get("strict_orthogonalization", True),
            **cfg,
        }

        self.ortho_basis: list[np.ndarray] | None = None  # Float32 基底
        self.basis_mean: np.ndarray | None = None          # 全局加权平均向量
        self.basis_labels: list[str] | None = None
        self.basis_energies: list[float] | None = None

        self.initialized = False

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """构建正交基（加权 PCA）。"""
        logger.info("[EPA] Initializing orthogonal basis (Weighted PCA)...")

        try:
            if self._load_from_cache():
                logger.info("[EPA] Loaded basis from cache.")
                self.initialized = True
                return True

            rows = self.db.execute(
                "SELECT id, name, vector FROM tags WHERE vector IS NOT NULL"
            ).fetchall()
            if len(rows) < 8:
                return False

            tags = []
            dim = self.config["dimension"]
            expected_bytes = dim * 4
            for row in rows:
                blob = row[2]
                if blob and len(blob) == expected_bytes:
                    vec = np.frombuffer(blob, dtype=np.float32).copy()
                    tags.append({"id": row[0], "name": row[1], "vector": vec})

            if len(tags) < 8:
                return False

            # 1. K-Means 聚类
            k = min(len(tags), self.config["cluster_count"])
            cluster_data = self._cluster_tags(tags, k)

            # 2. 加权 PCA
            svd_result = self.compute_weighted_pca(cluster_data)
            U = svd_result["U"]
            S = svd_result["S"]

            # 3. 选择主成分
            K = self._select_basis_dimension(S)

            self.ortho_basis = U[:K]
            self.basis_energies = S[:K]
            self.basis_mean = svd_result["mean_vector"]
            self.basis_labels = (
                svd_result.get("labels") or cluster_data["labels"]
            )[:K]

            self._save_to_cache()
            self.initialized = True
            return True

        except Exception as exc:
            logger.error("[EPA] Init failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # 投影
    # ------------------------------------------------------------------

    def project(self, vector: np.ndarray) -> dict:
        """将向量投影到语义空间。"""
        if not self.initialized or self.ortho_basis is None:
            return self._empty_result()

        vec = np.asarray(vector, dtype=np.float32)
        K = len(self.ortho_basis)

        # 使用 VectorIndex.project 静态方法
        basis_arr = np.array(self.ortho_basis, dtype=np.float32)
        result = VectorIndex.project(vec, basis_arr, self.basis_mean)

        projections = np.array(result["projections"], dtype=np.float32)
        probabilities = np.array(result["probabilities"], dtype=np.float32)
        entropy = result["entropy"]
        total_energy = result["total_energy"]

        if total_energy < 1e-12:
            return self._empty_result()

        normalized_entropy = entropy / math.log2(K) if K > 1 else 0.0

        # 提取主轴（energy > 5%）
        dominant_axes = []
        for k in range(K):
            if probabilities[k] > 0.05:
                dominant_axes.append({
                    "index": k,
                    "label": self.basis_labels[k] if self.basis_labels else "?",
                    "energy": float(probabilities[k]),
                    "projection": float(projections[k]),
                })
        dominant_axes.sort(key=lambda a: a["energy"], reverse=True)

        return {
            "projections": projections,
            "probabilities": probabilities,
            "entropy": normalized_entropy,
            "logic_depth": 1.0 - normalized_entropy,
            "dominant_axes": dominant_axes,
        }

    # ------------------------------------------------------------------
    # 跨域共振检测
    # ------------------------------------------------------------------

    def detect_cross_domain_resonance(self, vector: np.ndarray) -> dict:
        """检测跨域共振（主轴共激活）。"""
        proj = self.project(vector)
        axes = proj["dominant_axes"]
        if len(axes) < 2:
            return {"resonance": 0.0, "bridges": []}

        bridges = []
        top = axes[0]
        for secondary in axes[1:]:
            co_activation = math.sqrt(top["energy"] * secondary["energy"])
            if co_activation > 0.15:
                bridges.append({
                    "from": top["label"],
                    "to": secondary["label"],
                    "strength": co_activation,
                    "balance": (
                        min(top["energy"], secondary["energy"])
                        / max(top["energy"], secondary["energy"])
                    ),
                })

        resonance = sum(b["strength"] for b in bridges)
        return {"resonance": resonance, "bridges": bridges}

    # ------------------------------------------------------------------
    # K-Means 聚类（余弦 + 质心归一化）
    # ------------------------------------------------------------------

    def _cluster_tags(self, tags: list[dict], k: int) -> dict:
        """鲁棒 K-Means，与原版 _clusterTags 一致。"""
        dim = self.config["dimension"]
        vectors = np.array([t["vector"] for t in tags], dtype=np.float32)
        n = len(vectors)

        # Forgy 初始化
        rng = np.random.default_rng()
        indices = rng.choice(n, size=k, replace=False)
        centroids = vectors[indices].copy()

        max_iter = 50
        tolerance = 1e-4
        cluster_sizes = np.zeros(k, dtype=np.float32)

        for _iter in range(max_iter):
            # Assign（点积 = 余弦相似度，假设向量已归一化）
            sims = vectors @ centroids.T  # (n, k)
            labels = sims.argmax(axis=1)  # (n,)

            # Update
            movement = 0.0
            new_centroids = np.zeros_like(centroids)
            new_sizes = np.zeros(k, dtype=np.float32)

            for i in range(k):
                mask = labels == i
                count = mask.sum()
                new_sizes[i] = count
                if count == 0:
                    new_centroids[i] = centroids[i]
                    continue
                new_c = vectors[mask].sum(axis=0)
                mag = np.linalg.norm(new_c)
                if mag > 1e-9:
                    new_c /= mag
                dist_sq = float(np.sum((new_c - centroids[i]) ** 2))
                movement += dist_sq
                new_centroids[i] = new_c

            cluster_sizes = new_sizes
            centroids = new_centroids
            if movement < tolerance:
                break

        # 标签命名：找最近的 tag name
        labels_text = []
        for c in centroids:
            sims_c = vectors @ c
            best_idx = int(sims_c.argmax())
            labels_text.append(tags[best_idx]["name"])

        return {
            "vectors": [centroids[i] for i in range(k)],
            "labels": labels_text,
            "weights": cluster_sizes.tolist(),
        }

    # ------------------------------------------------------------------
    # 加权 PCA（Gram 矩阵 + eigh）
    # ------------------------------------------------------------------

    def compute_weighted_pca(self, cluster_data: dict) -> dict:
        """加权 PCA — 公共方法（ResultDeduplicator 跨模块调用）。

        步骤：
        1. 加权平均向量
        2. 加权中心化 (sqrt(weight) * (v - mean))
        3. Gram 矩阵 (n×n)
        4. eigh 特征分解（替代原版 Power Iteration + Deflation）
        5. 映射回原始空间 + 归一化
        """
        vectors = cluster_data["vectors"]
        weights = cluster_data["weights"]
        n = len(vectors)
        dim = self.config["dimension"]
        total_weight = sum(weights)

        # Step 1: 加权平均向量
        mean_vector = np.zeros(dim, dtype=np.float32)
        for i in range(n):
            mean_vector += vectors[i] * weights[i]
        mean_vector /= total_weight

        # Step 2: 加权中心化
        centered = np.array(
            [math.sqrt(weights[i]) * (vectors[i] - mean_vector) for i in range(n)],
            dtype=np.float64,
        )

        # Step 3: Gram 矩阵 (n×n)
        G = centered @ centered.T

        # Step 4: eigh（替代 Power Iteration + Deflation, ~150 行 JS → 2 行 Python）
        eigenvalues, eigenvectors = np.linalg.eigh(G)
        # eigh 返回升序，反转为降序
        eigenvalues = eigenvalues[::-1].copy()
        eigenvectors = eigenvectors[:, ::-1].copy()

        # Step 5: 映射回原始空间 U_pca = X^T @ v，然后归一化
        basis: list[np.ndarray] = []
        energies: list[float] = []
        max_k = min(n, self.config["max_basis_dim"])

        for k_idx in range(max_k):
            if eigenvalues[k_idx] < 1e-6:
                break
            ev = eigenvectors[:, k_idx]            # n-dim Gram eigenvector
            b = centered.T @ ev                     # dim-dim basis vector
            mag = np.linalg.norm(b)
            if mag > 1e-9:
                b /= mag
            basis.append(b.astype(np.float32))
            energies.append(float(eigenvalues[k_idx]))

        return {
            "U": basis,
            "S": energies,
            "mean_vector": mean_vector,
            "labels": cluster_data.get("labels"),
        }

    # ------------------------------------------------------------------
    # 基底维度选择
    # ------------------------------------------------------------------

    @staticmethod
    def _select_basis_dimension(S: list[float]) -> int:
        total = sum(S)
        if total < 1e-12:
            return len(S)
        cum = 0.0
        for i, s in enumerate(S):
            cum += s
            if cum / total > 0.95:
                return max(i + 1, 8)
        return len(S)

    # ------------------------------------------------------------------
    # 缓存序列化
    # ------------------------------------------------------------------

    def _save_to_cache(self) -> None:
        """将 EPA 基底保存到 kv_store（base64 序列化）。"""
        try:
            tag_count = self.db.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            data = {
                "basis": [
                    base64.b64encode(b.astype(np.float32).tobytes()).decode()
                    for b in self.ortho_basis
                ],
                "mean": base64.b64encode(
                    self.basis_mean.astype(np.float32).tobytes()
                ).decode(),
                "energies": [float(e) for e in self.basis_energies],
                "labels": self.basis_labels,
                "timestamp": __import__("time").time(),
                "tag_count": tag_count,
            }
            self.db.execute(
                "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
                ("epa_basis_cache", json.dumps(data)),
            )
            self.db.commit()
        except Exception as exc:
            logger.error("[EPA] Save cache error: %s", exc)

    def _load_from_cache(self) -> bool:
        """从 kv_store 加载 EPA 基底。"""
        try:
            row = self.db.execute(
                "SELECT value FROM kv_store WHERE key = ?", ("epa_basis_cache",)
            ).fetchone()
            if not row:
                return False
            data = json.loads(row[0])

            if "mean" not in data:
                return False  # 旧格式不兼容

            # ⚠️ .copy() 是必须的（base64 decode → frombuffer 返回只读视图）
            self.ortho_basis = [
                np.frombuffer(base64.b64decode(b64), dtype=np.float32).copy()
                for b64 in data["basis"]
            ]
            self.basis_mean = np.frombuffer(
                base64.b64decode(data["mean"]), dtype=np.float32
            ).copy()
            self.basis_energies = [float(e) for e in data["energies"]]
            self.basis_labels = data["labels"]
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result() -> dict:
        return {
            "projections": None,
            "probabilities": None,
            "entropy": 1.0,
            "logic_depth": 0.0,
            "dominant_axes": [],
        }
