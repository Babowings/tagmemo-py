# TagMemo-py 重构方案 — 从 Node.js + Rust 到纯 Python

## 一、重构目标

将 TagMemo（Node.js + Rust N-API 混合项目，共 ~4,720 行 JS + 642 行 Rust）重构为**纯 Python** 项目，保持所有核心 RAG 算法和 API 行为一致。

---

## 二、可行性分析

### 2.1 语言替换总览

| 原技术栈组件 | 行数 | Python 替代方案 | 可行性 |
|-------------|------|----------------|--------|
| Express (HTTP server) | app.js 369 行 | FastAPI + Uvicorn | ✅ 完全替代，且更简洁 |
| better-sqlite3 (同步 SQLite) | KBM 大量使用 | sqlite3 (标准库，同步) | ✅ 原生支持，保持同步模型与原版一致 |
| rust-vexus-lite (HNSW 向量索引 + SVD + Gram-Schmidt) | 642 行 Rust | usearch (Python binding) + numpy/scipy | ✅ 见 2.2 详析 |
| chokidar (文件监听) | KBM, Engine | watchdog | ✅ 成熟替代 |
| @dqbd/tiktoken (Token 计数) | TextChunker, EmbeddingUtils | tiktoken (OpenAI 官方 Python 库) | ✅ 同源库 |
| axios / node-fetch (HTTP 客户端) | Embedding, Reranker | httpx (async) | ✅ 完全替代 |
| cheerio (HTML 解析) | TextSanitizer | BeautifulSoup4 | ✅ 完全替代 |
| dayjs + timezone | TimeParser, Engine | datetime + python-dateutil / zoneinfo | ✅ 标准库足够 |
| crypto (SHA-256, Hash) | 多处 | hashlib (标准库) | ✅ 原生支持 |
| Float32Array / Buffer (二进制向量) | KBM, EPA, Pyramid | numpy ndarray (float32) | ✅ 更自然、更高效 |
| cors | app.js | FastAPI CORSMiddleware | ✅ 内置 |
| dotenv | app.js | python-dotenv | ✅ 完全替代 |

**结论：所有组件均有成熟的 Python 替代方案，不存在不可行的技术障碍。**

### 2.2 Rust 模块替换方案详析

rust-vexus-lite (642 行 Rust) 提供 4 类能力，逐一分析替换方案：

#### ① HNSW 向量索引 (`usearch` crate → `usearch` Python)

| 原 Rust 方法 | Python 替代 | 说明 |
|-------------|------------|------|
| `new VexusIndex(dim, cap)` | `usearch.Index(ndim=dim, metric='l2sq', dtype='f32')` | usearch 官方提供 Python 绑定 (pip install usearch)，底层同为 C++ 核心 |
| `.load(path)` | `index.load(path)` | 直接支持 |
| `.save(path)` | `index.save(path)` | 直接支持 |
| `.add(id, vector)` | `index.add(id, vector)` | 接受 numpy array |
| `.search(query, k)` | `index.search(query, k)` | 返回 (keys, distances) |
| `.remove(id)` | `index.remove(id)` | 直接支持 |
| `recoverFromSqlite()` | Python 直接读 SQLite + 批量 add | 比 Rust 实现更简单 |

**关键结论**：rust-vexus-lite 内部直接调用 `usearch` crate 的 `Index::save()` / `Index::load()`，而 Python `usearch` 包与 Rust crate 共用同一 C++ 核心，因此 `.usearch` 文件格式在理论上兼容。但需要注意：
- 原版使用 `MetricKind::L2sq`（见 lib.rs:73），Python 版必须使用 `metric='l2sq'` 才能保证评分语义一致（`score = 1.0 - l2sq_distance`）
- **建议首次启动时验证加载**，如果失败则自动从 SQLite `recover_from_sqlite()` 重建索引
- 索引性能接近原生（C++ 核心，Python 只是薄封装）
- API 几乎一一映射

#### ② SVD 分解 (`nalgebra` → `numpy.linalg.svd`)

```python
# Rust 原版
matrix = DMatrix::from_row_slice(n, dim, vec_slice);
let svd = matrix.svd(false, true);

# Python 替代
import numpy as np
matrix = np.array(vectors, dtype=np.float32).reshape(n, dim)
U, S, Vt = np.linalg.svd(matrix, full_matrices=False)
```

numpy 的 SVD 基于 LAPACK，性能优于 nalgebra 的纯 Rust 实现。**替换后性能反而可能提升。**

#### ③ Gram-Schmidt 正交投影 (`compute_orthogonal_projection`)

原 Rust 实现是标准 Gram-Schmidt，约 40 行。Python + numpy 等价实现：

```python
def orthogonal_projection(query: np.ndarray, tag_vectors: np.ndarray):
    basis = []
    coefficients = np.zeros(len(tag_vectors))
    projection = np.zeros_like(query, dtype=np.float64)
    
    for i, tag_vec in enumerate(tag_vectors):
        v = tag_vec.astype(np.float64).copy()
        for u in basis:
            v -= np.dot(v, u) * u
        mag = np.linalg.norm(v)
        if mag > 1e-6:
            v /= mag
            coeff = np.dot(query.astype(np.float64), v)
            coefficients[i] = abs(coeff)
            projection += coeff * v
            basis.append(v)
    
    residual = query.astype(np.float64) - projection
    return projection, residual, coefficients
```

numpy 的向量化操作使代码更简洁，性能上对于常规维度（1536-3072）差异可忽略。

#### ④ 握手分析 + EPA 投影 (`compute_handshakes`, `project`)

纯数学运算（差值向量、点积、概率、熵），numpy 一行搞定：

