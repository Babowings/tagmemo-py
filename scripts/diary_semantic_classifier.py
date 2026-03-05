#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from tagmemo.embedding_utils import get_embeddings_batch
from tagmemo.knowledge_base import KnowledgeBaseManager


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    dot = float(np.dot(vec_a, vec_b))
    norm_a = float(np.linalg.norm(vec_a))
    norm_b = float(np.linalg.norm(vec_b))
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_aggregate_vector(vectors: list[np.ndarray]) -> np.ndarray | None:
    if not vectors:
        return None
    avg = np.mean(np.vstack(vectors), axis=0)
    norm = np.linalg.norm(avg)
    if norm > 1e-9:
        avg = avg / norm
    return avg.astype(np.float32)


@dataclass
class MoveTask:
    file_id: int
    old_rel_path: str
    file_name: str
    score: float
    target_diary: str
    new_rel_path: str


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="VCP 日记语义分类工具 (Python 对齐版)")
    parser.add_argument("--source", required=True, help="源日记本目录名")
    parser.add_argument("--categories", required=True, help="分类列表，逗号分隔")
    parser.add_argument("--filter", default="", help="分类名净化词")
    parser.add_argument("--threshold", type=float, default=0.3, help="相似度阈值")
    parser.add_argument("--api-url", default="", help="覆盖 embedding API 地址")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / "config.env")

    root_path = Path(os.environ.get("KNOWLEDGEBASE_ROOT_PATH", str(project_root / "data" / "dailynote"))).resolve()
    store_path = Path(os.environ.get("KNOWLEDGEBASE_STORE_PATH", str(project_root / "VectorStore"))).resolve()
    db_path = store_path / "knowledge_base.sqlite"
    dim = int(os.environ.get("VECTORDB_DIMENSION", "3072"))

    if not db_path.exists():
        print(f"[SemanticClassifier] database not found: {db_path}")
        return 1

    categories_raw = [c.strip() for c in args.categories.replace("，", ",").split(",") if c.strip()]
    categories_clean = [c.replace(args.filter, "").strip() if args.filter else c for c in categories_raw]

    embed_cfg = {
        "api_key": os.environ.get("API_Key", ""),
        "api_url": args.api_url or os.environ.get("API_URL", ""),
        "model": os.environ.get("WhitelistEmbeddingModel", "text-embedding-3-small"),
    }
    category_vectors_raw = await get_embeddings_batch(categories_clean, embed_cfg)
    category_vectors = [np.array(v, dtype=np.float32) for v in category_vectors_raw]

    conn = sqlite3.connect(db_path)
    files = conn.execute("SELECT id, path FROM files WHERE diary_name = ?", (args.source,)).fetchall()
    if not files:
        print("[SemanticClassifier] no files in source diary")
        conn.close()
        return 0

    chunks_stmt = conn.cursor()
    tasks: list[MoveTask] = []

    for file_id, rel_path in files:
        rows = chunks_stmt.execute(
            "SELECT vector FROM chunks WHERE file_id = ? ORDER BY chunk_index ASC",
            (file_id,),
        ).fetchall()
        if not rows:
            continue

        vectors = [
            np.frombuffer(r[0], dtype=np.float32, count=dim).astype(np.float32)
            for r in rows
            if r[0] is not None
        ]
        file_vec = compute_aggregate_vector(vectors)
        if file_vec is None:
            continue

        best_idx = -1
        best_score = -1.0
        for i, cvec in enumerate(category_vectors):
            score = cosine_similarity(file_vec, cvec)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx >= 0 and best_score >= args.threshold:
            file_name = Path(rel_path).name
            target_diary = categories_raw[best_idx]
            new_rel_path = str(Path(target_diary) / file_name).replace("\\", "/")
            tasks.append(MoveTask(file_id, rel_path, file_name, best_score, target_diary, new_rel_path))

    conn.close()

    if not tasks:
        print("[SemanticClassifier] no move candidates above threshold")
        return 0

    print("[SemanticClassifier] planned moves:")
    for t in tasks:
        print(f"  {t.file_name} -> {t.target_diary} ({t.score:.3f})")

    if args.dry_run:
        print("[SemanticClassifier] dry-run completed")
        return 0

    kb = KnowledgeBaseManager()
    await kb.initialize()

    moved_new_abs_paths: list[Path] = []
    for t in tasks:
        src_abs = root_path / t.old_rel_path
        dst_abs = root_path / t.new_rel_path
        dst_abs.parent.mkdir(parents=True, exist_ok=True)
        if dst_abs.exists():
            print(f"[SemanticClassifier] skip existing target: {t.new_rel_path}")
            continue
        if not src_abs.exists():
            print(f"[SemanticClassifier] skip missing source: {t.old_rel_path}")
            continue

        shutil.move(str(src_abs), str(dst_abs))
        kb.delete_memories(file_paths=[t.old_rel_path], cleanup_orphans=True)
        kb._on_file_event(str(dst_abs))
        moved_new_abs_paths.append(dst_abs)

    if moved_new_abs_paths:
        await asyncio.sleep(2.2)
        await kb._flush_batch()

    await kb.shutdown()
    print(f"[SemanticClassifier] moved {len(moved_new_abs_paths)} files")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
