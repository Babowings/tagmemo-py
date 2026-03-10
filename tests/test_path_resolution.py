from __future__ import annotations

from pathlib import Path

from tagmemo.engine import TagMemoEngine
from tagmemo.knowledge_base import KnowledgeBaseManager


def test_engine_resolves_relative_paths_against_project_root():
    engine = TagMemoEngine(
        {
            "root_path": "./data/dailynote",
            "store_path": "./VectorStore",
        }
    )

    project_root = Path(__file__).resolve().parent.parent

    assert engine.config["root_path"] == str((project_root / "data" / "dailynote").resolve())
    assert engine.config["store_path"] == str((project_root / "VectorStore").resolve())


def test_knowledge_base_resolves_relative_paths_against_project_root():
    kb = KnowledgeBaseManager(
        {
            "root_path": "./data/dailynote",
            "store_path": "./VectorStore",
            "dimension": 4,
        }
    )

    project_root = Path(__file__).resolve().parent.parent

    assert kb.config["root_path"] == str((project_root / "data" / "dailynote").resolve())
    assert kb.config["store_path"] == str((project_root / "VectorStore").resolve())