```python
# Rust .project() 等价
centered = (vector - mean).astype(np.float64)
projections = basis @ centered  # 矩阵乘法
energies = projections ** 2
total_energy = energies.sum()
probabilities = energies / (total_energy + 1e-12)
entropy = -np.sum(probabilities * np.log2(probabilities + 1e-9))
```

**总结：Rust 模块的全部 642 行可用 ~150 行 Python + numpy 替代，且利用 numpy 的 BLAS 后端，数值计算性能相当甚至更优。**

### 2.3 性能评估

| 组件 | JS 版性能 | Python 版预期性能 | 说明 |
|------|----------|------------------|------|
| HNSW 搜索 | Rust (usearch C++ core) | Python (同 usearch C++ core) | **相同** — 底层同一引擎 |
| SVD 分解 | nalgebra (纯 Rust) | numpy (LAPACK/OpenBLAS) | **Python 更快** — LAPACK 高度优化 |
| Gram-Schmidt | Rust 手写循环 | numpy 向量化 | **相当** — 维度不大时差异微小 |
| HTTP 请求处理 | Express (单线程) | FastAPI + Uvicorn (async) | **Python 更优** — 原生异步 |
| SQLite 操作 | better-sqlite3 (同步 C binding) | sqlite3 (同步 C binding) | **相同** — 均为同步操作，行为一致 |
| Embedding API 调用 | axios | httpx async | **Python 更优** — 并发请求 |

**结论：性能无退化风险。向量搜索核心不变，数值计算有 numpy 加速，HTTP 层有 async 加速。**

### 2.4 Python 版额外优势

1. **部署更简单** — 无需编译 Rust，无需平台特定的 .node 二进制
2. **生态更丰富** — 可直接集成 LangChain、LlamaIndex、Sentence Transformers 等
3. **调试更方便** — numpy 数组可直接可视化、Jupyter 交互调试
4. **扩展更容易** — Python ML 生态（scikit-learn、faiss 等）唾手可得

---

## 三、Python 依赖清单

### requirements.txt

```
# === Web 框架 ===
fastapi>=0.115.0
uvicorn[standard]>=0.32.0

# === 向量索引 (替代 rust-vexus-lite) ===
usearch>=2.12.0

# === 数值计算 (替代 Float32Array + nalgebra) ===
numpy>=1.26.0

# === 数据库 ===
# sqlite3 为标准库，无需安装。保持同步模式与原版 better-sqlite3 行为一致。
# FastAPI 路由中通过 run_in_executor 调用同步 DB 操作。

# === HTTP 客户端 (替代 axios / node-fetch) ===
httpx>=0.27.0

# === Token 计数 (替代 @dqbd/tiktoken) ===
tiktoken>=0.7.0

# === HTML 解析 (替代 cheerio) ===
beautifulsoup4>=4.12.0

# === 文件监听 (替代 chokidar) ===
watchdog>=4.0.0

# === 环境变量 ===
python-dotenv>=1.0.0

# === 时间处理 ===
python-dateutil>=2.9.0
```

> **Python 版本要求：3.10+**（使用 `zoneinfo`、`match/case`、`list[dict]` 类型标注等特性）

### npm → pip 依赖映射

| npm 包 | pip 包 | 说明 |
|--------|--------|------|
| `express` | `fastapi` + `uvicorn` | Python 最流行的异步 Web 框架 |
| `cors` | `fastapi.middleware.cors` | FastAPI 内置 |
| `better-sqlite3` | `sqlite3` (标准库，同步) | Python 自带，保持同步事务模型 |
| `axios` / `node-fetch` | `httpx` | 支持同步/异步，类似 axios API |
| `@dqbd/tiktoken` | `tiktoken` | OpenAI 官方同源库 |
| `cheerio` | `beautifulsoup4` | 经典 HTML 解析库 |
| `chokidar` | `watchdog` | 跨平台文件监听 |
| `dayjs` | `datetime` + `python-dateutil` | 标准库 + 增强时区处理 |
| `dotenv` | `python-dotenv` | 同名同功能 |
| `crypto` | `hashlib` | Python 标准库 |
| `rust-vexus-lite` | `usearch` + `numpy` | 见 2.2 详析 |

---

## 四、项目结构设计

```
TagMemo-py/
├── tagmemo/                        Python 包
│   ├── __init__.py
│   ├── engine.py                   TagMemoEngine (核心编排)
│   ├── knowledge_base.py           KnowledgeBaseManager (向量库 + TagBoost)
│   ├── epa.py                      EPAModule (加权 PCA/SVD)
│   ├── residual_pyramid.py         ResidualPyramid (Gram-Schmidt)
│   ├── result_deduplicator.py      ResultDeduplicator (SVD 去重)
│   ├── embedding_service.py        EmbeddingService (API + 缓存)
│   ├── embedding_utils.py          批量嵌入工具
│   ├── context_vector.py           ContextVectorManager
│   ├── semantic_groups.py          SemanticGroupManager
│   ├── reranker.py                 Reranker (断路器 + 批次)
│   ├── time_parser.py              TimeExpressionParser
│   ├── time_expressions.py         时间表达式配置数据
│   ├── text_sanitizer.py           TextSanitizer
│   ├── text_chunker.py             TextChunker
│   └── vector_index.py             VectorIndex 封装 (usearch 适配层)
│
├── app.py                          FastAPI 服务 + CLI 入口
├── config.env                      环境配置
├── rag_params.json                 算法参数 (热加载)
├── requirements.txt                Python 依赖
├── pyproject.toml                  项目元数据 + 构建配置
├── README.md
├── REFACTORING_PLAN.md             本文档
│
├── data/dailynote/                 知识库文档
├── data/semantic_groups/           语义组配置 + 编辑同步 + 向量缓存
├── VectorStore/                    向量索引 + SQLite 存储
└── tests/                          测试
    ├── test_engine.py
    ├── test_knowledge_base.py
    ├── test_epa.py
    └── ...
```

