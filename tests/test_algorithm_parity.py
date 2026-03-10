from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest

from tagmemo import embedding_utils
from tagmemo.knowledge_base import KnowledgeBaseManager


class _DummyIndex:
    def __init__(self, results: list[dict] | None = None) -> None:
        self._results = results or []
        self.added: list[tuple[int, np.ndarray]] = []

    def stats(self) -> dict:
        return {"total_vectors": len(self._results) or 1}

    def search(self, vector, k: int) -> list[dict]:
        return self._results[:k]

    def add(self, key: int, vec: np.ndarray) -> None:
        self.added.append((key, vec))

    def remove(self, key: int) -> None:
        return None

    def save(self, path: str) -> None:
        return None


class _DummyEPA:
    def project(self, vector: np.ndarray) -> dict:
        return {
            "logic_depth": 1.0,
            "entropy": 0.0,
            "dominant_axes": [{"label": "World"}],
        }

    def detect_cross_domain_resonance(self, vector: np.ndarray) -> dict:
        return {"resonance": 0.0, "bridges": []}


class _DummyPyramid:
    def analyze(self, vector: np.ndarray) -> dict:
        return {
            "levels": [
                {
                    "level": 0,
                    "tags": [
                        {
                            "id": 1,
                            "name": "tag-1",
                            "contribution": 1.0,
                            "similarity": 1.0,
                        }
                    ],
                }
            ],
            "features": {
                "coverage": 0.0,
                "novelty": 0.0,
                "depth": 1.0,
                "tag_memo_activation": 1.0,
            },
        }


def _build_kb(tmp_path: Path) -> KnowledgeBaseManager:
    root = tmp_path / "data" / "dailynote"
    store = tmp_path / "VectorStore"
    root.mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)

    kb = KnowledgeBaseManager(
        {
            "root_path": str(root),
            "store_path": str(store),
            "dimension": 2,
            "full_scan_on_startup": False,
        }
    )
    kb.db = sqlite3.connect(store / "knowledge_base.sqlite", check_same_thread=False)
    kb._init_schema()
    kb.tag_index = _DummyIndex()
    kb.epa = _DummyEPA()
    kb.residual_pyramid = _DummyPyramid()
    kb.rag_params = {
        "KnowledgeBaseManager": {
            "activationMultiplier": [1.5, 1.5],
            "dynamicBoostRange": [0.3, 2.0],
            "coreBoostRange": [1.2, 1.4],
        }
    }
    return kb


