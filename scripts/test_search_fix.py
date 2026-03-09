"""Quick smoke test for the search() None-diary fix."""
import asyncio
import sys
sys.path.insert(0, ".")

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path("config.env"))

from tagmemo.knowledge_base import KnowledgeBaseManager
import numpy as np


async def main():
    kb = KnowledgeBaseManager()
    await kb.initialize()

    q = np.random.randn(4096).astype(np.float32)
    q /= np.linalg.norm(q)
    vec = q.tolist()

    # Test 1: search(None, vector, k) - previously broken
    r1 = await kb.search(None, vec, 5, 0.0, [])
    print(f"search(None, vector): {len(r1)} results")
    if r1:
        print(f"  First: score={r1[0]['score']:.4f}, source={r1[0]['sourceFile']}")

    # Test 2: search(vector, k) - alternate call
    r2 = await kb.search(vec, 5, 0.0, [])
    print(f"search(vector): {len(r2)} results")

    # Test 3: search('User', vector, k)
    r3 = await kb.search("User", vec, 5, 0.0, [])
    print(f'search("User", vector): {len(r3)} results')

    await kb.shutdown()
    print("\nAll search paths verified!")


asyncio.run(main())