### 4.1 与 JS 版模块对照

| JS 文件 | Python 文件 | 说明 |
|---------|------------|------|
| `app.js` (369) | `app.py` | FastAPI 替代 Express |
| `lib/TagMemoEngine.js` (780) | `tagmemo/engine.py` | 核心引擎 |
| `lib/KnowledgeBaseManager.js` (925) | `tagmemo/knowledge_base.py` | 向量 CRUD + TagBoost |
| `lib/EPAModule.js` (486) | `tagmemo/epa.py` | EPA 分析 |
| `lib/ResidualPyramid.js` (392) | `tagmemo/residual_pyramid.py` | 残差金字塔 |
| `lib/ResultDeduplicator.js` (151) | `tagmemo/result_deduplicator.py` | SVD 去重 |
| `lib/EmbeddingService.js` (162) | `tagmemo/embedding_service.py` | Embedding 缓存 |
| `lib/EmbeddingUtils.js` (110) | `tagmemo/embedding_utils.py` | 批量嵌入 |
| `lib/ContextVectorManager.js` (255) | `tagmemo/context_vector.py` | 上下文向量 |
| `lib/SemanticGroupManager.js` (305) | `tagmemo/semantic_groups.py` | 语义组 |
| `lib/Reranker.js` (262) | `tagmemo/reranker.py` | Rerank 重排 |
| `lib/TimeExpressionParser.js` (214) | `tagmemo/time_parser.py` | 时间解析 |
| `lib/timeExpressions.config.js` (90) | `tagmemo/time_expressions.py` | 时间配置 |
| `lib/TextSanitizer.js` (123) | `tagmemo/text_sanitizer.py` | 文本清洗 |
| `lib/TextChunker.js` (103) | `tagmemo/text_chunker.py` | 文本分块 |
| `rust-vexus-lite/` (642 Rust) | `tagmemo/vector_index.py` | usearch 适配层 |

### 4.2 新增 `vector_index.py` 适配层

为 JS 版的 `VexusIndex` 创建一个 Python 封装，保持相同的接口语义：

