from __future__ import annotations

import sqlite3
from pathlib import Path

from tagmemo.knowledge_base import KnowledgeBaseManager


class _DummyIndex:
    def __init__(self) -> None:
        self.removed: list[int] = []

    def remove(self, key: int) -> None:
        self.removed.append(key)

    def add(self, key, vec) -> None:
        return None

    def save(self, path: str) -> None:
        return None


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
