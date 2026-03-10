"""tests/conftest.py — 共享 fixtures"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """提供一个临时目录。"""
    return tmp_path


@pytest.fixture()
def sample_vectors() -> np.ndarray:
    """生成 10 条 128 维随机 float32 向量，固定种子以保证可重复。"""
    rng = np.random.default_rng(42)
    return rng.standard_normal((10, 128)).astype(np.float32)


@pytest.fixture()
def sample_query() -> np.ndarray:
    """单条 128 维查询向量。"""
    rng = np.random.default_rng(99)
    return rng.standard_normal(128).astype(np.float32)


@pytest.fixture()
def memory_db() -> sqlite3.Connection:
    """内存 SQLite 数据库，预建 vectors / tags / chunks 表。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vectors (
            id INTEGER PRIMARY KEY,
            diary_name TEXT,
            file_path TEXT,
            content TEXT,
            embedding BLOB,
            hash TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            embedding BLOB,
            vector BLOB,
            count INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            diary_name TEXT,
            file_path TEXT,
            content TEXT,
            embedding BLOB,
            hash TEXT,
            chunk_index INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kv_store (
            key TEXT PRIMARY KEY,
            value TEXT,
            vector BLOB
        )
    """)
    conn.commit()
    return conn