```python
"""vector_index.py — usearch 适配层，替代 rust-vexus-lite"""
import numpy as np
from usearch.index import Index
from pathlib import Path
import sqlite3

class VectorIndex:
    """对 usearch.Index 的封装，1:1 对应原 VexusIndex API"""
    
    def __init__(self, dim: int, capacity: int = 10000):
        self.dim = dim
        self.index = Index(ndim=dim, metric='l2sq', dtype='f32')
        self.index.reserve(capacity)
    
    @classmethod
    def load(cls, path: str, dim: int, capacity: int = 10000,
             db_path: str = None, table_type: str = None) -> 'VectorIndex':
        """加载索引文件。如果加载失败且提供了 db_path，自动从 SQLite 重建。"""
        instance = cls.__new__(cls)
        instance.dim = dim
        try:
            instance.index = Index.restore(path)
        except Exception:
            # Fallback: 从 SQLite 重建索引
            instance.index = Index(ndim=dim, metric='l2sq', dtype='f32')
            instance.index.reserve(capacity)
            if db_path:
                count = instance.recover_from_sqlite(db_path, table_type or 'tags')
                print(f'[VectorIndex] Rebuilt index from SQLite: {count} vectors')
            return instance
        if instance.index.capacity < capacity:
            instance.index.reserve(capacity)
        return instance
    
    def save(self, path: str):
        """原子写入：先写临时文件，再 rename（与 Rust 版 lib.rs:132-140 一致）"""
        import os
        temp_path = f"{path}.tmp"
        self.index.save(temp_path)
        os.replace(temp_path, path)  # 原子替换，跨平台
    
    def add(self, id: int, vector: np.ndarray):
        # 自动扩容（与 Rust 版 lib.rs:166-170 一致）
        if len(self.index) + 1 >= self.index.capacity:
            new_cap = int(self.index.capacity * 1.5)
            self.index.reserve(new_cap)
        self.index.add(id, vector.astype(np.float32))
    
    def remove(self, id: int):
        self.index.remove(id)
    
    def search(self, query: np.ndarray, k: int) -> list[dict]:
        matches = self.index.search(query.astype(np.float32), k)
        # score = 1.0 - l2sq_dist，与原版 Rust (lib.rs:252) 完全一致。
        # 对于归一化向量，l2sq ∈ [0, 4]，score ∈ [-3, 1]。
        # 原版就是这个公式，结果仅用于排序（越大越好），绝对值不影响功能。
        return [
            {"id": int(key), "score": 1.0 - float(dist)}
            for key, dist in zip(matches.keys, matches.distances)
        ]
    
    def stats(self) -> dict:
        return {
            "total_vectors": len(self.index),
            "dimensions": self.dim,
            "capacity": self.index.capacity,
        }
    
    def recover_from_sqlite(self, db_path: str, table_type: str,
                            filter_diary_name: str = None) -> int:
        conn = sqlite3.connect(db_path)
        if table_type == "tags":
            rows = conn.execute(
                "SELECT id, vector FROM tags WHERE vector IS NOT NULL"
            ).fetchall()
        elif table_type == "chunks" and filter_diary_name:
            rows = conn.execute(
                "SELECT c.id, c.vector FROM chunks c JOIN files f ON c.file_id = f.id "
                "WHERE f.diary_name = ? AND c.vector IS NOT NULL",
                (filter_diary_name,)
            ).fetchall()
        else:
            conn.close()
            return 0
        
        count = 0
        expected_bytes = self.dim * 4  # float32 = 4 bytes
        for row_id, vector_blob in rows:
            if vector_blob and len(vector_blob) == expected_bytes:
                vec = np.frombuffer(vector_blob, dtype=np.float32).copy()
                self.add(row_id, vec)
                count += 1
        conn.close()
        return count
    
    # ===== 数值计算方法 (替代 VexusIndex 的 Rust 数值方法) =====
    
    @staticmethod
    def compute_svd(vectors: np.ndarray, max_k: int) -> dict:
        """替代 Rust compute_svd。
        注意：EPA 实际使用 Gram 矩阵 + eigh 而非直接对原始数据做 SVD，
        此方法保留作为通用工具函数（如 ResultDeduplicator 可能使用）。"""
        U, S, Vt = np.linalg.svd(vectors.astype(np.float64), full_matrices=False)
        k = min(len(S), max_k)
        return {
            "u": Vt[:k].flatten().tolist(),  # 主成分 (k × dim)
            "s": S[:k].tolist(),
            "k": k,
            "dim": vectors.shape[1],
        }
    
    @staticmethod
    def compute_orthogonal_projection(query: np.ndarray,
                                       tag_vectors: np.ndarray) -> dict:
        """替代 Rust compute_orthogonal_projection (Gram-Schmidt)"""
        dim = len(query)
        q = query.astype(np.float64)
        basis = []
        coefficients = np.zeros(len(tag_vectors))
        projection = np.zeros(dim, dtype=np.float64)
        
        for i, tag_vec in enumerate(tag_vectors):
            v = tag_vec.astype(np.float64).copy()
            for u in basis:
                v -= np.dot(v, u) * u
            mag = np.linalg.norm(v)
            if mag > 1e-6:
                v /= mag
                coeff = np.dot(q, v)
                coefficients[i] = abs(coeff)
                projection += coeff * v
                basis.append(v)
        
        residual = q - projection
        return {
            "projection": projection.tolist(),
            "residual": residual.tolist(),
            "basis_coefficients": coefficients.tolist(),
        }
    
    @staticmethod
    def compute_handshakes(query: np.ndarray,
                           tag_vectors: np.ndarray) -> dict:
        """替代 Rust compute_handshakes"""
        deltas = query.astype(np.float64) - tag_vectors.astype(np.float64)
        magnitudes = np.linalg.norm(deltas, axis=1)
        safe_mags = np.where(magnitudes > 1e-9, magnitudes, 1.0)
        directions = deltas / safe_mags[:, np.newaxis]
        directions[magnitudes <= 1e-9] = 0.0
        return {
            "magnitudes": magnitudes.tolist(),
            "directions": directions.flatten().tolist(),
        }
    
    @staticmethod
    def project(vector: np.ndarray, basis: np.ndarray,
                mean: np.ndarray) -> dict:
        """替代 Rust .project() — EPA 投影"""
        centered = (vector - mean).astype(np.float64)
        projections = basis.astype(np.float64) @ centered
        energies = projections ** 2
        total_energy = energies.sum()
        
        if total_energy > 1e-12:
            probabilities = energies / total_energy
            entropy = -np.sum(probabilities[probabilities > 1e-9]
                              * np.log2(probabilities[probabilities > 1e-9]))
        else:
            probabilities = np.zeros_like(projections)
            entropy = 0.0
        
        return {
            "projections": projections.tolist(),
            "probabilities": probabilities.tolist(),
            "entropy": float(entropy),
            "total_energy": float(total_energy),
        }
```

---

## 五、逐模块重构方案

### 5.1 app.py (← app.js)

| JS | Python |
|----|--------|
| `express()` + `app.use(cors())` | `FastAPI()` + `CORSMiddleware` |
| `app.get('/status', ...)` | `@app.get("/status")` |
| `app.post('/v1/chat/completions', ...)` | `@app.post("/v1/chat/completions")` |
| `node-fetch` 转发请求 | `httpx.AsyncClient` 转发 |
| SSE 流式 `response.body.pipe(res)` | `httpx` streaming + `StreamingResponse` 字节流透传（见下文） |
| `express.json({ limit: '10mb' })` | Uvicorn / 中间件限制请求体大小 |
| `readline` CLI | `asyncio` + `aioconsole` 或 `click` CLI |
| `process.argv.includes('--cli')` | `typer` 或 `argparse` 子命令 |

**SSE 流式透传详解**：原版 `response.body.pipe(res)` 是将上游 LLM 的响应**原封不动地以字节流透传**给客戶端，而非自己生成 SSE 事件。Python 版用 `httpx` streaming + `StreamingResponse` 实现：
```python
async def proxy_stream(upstream_resp):
    async for chunk in upstream_resp.aiter_bytes():
        yield chunk
return StreamingResponse(proxy_stream(resp), media_type="text/event-stream", headers=headers)
```
**不使用 `sse_starlette` 生成事件**，因为实质是透传而非生成。原版通过 `X-TagMemo-Metrics` 自定义头附加元数据（app.js:211），Python 版需保留。

**请求体大小限制**：原版 `express.json({ limit: '10mb' })`。Python 版通过中间件或路由内检查 `len(await request.body()) > 10MB` 实现。

**其他 app.js 辅助逻辑**：
- `SYSTEM_PROMPT_TEMPLATE`（app.js:32-37）— 从环境变量加载，有默认中文模板
- `buildEnhancedMessages()`（app.js:223-247）— 将记忆注入 system prompt，需 1:1 翻译
- `findLastIndex()`（app.js:343-348）— Python 无 `list.findLastIndex()`，用 `next(i for i in range(len(arr)-1, -1, -1) if fn(arr[i]))` 实现

