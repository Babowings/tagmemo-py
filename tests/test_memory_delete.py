from __future__ import annotations

import sqlite3
from pathlib import Path

from tagmemo.knowledge_base import KnowledgeBaseManager


class _DummyIndex:
    def __init__(self) -> None:
        self.removed: list[int] = []
        self.saved_paths: list[str] = []

    def remove(self, key: int) -> None:
        self.removed.append(key)

    def add(self, key, vec) -> None:
        return None

    def save(self, path: str) -> None:
        self.saved_paths.append(path)


class _DummyTimer:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def _build_kb(tmp_path: Path) -> KnowledgeBaseManager:
    root = tmp_path / "data" / "dailynote"
    store = tmp_path / "VectorStore"
    root.mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)

    kb = KnowledgeBaseManager(
        {
            "root_path": str(root),
            "store_path": str(store),
            "dimension": 4,
        }
    )
    kb.db = sqlite3.connect(store / "knowledge_base.sqlite", check_same_thread=False)
    kb._init_schema()
    kb.tag_index = _DummyIndex()
    return kb


def test_delete_memory_by_path_cleans_relations(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None

    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (1, ?, 'DiaryA', 'c1', 1, 1, 1)",
        ("DiaryA/2026-01-01.md",),
    )
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (101, 1, 'chunk-a', 0, ?)", (b"v",))
    kb.db.execute("INSERT INTO tags (id, name, vector) VALUES (201, 'tag-a', ?)", (b"tv",))
    kb.db.execute("INSERT INTO file_tags (file_id, tag_id) VALUES (1, 201)")
    kb.db.commit()

    diary_idx = _DummyIndex()
    kb.diary_indices["DiaryA"] = diary_idx

    result = kb.delete_memories(file_paths=["DiaryA/2026-01-01.md"])

    assert result["deleted_files"] == 1
    assert result["deleted_chunks"] == 1
    assert result["deleted_file_tags"] == 1
    assert result["deleted_tags"] == 1
    assert diary_idx.removed == [101]

    file_count = kb.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunk_count = kb.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    rel_count = kb.db.execute("SELECT COUNT(*) FROM file_tags").fetchone()[0]
    tag_count = kb.db.execute("SELECT COUNT(*) FROM tags").fetchone()[0]

    assert file_count == 0
    assert chunk_count == 0
    assert rel_count == 0
    assert tag_count == 0


def test_delete_memory_dry_run_keeps_data(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None

    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (1, ?, 'DiaryA', 'c1', 1, 1, 1)",
        ("DiaryA/2026-01-01.md",),
    )
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (101, 1, 'chunk-a', 0, ?)", (b"v",))
    kb.db.commit()

    result = kb.delete_memories(file_paths=["DiaryA/2026-01-01.md"], dry_run=True)

    assert result["dry_run"] is True
    assert result["matched_files"] == 1

    file_count = kb.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunk_count = kb.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    assert file_count == 1
    assert chunk_count == 1


def test_delete_memory_by_diary_removes_all_files(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None

    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (1, ?, 'DiaryA', 'c1', 1, 1, 1)",
        ("DiaryA/2026-01-01.md",),
    )
    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (2, ?, 'DiaryA', 'c2', 1, 1, 1)",
        ("DiaryA/2026-01-02.md",),
    )
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (101, 1, 'chunk-a', 0, ?)", (b"v",))
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (102, 2, 'chunk-b', 0, ?)", (b"v",))
    kb.db.commit()

    diary_idx = _DummyIndex()
    kb.diary_indices["DiaryA"] = diary_idx

    result = kb.delete_memories(diary_name="DiaryA")

    assert result["deleted_files"] == 2
    assert set(diary_idx.removed) == {101, 102}

    file_count = kb.db.execute("SELECT COUNT(*) FROM files WHERE diary_name='DiaryA'").fetchone()[0]
    assert file_count == 0


def test_reconcile_missing_files_removes_stale_db_records(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None

    diary_idx = _DummyIndex()
    kb.diary_indices["DiaryA"] = diary_idx

    real_file = tmp_path / "data" / "dailynote" / "DiaryA" / "2026-01-01.md"
    real_file.parent.mkdir(parents=True, exist_ok=True)
    real_file.write_text("hello", encoding="utf-8")

    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (1, ?, 'DiaryA', 'c1', 1, 1, 1)",
        ("DiaryA/2026-01-01.md",),
    )
    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (2, ?, 'DiaryA', 'c2', 1, 1, 1)",
        ("DiaryA/missing.md",),
    )
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (101, 1, 'keep', 0, ?)", (b"v",))
    kb.db.execute("INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (102, 2, 'gone', 0, ?)", (b"v",))
    kb.db.commit()

    result = kb.reconcile_missing_files(dry_run=False)

    assert result["missing_files"] == 1
    assert result["deleted_files"] == 1

    remaining = kb.db.execute("SELECT path FROM files ORDER BY id").fetchall()
    assert remaining == [("DiaryA/2026-01-01.md",)]
    assert diary_idx.removed == [102]


def test_idle_eviction_saves_and_unloads_diary_index(tmp_path: Path):
    kb = _build_kb(tmp_path)

    diary_idx = _DummyIndex()
    save_timer = _DummyTimer()
    kb.diary_indices["DiaryA"] = diary_idx
    kb._save_timers["DiaryA"] = save_timer
    kb.diary_index_last_used = {"DiaryA": 0}
    kb.config["index_idle_ttl"] = 1

    kb._evict_idle_indices(now=10)

    assert "DiaryA" not in kb.diary_indices
    assert "DiaryA" not in kb.diary_index_last_used
    assert save_timer.cancelled is True
    assert len(diary_idx.saved_paths) == 1
    assert diary_idx.saved_paths[0].endswith(".usearch")
