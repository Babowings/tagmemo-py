"""tests/test_epa.py — EPAModule 单元测试"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from tagmemo.epa import EPAModule


def _seed_tags(conn: sqlite3.Connection, dim: int = 128, n: int = 20) -> None:
    """往 tags 表插入 n 条随机向量，模拟预建标签库。"""
    rng = np.random.default_rng(42)
    for i in range(n):
        tag_name = f"tag_{i}"
        vec = rng.standard_normal(dim).astype(np.float32)
        blob = vec.tobytes()
        conn.execute(
            "INSERT OR IGNORE INTO tags (id, name, vector, count) VALUES (?, ?, ?, ?)",
            (i + 1, tag_name, blob, max(1, int(rng.integers(1, 10)))),
        )
    conn.commit()


class TestEPAModuleInit:
    """初始化与基本设置。"""

    def test_create_with_defaults(self, memory_db: sqlite3.Connection):
        epa = EPAModule(memory_db)
        assert epa.initialized is False

    def test_create_with_custom_config(self, memory_db: sqlite3.Connection):
        cfg = {"max_basis_dim": 32, "dimension": 128, "cluster_count": 8}
        epa = EPAModule(memory_db, config=cfg)
        assert epa.config["max_basis_dim"] == 32
        assert epa.config["dimension"] == 128


class TestEPAModuleInitialize:
    """初始化 (需要 tags 数据)。"""

    def test_initialize_with_tags(self, memory_db: sqlite3.Connection):
        dim = 128
        _seed_tags(memory_db, dim=dim, n=20)
        epa = EPAModule(memory_db, config={"dimension": dim, "cluster_count": 4, "max_basis_dim": 8})
        ok = epa.initialize()
        assert ok is True
        assert epa.initialized is True

    def test_initialize_empty_db(self, memory_db: sqlite3.Connection):
        """空 tags 表时 initialize 应返回 False。"""
        epa = EPAModule(memory_db, config={"dimension": 128})
        ok = epa.initialize()
        assert ok is False
        assert epa.initialized is False


class TestEPAModuleProject:
    """project / detect_cross_domain_resonance。"""

    def test_project_after_init(self, memory_db: sqlite3.Connection):
        dim = 128
        _seed_tags(memory_db, dim=dim, n=20)
        epa = EPAModule(memory_db, config={"dimension": dim, "cluster_count": 4, "max_basis_dim": 8})
        epa.initialize()

        rng = np.random.default_rng(99)
        query_vec = rng.standard_normal(dim).astype(np.float32)
        result = epa.project(query_vec)
        assert "projections" in result or "entropy" in result or result is not None

    def test_project_without_init(self, memory_db: sqlite3.Connection):
        """未初始化时 project 应返回空结果。"""
        epa = EPAModule(memory_db, config={"dimension": 128})
        rng = np.random.default_rng(99)
        query_vec = rng.standard_normal(128).astype(np.float32)
        result = epa.project(query_vec)
        # 应返回某种空/默认结果而不是抛异常
        assert result is not None

    def test_detect_cross_domain_resonance(self, memory_db: sqlite3.Connection):
        dim = 128
        _seed_tags(memory_db, dim=dim, n=20)
        epa = EPAModule(memory_db, config={"dimension": dim, "cluster_count": 4, "max_basis_dim": 8})
        epa.initialize()

        rng = np.random.default_rng(99)
        query_vec = rng.standard_normal(dim).astype(np.float32)
        result = epa.detect_cross_domain_resonance(query_vec)
        assert result is not None


class TestEPAModuleComputeWeightedPCA:
    """compute_weighted_pca (半公开方法，被 ResultDeduplicator 调用)。"""

    def test_compute_weighted_pca(self, memory_db: sqlite3.Connection):
        dim = 128
        _seed_tags(memory_db, dim=dim, n=20)
        epa = EPAModule(memory_db, config={"dimension": dim, "cluster_count": 4, "max_basis_dim": 8})
        epa.initialize()

        # 构造 cluster_data
        rng = np.random.default_rng(42)
        cluster_data = {
            "labels": [0, 0, 1, 1, 2, 2],
            "centroids": rng.standard_normal((3, dim)).astype(np.float32),
            "vectors": rng.standard_normal((6, dim)).astype(np.float32),
            "weights": [1.0] * 6,
        }
        result = epa.compute_weighted_pca(cluster_data)
        assert result is not None