### 5.2 engine.py (← TagMemoEngine.js)

基本为 1:1 翻译，关键差异：

| JS 模式 | Python 模式 |
|---------|------------|
| `class TagMemoEngine { constructor() { ... } }` | `class TagMemoEngine: def __init__(self): ...` |
| `async query()` | `async def query()` (原生异步) |
| `Map` 缓存 | `dict`（保持插入序，Python 3.7+）。淘汰策略为 FIFO：`del cache[next(iter(cache))]`，与原版 `Map.keys().next().value` 一致。不使用 `cachetools.TTLCache`（其为 LRU 策略，与原版行为不同） |
| `chokidar.watch()` | `watchdog.Observer()` + `FileSystemEventHandler`。**注意**：watchdog 无 `ignoreInitial` 等价选项（不会为已有文件触发事件），需手动实现启动时全量扫描（`os.walk` 遍历所有 .md/.txt 文件） |
| `setInterval()` 定期清理 | `asyncio.create_task()` + `asyncio.sleep()` 循环 |
| `crypto.createHash('sha256')` | `hashlib.sha256()` |
| `new Float32Array(queryVector)` | `np.array(queryVector, dtype=np.float32)` |

**设计改进**：原版 `TagMemoEngine.js` 和 `KnowledgeBaseManager.js` 各自独立监听 `rag_params.json`，存在重复 watcher。Python 版统一由 `engine.py` 做一次 `watchdog` 监听，参数变更后同步给 `knowledge_base.py`。

### 5.3 knowledge_base.py (← KnowledgeBaseManager.js) — 最复杂

**核心变更：**

0. **启动时全量扫描（watchdog 差异）**  
   原版 `chokidar.watch(path, { ignoreInitial: !fullScanOnStartup })` 可在启动时自动为已有文件触发 `add` 事件。`watchdog` 无此功能，Python 版需在 watcher 启动前手动扫描：
   ```python
   if self.config['full_scan_on_startup']:
       for root, dirs, files in os.walk(self.config['root_path']):
           for f in files:
               if f.endswith(('.md', '.txt')):
                   self._handle_file(os.path.join(root, f))
   ```
   **这是必须实现的功能**，否则 Python 版启动后不会索引任何已有文档。

1. **VexusIndex → VectorIndex**  
   所有 `require('rust-vexus-lite')` 替换为 `from tagmemo.vector_index import VectorIndex`

   **多索引架构**：KBM 维护**多个 VectorIndex 实例**——一个全局 `tag_index` + 每个日记本一个 `chunk_index`。日记本索引懒加载（`_getOrLoadDiaryIndex()`，原版 KBM:203-226），用 `dict[str, VectorIndex]` 管理：
   ```python
   self.diary_indices: dict[str, VectorIndex] = {}
   
   def _get_or_load_diary_index(self, diary_name: str) -> VectorIndex:
       if diary_name in self.diary_indices:
           return self.diary_indices[diary_name]
       safe_name = hashlib.md5(diary_name.encode()).hexdigest()
       idx = self._load_or_build_index(f'diary_{safe_name}', 50000, 'chunks', diary_name)
       self.diary_indices[diary_name] = idx
       return idx
   ```

2. **Buffer/Float32Array → numpy**  
   ```python
   # JS: new Float32Array(vector) → Buffer.from(...) → index.search(buffer, k)
   # Python: np.array(vector, np.float32) → index.search(array, k)
   ```

3. **better-sqlite3 → sqlite3**  
   ```python
   # JS: const db = require('better-sqlite3')(path); db.prepare(sql).get(...)
   # Python: conn = sqlite3.connect(path); conn.execute(sql, ...).fetchone()
   ```
   **初始化 pragma**（原版 KBM:87-88）：
   ```python
   conn.execute("PRAGMA journal_mode=WAL")      # 并发读性能关键
   conn.execute("PRAGMA synchronous=NORMAL")     # 写入性能优化
   ```
   **数据库 Schema**（原版 KBM:158-198，5 表 + 4 索引）：
   - `files` (id, path, diary_name, checksum, mtime, size, updated_at)
   - `chunks` (id, file_id, chunk_index, content, vector BLOB)
   - `tags` (id, name UNIQUE, vector BLOB)
   - `file_tags` (file_id, tag_id, PRIMARY KEY)
   - `kv_store` (key PRIMARY KEY, value, vector BLOB)
   - 索引：idx_chunks_file_id, idx_files_path, idx_files_diary, idx_file_tags_tag
   
   Python 版与 JS 版共用同一 schema。全新初始化时需执行 `CREATE TABLE IF NOT EXISTS` 语句。
   
   **注意事项**：
   - `better-sqlite3` 的 `prepare()` 会预编译并缓存 SQL 语句，高频逐条查询有性能优势。Python `sqlite3` 无显式预编译 API，高频查询应批量化（`WHERE id IN (?, ?, ...)`）代替逐条查询
   - **事务边界**：原版 `db.transaction(() => { ... })()` 在事务内只做 SQLite 操作，返回值（更新/删除的 ID 列表）在事务外用于更新 VectorIndex。Python 版必须保持相同边界，避免在 `with conn:` 块内操作索引——否则索引操作失败而 SQLite 已提交会造成数据不一致

4. **向量 BLOB 读写**  
   ```python
   # 写入: vector.astype(np.float32).tobytes()
   # 读取: np.frombuffer(blob, dtype=np.float32).copy()  # 必须 .copy()!
   ```
   > ⚠️ **全局注意**：Python 从 SQLite BLOB 读取向量时，必须使用 `np.frombuffer(...).copy()`。`np.frombuffer` 返回只读数组，不 `.copy()` 会导致后续写操作抛出 `ValueError: assignment destination is read-only`。原版 JS 的 `new Float32Array(buf.buffer)` 创建的是可写视图，无此限制。所有从 SQLite 读取向量的地方（KBM、EPA、ResidualPyramid 等）均需遵守。