def test_apply_tag_boost_clamps_alpha_to_one(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None
    kb.db.execute("INSERT INTO tags (id, name, vector) VALUES (1, 'tag-1', ?)", (np.array([0.0, 1.0], dtype=np.float32).tobytes(),))
    kb.db.commit()

    result = kb._apply_tag_boost_v3(
        np.array([1.0, 0.0], dtype=np.float32),
        base_tag_boost=1.0,
        core_tags=[],
    )

    assert result["vector"] == pytest.approx(np.array([0.0, 1.0], dtype=np.float32), abs=1e-6)


def test_hydrate_results_specific_includes_upstream_fields(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None
    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (1, ?, 'DiaryA', 'c1', 1, 1, 123)",
        ("DiaryA/2026-03-09.md",),
    )
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (101, 1, 'hello', 0, ?)", (b"v",))
    kb.db.commit()

    hydrated = kb._hydrate_results(
        [{"id": 101, "score": 0.9}],
        {
            "matched_tags": ["tag-1", "tag-2"],
            "boost_factor": 0.8,
            "core_tags_matched": ["tag-1"],
            "totalSpikeScore": 2.5,
        },
        with_updated_at=True,
    )

    assert hydrated == [
        {
            "text": "hello",
            "score": 0.9,
            "sourceFile": "2026-03-09.md",
            "fullPath": "DiaryA/2026-03-09.md",
            "matchedTags": ["tag-1", "tag-2"],
            "boostFactor": 0.8,
            "tagMatchScore": 2.5,
            "tagMatchCount": 2,
            "coreTagsMatched": ["tag-1"],
            "updated_at": 123,
        }
    ]


def test_hydrate_results_global_omits_full_path(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None
    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (1, ?, 'DiaryA', 'c1', 1, 1, 123)",
        ("DiaryA/2026-03-09.md",),
    )
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (101, 1, 'hello', 0, ?)", (b"v",))
    kb.db.commit()

    hydrated = kb._hydrate_results([{"id": 101, "score": 0.9}], None, with_updated_at=False)

    assert hydrated == [
        {
            "text": "hello",
            "score": 0.9,
            "sourceFile": "2026-03-09.md",
            "matchedTags": [],
            "boostFactor": 0,
            "tagMatchScore": 0,
            "tagMatchCount": 0,
            "coreTagsMatched": [],
        }
    ]
    assert "fullPath" not in hydrated[0]


@pytest.mark.asyncio
async def test_search_forwards_core_boost_factor_to_specific(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    kb = _build_kb(tmp_path)
    captured: dict[str, object] = {}

    def _fake_specific(diary_name, query_vec, k, tag_boost, core_tags, core_boost_factor):
        captured.update(
            {
                "diary_name": diary_name,
                "k": k,
                "tag_boost": tag_boost,
                "core_tags": core_tags,
                "core_boost_factor": core_boost_factor,
            }
        )
        return [{"ok": True}]

    monkeypatch.setattr(kb, "_search_specific_index", _fake_specific)

    result = await kb.search("DiaryA", [1.0, 0.0], 7, 0.4, ["core"], 1.9)

    assert result == [{"ok": True}]
    assert captured["core_boost_factor"] == 1.9


@pytest.mark.asyncio
async def test_search_forwards_core_boost_factor_to_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    kb = _build_kb(tmp_path)
    captured: dict[str, object] = {}

    def _fake_global(query_vec, k, tag_boost, core_tags, core_boost_factor):
        captured.update(
            {
                "k": k,
                "tag_boost": tag_boost,
                "core_tags": core_tags,
                "core_boost_factor": core_boost_factor,
            }
        )
        return [{"ok": True}]

    monkeypatch.setattr(kb, "_search_all_indices", _fake_global)

    result = await kb.search([1.0, 0.0], 7, 0.4, ["core"], 1.9)

    assert result == [{"ok": True}]
    assert captured["core_boost_factor"] == 1.9


@pytest.mark.asyncio
async def test_get_embeddings_batch_preserves_input_positions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(embedding_utils, "_MAX_BATCH_ITEMS", 2)
    monkeypatch.setattr(embedding_utils, "_safe_max_tokens", 10)

    class _FakeEncoding:
        def encode(self, text: str) -> list[int]:
            if text == "oversize":
                return list(range(11))
            return [1]

    async def _fake_send_batch(client, batch_texts, config, batch_number):
        if batch_texts == ["fail-a", "fail-b"]:
            raise RuntimeError("boom")
        return [[float(batch_number), float(i)] for i, _ in enumerate(batch_texts)]

    monkeypatch.setattr(embedding_utils, "_encoding", _FakeEncoding())
    monkeypatch.setattr(embedding_utils, "_send_batch", _fake_send_batch)

    result = await embedding_utils.get_embeddings_batch(
        ["ok-1", "oversize", "ok-2", "fail-a", "fail-b"],
        {"api_key": "k", "api_url": "http://example.com", "model": "m"},
        concurrency=2,
    )

    assert len(result) == 5
    assert result[0] == [1.0, 0.0]
    assert result[1] is None
    assert result[2] == [1.0, 1.0]
    assert result[3] is None
    assert result[4] is None


@pytest.mark.asyncio
async def test_flush_batch_retries_catastrophic_failures_three_times(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    kb = _build_kb(tmp_path)
    kb.tag_index = _DummyIndex()
    file_path = tmp_path / "data" / "dailynote" / "DiaryA" / "bad.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("broken", encoding="utf-8")

    async def _boom(texts, config):
        raise RuntimeError("embedding down")

    monkeypatch.setattr("tagmemo.knowledge_base.get_embeddings_batch", _boom)

    for _ in range(3):
        kb.pending_files.add(str(file_path))
        await kb._flush_batch()

    assert str(file_path) not in kb.pending_files
    assert kb.file_retry_count.get(str(file_path)) is None


@pytest.mark.asyncio
async def test_flush_batch_clears_retry_count_after_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    kb = _build_kb(tmp_path)
    kb.tag_index = _DummyIndex()
    file_path = tmp_path / "data" / "dailynote" / "DiaryA" / "ok.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello world", encoding="utf-8")
    kb.pending_files.add(str(file_path))
    kb.file_retry_count[str(file_path)] = 2

    async def _fake_embeddings(texts, config):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("tagmemo.knowledge_base.get_embeddings_batch", _fake_embeddings)

    await kb._flush_batch()

    assert kb.file_retry_count.get(str(file_path)) is None


def test_flush_batch_async_deduplicates_inflight_dispatches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    kb = _build_kb(tmp_path)
    file_path = tmp_path / "data" / "dailynote" / "DiaryA" / "queued.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello", encoding="utf-8")
    kb.pending_files.add(str(file_path))

    started: list[str] = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append("started")

    monkeypatch.setattr(threading, "Thread", _FakeThread)

    kb._flush_batch_async()
    kb._flush_batch_async()
    kb._flush_batch_async()

    assert len(started) == 1


@pytest.mark.asyncio
async def test_get_embeddings_batch_logs_nonempty_failure_details(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    async def _fake_send_batch(client, batch_texts, config, batch_number):
        raise RuntimeError("")

    monkeypatch.setattr(embedding_utils, "_MAX_BATCH_ITEMS", 2)
    monkeypatch.setattr(embedding_utils, "_safe_max_tokens", 10)

    class _FakeEncoding:
        def encode(self, text: str) -> list[int]:
            return [1]

    monkeypatch.setattr(embedding_utils, "_encoding", _FakeEncoding())
    monkeypatch.setattr(embedding_utils, "_send_batch", _fake_send_batch)

    with caplog.at_level(logging.ERROR):
        result = await embedding_utils.get_embeddings_batch(
            ["a", "b", "c"],
            {"api_key": "k", "api_url": "http://example.com", "model": "m"},
            concurrency=1,
        )

    assert result == [None, None, None]
    error_messages = [record.getMessage() for record in caplog.records if "failed permanently" in record.getMessage()]
    assert error_messages
    assert all(not message.endswith(": ") for message in error_messages)
