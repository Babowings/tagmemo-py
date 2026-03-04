"""tests/test_vector_index.py — VectorIndex 单元测试"""

from __future__ import annotations

import numpy as np
import pytest

from tagmemo.vector_index import VectorIndex


class TestVectorIndexBasic:
    """基础 CRUD 操作。"""

    def test_create_empty(self):
        idx = VectorIndex(dim=128, capacity=100)
        s = idx.stats()
        assert s["dimensions"] == 128
        assert s["total_vectors"] == 0

    def test_add_and_search(self, sample_vectors: np.ndarray, sample_query: np.ndarray):
        idx = VectorIndex(dim=128, capacity=100)
        for i, vec in enumerate(sample_vectors):
            idx.add(i + 1, vec)
        results = idx.search(sample_query, k=3)
        assert len(results) == 3
        for r in results:
            assert "id" in r
            assert "score" in r
            assert isinstance(r["id"], int)
            assert isinstance(r["score"], float)

    def test_add_batch(self, sample_vectors: np.ndarray, sample_query: np.ndarray):
        idx = VectorIndex(dim=128, capacity=100)
        ids = list(range(1, len(sample_vectors) + 1))
        idx.add_batch(ids, sample_vectors)
        s = idx.stats()
        assert s["total_vectors"] == len(sample_vectors)
        results = idx.search(sample_query, k=5)
        assert len(results) == 5

    def test_remove(self, sample_vectors: np.ndarray):
        idx = VectorIndex(dim=128, capacity=100)
        idx.add(1, sample_vectors[0])
        idx.add(2, sample_vectors[1])
        idx.remove(1)
        # usearch 的 remove 标记为 tombstone，total 可能不立即减少
        # 但搜索不应返回已删除的向量
        results = idx.search(sample_vectors[0], k=5)
        found_ids = {r["id"] for r in results}
        assert 1 not in found_ids

    def test_search_score_range(self, sample_vectors: np.ndarray):
        """score = 1.0 - l2sq_distance，应为 ≤ 1.0 (自身搜索时 = 1.0)。"""
        idx = VectorIndex(dim=128, capacity=100)
        idx.add(1, sample_vectors[0])
        results = idx.search(sample_vectors[0], k=1)
        assert len(results) == 1
        assert results[0]["score"] == pytest.approx(1.0, abs=1e-4)

    def test_search_k_greater_than_size(self, sample_vectors: np.ndarray):
        """k > 索引大小时应返回全部，不报错。"""
        idx = VectorIndex(dim=128, capacity=100)
        idx.add(1, sample_vectors[0])
        results = idx.search(sample_vectors[0], k=100)
        assert len(results) == 1


class TestVectorIndexPersistence:
    """保存 / 加载测试。"""

    def test_save_and_load(self, tmp_dir, sample_vectors: np.ndarray, sample_query: np.ndarray):
        path = str(tmp_dir / "test.usearch")
        # Save
        idx = VectorIndex(dim=128, capacity=100)
        for i, v in enumerate(sample_vectors):
            idx.add(i + 1, v)
        idx.save(path)

        # Load
        idx2 = VectorIndex.load(path, dim=128, capacity=100)
        results = idx2.search(sample_query, k=3)
        assert len(results) == 3

    def test_load_nonexistent_no_db(self, tmp_dir):
        """加载不存在的文件且无 db_path 时应返回空索引。"""
        path = str(tmp_dir / "nonexistent.usearch")
        idx = VectorIndex.load(path, dim=128, capacity=100)
        assert idx.stats()["total_vectors"] == 0


class TestVectorIndexStaticMethods:
    """静态数学方法。"""

    def test_compute_svd(self, sample_vectors: np.ndarray):
        result = VectorIndex.compute_svd(sample_vectors, max_k=5)
        assert "u" in result
        assert "s" in result
        assert "k" in result
        assert "dim" in result
        assert result["k"] <= 5

    def test_compute_orthogonal_projection(self, sample_vectors: np.ndarray, sample_query: np.ndarray):
        tag_vectors = sample_vectors[:3]
        result = VectorIndex.compute_orthogonal_projection(sample_query, tag_vectors)
        assert "projection" in result
        assert "residual" in result
        assert "basis_coefficients" in result
        assert len(result["basis_coefficients"]) == 3

    def test_compute_handshakes(self, sample_vectors: np.ndarray, sample_query: np.ndarray):
        tag_vectors = sample_vectors[:3]
        result = VectorIndex.compute_handshakes(sample_query, tag_vectors)
        assert "magnitudes" in result
        assert "directions" in result

    def test_project(self, sample_vectors: np.ndarray, sample_query: np.ndarray):
        # 先做 SVD 得到 basis
        svd_result = VectorIndex.compute_svd(sample_vectors, max_k=5)
        basis = svd_result["u"]  # shape: (k, dim)
        mean = sample_vectors.mean(axis=0)
        result = VectorIndex.project(sample_query, basis, mean)
        assert "projections" in result
        assert "probabilities" in result
        assert "entropy" in result
        assert "total_energy" in result


class TestAutoExpand:
    """自动扩容。"""

    def test_auto_expand_capacity(self):
        idx = VectorIndex(dim=4, capacity=2)
        rng = np.random.default_rng(0)
        for i in range(10):
            vec = rng.standard_normal(4).astype(np.float32)
            idx.add(i + 1, vec)
        s = idx.stats()
        assert s["total_vectors"] == 10
        assert s["capacity"] >= 10