5. **TagBoost V3.7 — 核心算法 1:1 翻译**  
   所有 Float32Array 循环运算替换为 numpy 向量化运算：
   ```python
   # JS: for (let d = 0; d < dim; d++) result[d] += weight * tagVec[d]
   # Python: result += weight * tag_vec  # numpy broadcasting
   ```

### 5.4 epa.py (← EPAModule.js)

**核心变更：**

1. **Rust `.project()` → numpy 矩阵乘法**
   ```python
   projections = basis @ centered  # 替代 200 行 JS + Rust FFI
   ```

2. **Weighted PCA — 完整算法流程**

   原版 `_computeWeightedPCA` 是一个多步骤算法，不能简化为单纯的 `np.linalg.svd`：

   ```python
   def _compute_weighted_pca(self, cluster_data: dict) -> dict:
       vectors = cluster_data['vectors']   # n 个质心向量 (numpy)
       weights = cluster_data['weights']   # 簇大小
       n, dim = len(vectors), self.config['dimension']
       total_weight = sum(weights)
       
       # Step 1: 加权平均向量
       mean_vector = np.zeros(dim, dtype=np.float32)
       for i in range(n):
           mean_vector += vectors[i] * weights[i]
       mean_vector /= total_weight
       
       # Step 2: 加权中心化 (关键: sqrt(weight) * (v - mean))
       centered = np.array([
           np.sqrt(weights[i]) * (vectors[i] - mean_vector)
           for i in range(n)
       ], dtype=np.float64)
       
       # Step 3: 构建 Gram 矩阵 (n×n，而非 dim×dim)
       G = centered @ centered.T
       
       # Step 4: 特征分解 (替代原版的 Power Iteration + Deflation)
       eigenvalues, eigenvectors = np.linalg.eigh(G)
       # eigh 返回升序，反转为降序
       eigenvalues = eigenvalues[::-1]
       eigenvectors = eigenvectors[:, ::-1]
       
       # Step 5: 映射回原始空间 U_pca = X^T * v / sqrt(lambda)
       #         这是必须的，Gram 特征向量是 n 维，需要映射为 dim 维
       basis = []
       energies = []
       max_k = min(n, self.config['max_basis_dim'])
       for k in range(max_k):
           if eigenvalues[k] < 1e-6:
               break
           ev = eigenvectors[:, k]              # n-dim Gram eigenvector
           b = centered.T @ ev                  # dim-dim basis vector
           mag = np.linalg.norm(b)
           if mag > 1e-9:
               b /= mag                         # 归一化
           basis.append(b.astype(np.float32))
           energies.append(float(eigenvalues[k]))
       
       return {
           'U': basis,
           'S': energies,
           'meanVector': mean_vector,
           'labels': cluster_data['labels']
       }
   ```

   与原版对比：
   - 原版用 Power Iteration + Deflation + Re-orthogonalization (~150 行 JS)，Python 版用 `np.linalg.eigh` 一步代替
   - `eigh` 返回所有特征向量，比逾代方法更稳定、更快速
   - **Step 5 的映射步骤不可省略**，否则基底维度仅为 n 而非 dim

3. **K-Means 聚类** (原版 `_clusterTags`，~80 行)

   原版使用余弦相似度做分配、**质心归一化**、收敛检测。Python 版应保留这些特性：
   ```python
   # 质心更新后必须归一化（原版明确做了这一步）
   mag = np.linalg.norm(new_centroid)
   if mag > 1e-9:
       new_centroid /= mag
   ```
   可用 numpy 向量化实现，无需引入 scikit-learn

4. **EPA 缓存序列化** (`_saveToCache` / `_loadFromCache`)

   原版将 `Float32Array` 用 `Buffer.toString('base64')` 序列化为 base64 存入 `kv_store` 表。Python 版等价实现：
   ```python
   import base64
   # 保存: Float32Array → bytes → base64
   b64 = base64.b64encode(array.astype(np.float32).tobytes()).decode()
   # 加载: base64 → bytes → numpy (注意 .copy())
   array = np.frombuffer(base64.b64decode(b64), dtype=np.float32).copy()
   ```
   此缓存机制避免每次启动重算 PCA，是 EPA 模块的重要性能优化。

### 5.5 residual_pyramid.py (← ResidualPyramid.js)

**核心变更：**

`ResidualPyramid` 是一个**有状态类**，构造时注入 `tagIndex`（VectorIndex 实例）和 `db`（SQLite 连接），其 `analyze()` 方法的多层循环需要调用：
- `self.tag_index.search(residual_vector, k)` — 每层搜索最近 Tag
- `self.db.execute(...)` — 根据 ID 查询 Tag 向量
- `VectorIndex.compute_orthogonal_projection(...)` — Gram-Schmidt 投影（静态方法）
- `VectorIndex.compute_handshakes(...)` — 握手分析（静态方法）

数学计算部分放在 `VectorIndex` 的静态方法中，但 `ResidualPyramid` 本身作为有状态类必须持有 `tag_index` 和 `db` 引用。代码量从 JS 392 行预估减至 ~200 行。

**注意**：`ResultDeduplicator` 直接调用了 `EPAModule._computeWeightedPCA()` 和 `ResidualPyramid._computeOrthogonalProjection()`（原版是以 `_` 开头的“私有”方法）。Python 版建议将这两个方法暴露为公共方法（去掉 `_` 前缀）以明确其跨模块调用的设计意图。

### 5.6 其余模块 (≤5 影响度)

| 模块 | 主要变更 |
|------|---------|
| `embedding_service.py` | `axios` → `httpx`，`Map` → `dict`/`TTLCache`。**依赖 `text_chunker.py`**（原版 `EmbeddingService.js` 导入 `TextChunker.chunkText()`） |
| `embedding_utils.py` | `node-fetch` → `httpx`，`@dqbd/tiktoken` → `tiktoken`。并发工作池用 `asyncio.Semaphore` + `asyncio.gather()` 实现受控并发 |
| `context_vector.py` | `Float32Array` → `numpy`，`crypto` → `hashlib`。`Promise.all(tasks)` → `asyncio.gather(*tasks)` 实现并行异步消息处理 |
| `semantic_groups.py` | `fs/promises` → `pathlib` + `open()`，包含 `.edit.json` 同步机制和向量缓存目录管理。`saveGroups()` 需做原子写入（temp + `os.replace()`），与 Rust save 同理。Windows 上必须用 `os.replace()` 而非 `os.rename()` |
| `reranker.py` | `axios` → `httpx`，逻辑 1:1。URL 拼接用 `f"{self.url.rstrip('/')}/v1/rerank"` 而非 `urljoin()`（避免路径丢失问题） |
| `time_parser.py` | `dayjs` → `datetime` + `dateutil.relativedelta` + `zoneinfo`。dayjs 链式 API 较多，实际翻译工作量偏大 |
| `time_expressions.py` | 纯数据，直接翻译 |
| `text_sanitizer.py` | `cheerio` → `BeautifulSoup4`，正则不变 |
| `text_chunker.py` | `@dqbd/tiktoken` → Python `tiktoken`，API 相同 |
| `result_deduplicator.py` | 全 numpy 操作。直接调用 `EPAModule.compute_weighted_pca()` 和 `ResidualPyramid.compute_orthogonal_projection()`（公共方法） |

### 5.7 JS → Python 通用 API 差异备忘

以下 JS/Python API 差异在整个代码库中普遍存在，编码时需全局注意：

| JS 模式 | Python 等价 | 说明 |
|---------|------------|------|
| `str.match(/regex/g)` 返回数组或 `null` | `re.findall(pattern, text)` 返回列表（永不 `None`） | 无需 `\|\| []` 兜底 |
| `new URL('path', baseUrl).toString()` | `f"{base_url.rstrip('/')}/path"` | `urljoin` 对无尾 `/` 的 base 会丢失最后一级路径 |
| `Promise.all(tasks)` | `asyncio.gather(*tasks)` | 并行异步 |
| `setImmediate(() => ...)` | `threading.Timer(0, fn).start()` 或 `loop.call_soon()` | 延迟执行 |
| `arr.findLastIndex(fn)` | `next(i for i in range(len(a)-1,-1,-1) if fn(a[i]))` | Python 无内置 |
| `crypto.randomUUID()` | `str(uuid.uuid4())` | 随机 UUID |
| 文件原子写入（temp + rename） | `os.replace(temp, target)` | Windows 上 `os.rename()` 目标存在会报错 |

---

## 六、数据/索引兼容性

### 6.1 .usearch 索引文件

rust-vexus-lite 内部直接使用 `usearch` crate 的 `Index::save()` / `Index::load()`，而 Python `usearch` 包与该 crate 共用同一 C++ 核心，因此文件格式在理论上兼容。

**重要注意事项：**
- 原版使用 `MetricKind::L2sq`，Python 版必须使用 `metric='l2sq'` 才能保证匹配
- 首次启动时应进行验证性加载，如果加载失败则自动从 SQLite 重建索引
- 也可以保守地选择 Python 版首次启动时始终从 SQLite 重建，避免任何跨语言兼容性风险

### 6.2 SQLite 数据库

SQLite 是跨语言的标准格式。JS 版（better-sqlite3）和 Python 版（sqlite3）创建的数据库文件完全互通。

### 6.3 config.env / rag_params.json

纯文本/JSON 格式，无需迁移。Python 版直接复用同样的配置文件。

**结论：JS 版的持久化数据（SQLite + 配置文件）可直接被 Python 版使用。`.usearch` 向量索引理论上兼容，但建议 Python 版提供从 SQLite 自动重建索引的 fallback 机制，以确保健壮性。**

---

## 七、API 接口兼容性

Python 版将保持完全相同的 HTTP API 接口：

| 端点 | 方法 | 请求/响应格式 | 兼容性 |
|------|------|-------------|--------|
| `/v1/chat/completions` | POST | OpenAI 兼容 | ✅ 完全一致 |
| `/v1/memory/query` | POST | `{message, history, diaryName, useRerank}` | ✅ 完全一致 |
| `/status` | GET | `{status, engine, cache, rerank, uptime}` | ✅ 完全一致 |
| `/v1/cache/clear` | POST | `{status, message}` | ✅ 完全一致 |
| `/v1/params/reload` | POST | `{status, message}` | ✅ 完全一致 |

**作为上游 LLM 的代理行为也保持一致**，包括流式/非流式转发、`tagmemo_metrics` 附加字段、Debug 模式等。

---

## 八、重构顺序建议

按依赖关系从底层向上实现：

| 阶段 | 模块 | 依赖 | 预估行数 |
|------|------|------|---------|
| **Phase 1: 基础层** | | | |
| 1a | `vector_index.py` | usearch, numpy | ~150 |
| 1b | `text_sanitizer.py` | beautifulsoup4 | ~80 |
| 1c | `text_chunker.py` | tiktoken | ~70 |
| 1d | `time_expressions.py` | — | ~80 |
| 1e | `time_parser.py` | datetime, dateutil, zoneinfo | ~200 |
| **Phase 2: 数据层** | | | |
| 2a | `embedding_utils.py` | httpx, tiktoken | ~80 |
| 2b | `embedding_service.py` | httpx, text_chunker | ~120 |
| 2c | `epa.py` | numpy, vector_index | ~300 |
| 2d | `residual_pyramid.py` | numpy, vector_index | ~200 |
| 2e | `result_deduplicator.py` | numpy, epa, residual_pyramid | ~100 |
| **Phase 3: 业务层** | | | |
| 3a | `knowledge_base.py` | sqlite3, vector_index, epa, residual_pyramid, ... | ~650 |
| 3b | `context_vector.py` | hashlib, numpy | ~180 |
| 3c | `semantic_groups.py` | pathlib, hashlib | ~220 |
| 3d | `reranker.py` | httpx | ~180 |
| **Phase 4: 引擎层** | | | |
| 4a | `engine.py` | 所有上层模块 | ~500 |
| **Phase 5: 服务层** | | | |
| 5a | `app.py` | fastapi, engine | ~300 |
| **Phase 6: 项目配置** | | | |
| 6 | pyproject.toml, config.env, README.md, tests | — | — |

**预估总代码量：~3,000-3,500 行 Python**（相比 JS 4,720 + Rust 642 = 5,362 行，约减少 35-45%）。

代码减少原因：
- numpy 向量化替代手写循环，大幅减少数值计算代码
- Python 语法更简洁（无 `function`/`async function` 关键字冗余、无 `{}` 包裹）
- Rust FFI 胶水代码（Buffer 转换、错误处理）不再需要
- FastAPI 比 Express 更简洁（装饰器 vs 回调）

---

## 九、KBM 内部方法与 CLI 脚本翻译策略

以下是 `KnowledgeBaseManager.js` 和 `app.js` 中需要 1:1 翻译的重要内部方法，第五章未逐一列出但实际编码中不可遗漏：

| 方法/功能 | 原版位置 | Python 翻译策略 |
|-----------|---------|----------------|
| `_extractTags(content)` | KBM:870-888 | 正则提取 Tag 行 → 分割 → 黑名单/超级黑名单过滤。逻辑 1:1 |
| `_buildCooccurrenceMatrix()` | KBM:890-907 | SQL JOIN 构建 Tag 共现矩阵 → `dict[int, dict[int, int]]`。TagBoost V3.7 的基础数据 |
| `_handleDelete(filePath)` | KBM:834-847 | 文件删除后清理 SQLite 记录 + 从向量索引 remove |
| `_scheduleIndexSave()` + `_saveIndexToDisk()` | KBM:849-868 | 延迟批量保存机制。Python 版用 `threading.Timer`（因为 KBM 是同步模块，避免与 FastAPI asyncio 事件循环混用） |
| `_hydrateDiaryNameCacheSync()` | KBM:602-616 | 从 `kv_store` 表预热日记本名称向量缓存 |
| `_prepareTextForEmbedding()` | KBM:827-832 | 装饰性 Emoji 清理 + 空白规范化。保留为 KBM 内部方法（比 TextSanitizer 更轻量） |
| 文件忽略逻辑 | KBM:626-630 | `ignoreFolders` / `ignorePrefixes` / `ignoreSuffixes` 过滤 |
| `shutdown()` | KBM:910-921 + Engine:759-776 | 优雅关闭：保存未存盘索引、关闭 watcher、关闭 DB。Python 版在 FastAPI `lifespan` 事件中调用 |
| Tag 黑名单/超级黑名单 | KBM:882-886 | `TAG_BLACKLIST` (Set) + `TAG_BLACKLIST_SUPER` (正则) 过滤 |
| CLI 模式命令 | app.js:277-291 | `/status`、`/clear` 等 CLI 命令。Python 版用 `argparse` 子命令或交互式 `input()` 循环 |

> **关于 `scripts/ingest.js` 和 `scripts/rebuild_indexes.js`**：`package.json` 中定义了这两个脚本入口，但 TagMemo 项目中实际**不存在 `scripts/` 目录**（已被 watcher 自动 ingestion 替代）。Python 版无需创建等价脚本，但可考虑在 `app.py` 中提供 `--rebuild` CLI 参数用于手动重建索引。

---

## 十、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| usearch Python 绑定 API 差异 | 中 | 通过 VectorIndex 适配层隔离，内部兼容。加载失败时自动从 SQLite 重建 |
| SQLite 并发写入 (Python GIL) | 低 | better-sqlite3 也是单线程同步的，行为一致 |
| chokidar → watchdog 事件差异 | 低 | watchdog 事件模型更简单，封装后一致 |
| tiktoken Python vs JS 版行为差异 | 极低 | 同源库，编码结果一致 |
| 大文件 ingestion 性能 | 低 | numpy 批量操作可优化 |

---

## 十一、总结

| 维度 | 评估 |
|------|------|
| **技术可行性** | ✅ 完全可行 — 所有组件均有成熟 Python 替代 |
| **数据兼容性** | ✅ 基本兼容 — SQLite + JSON 跨语言互通，.usearch 索引提供 fallback 重建 |
| **API 兼容性** | ✅ 完全兼容 — 相同 HTTP 端点、相同请求/响应格式 |
| **性能影响** | ✅ 无退化 — HNSW 核心不变，numpy 数值计算更优 |
| **代码量** | ⬇️ 减少 ~35-45% — Python 语法更简洁 + numpy 向量化 |
| **部署复杂度** | ⬇️ 大幅降低 — 无需 Rust 编译、无平台特定二进制 |
| **重构工作量** | 中等 — 约 16 个 Python 文件，核心算法逻辑 1:1 翻译 |
