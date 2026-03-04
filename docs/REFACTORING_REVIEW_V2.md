# 第二轮审查报告 — 修改后的 REFACTORING_PLAN.md

> 审查日期：2026-02-23  
> 审查对象：修改后的 `REFACTORING_PLAN.md`  
> 审查重点：①之前问题的修复状态 ②Python/JS/Rust 语言差异带来的新问题

---

## 🔴 新发现的严重问题

### 1. `metric='l2sq'` 的 score 计算公式 `1.0 - dist` 在数学上不正确

方案第 269 行改为 `metric='l2sq'`（正确匹配原版），但第 304 行的 score 计算：
```python
{"id": int(key), "score": 1.0 - float(dist)}
```

**问题**：L2 平方距离的范围是 `[0, +∞)`，不是 `[0, 1]`。对于归一化向量，L2sq 范围是 `[0, 4]`。所以 `1.0 - l2sq_dist` 可以产生**负数** score，与原版行为不一致。

原版 VexusIndex 的 `search()` 返回的 `score` 需要确认其实际含义。从原版 JS 代码的使用来看（`results.sort((a, b) => b.score - a.score)`），score 应该是越高越好。

**建议修改**：
```python
# 方案一：如果原版 Rust 内部做了 cos 转换
{"id": int(key), "score": 1.0 - float(dist) / 2.0}  # l2sq to cosine for normalized vecs

# 方案二：直接用 metric='cos' 更安全
self.index = Index(ndim=dim, metric='cos', dtype='f32')
# 此时 dist = 1 - cos_similarity, score = 1.0 - dist 就天然在 [0, 1] 范围
```

我之前的review没有提到这个问题，是你自己发现并修改的，你考虑是不是误判了？是否要修改回之前的cos？

需要查看原版 Rust 代码确认 `MetricKind` 和 score 转换逻辑。**这是一个可能导致检索结果排序完全错误的关键问题。**

---

## 🟡 Python/JS 语言差异问题

### 2. `np.frombuffer` 返回只读数组 — 全局性问题

方案第 336 行已经正确加了 `.copy()`：
```python
vec = np.frombuffer(vector_blob, dtype=np.float32).copy()
```

但在 `knowledge_base.py` 中**所有从 SQLite BLOB 读取向量的地方**都需要 `.copy()`。原版 JS 中 `new Float32Array(buf.buffer, buf.byteOffset, dim)` 创建的是可写视图，而 Python 的 `np.frombuffer` 返回只读数组，不 `.copy()` 就无法修改。

**建议**：在方案的某个显眼位置加一个通用注意事项：
> ⚠️ Python 从 SQLite BLOB 读取向量时，必须使用 `np.frombuffer(...).copy()`。`np.frombuffer` 返回只读数组，不 copy 会导致后续写操作抛出 `ValueError: assignment destination is read-only`。

### 3. `better-sqlite3` 的 `prepare()` 预编译缓存无 Python 等价

原版 `better-sqlite3` 的核心模式：
```js
const stmt = this.db.prepare(sql);   // 预编译一次
const row = stmt.get(param);          // 多次调用已编译语句
```

Python `sqlite3` 没有 `prepare()` + `get()` 的组合，等价写法是：
```python
row = self.conn.execute(sql, (param,)).fetchone()
```

**隐藏问题**：`prepare` 会预编译 SQL 并缓存，在高频调用时（如 `hydrate.get(res.id)` 对每个搜索结果逐条调用）有性能优势。Python `sqlite3` 不提供显式预编译 API。

**建议**：高频 SQL 查询考虑批量化（`WHERE id IN (?, ?, ...)`）代替逐条查询。

### 4. `better-sqlite3` 的 `.transaction()` 事务边界设计

原版 `KnowledgeBaseManager.js:726-784` 使用 `db.transaction(() => { ... })()` 的模式。事务函数有返回值 `{ updates, tagUpdates, deletions }`，**事务外**再用这些返回值更新 VectorIndex。

Python `sqlite3` 的事务模式不同：
```python
with conn:  # 自动 commit on exit, rollback on exception
    conn.execute(...)
```

**问题**：需要在 Python 版中保持相同的事务边界：
- 事务内：只做 SQLite 操作
- 事务外：使用返回值更新 VectorIndex（add/remove）

如果把 VectorIndex 操作也放在 `with conn:` 内，一旦索引操作失败但 SQLite 已提交，会造成**数据不一致**。

**建议**：方案应明确事务边界设计。

### 5. 缓存淘汰策略差异：原版 FIFO vs `cachetools.TTLCache` LRU

原版 Engine 的查询缓存淘汰靠 `Map.keys().next().value`（删除最早插入的 key），是 **FIFO** 策略。

方案第 450 行提到可以用 `cachetools.TTLCache`，但 `TTLCache` 继承自 `LRUCache`，淘汰的是**最久未访问**的条目（LRU），与原版的 FIFO 行为不同。

**建议**：如果要保持原版行为，用 `dict` + 手动删除 `next(iter(cache))` 即可（Python 3.7+ dict 保持插入序）。如果有意改进为 LRU，应在方案中注明这是设计改进。

### 6. `watchdog` 无 `ignoreInitial` — 缺少启动时全量扫描

原版 `chokidar.watch(path, { ignoreInitial: !fullScanOnStartup })`：
- `ignoreInitial: false` → 启动时对已有文件触发 `add` 事件（全量扫描）
- `ignoreInitial: true` → 只监听新变化

`watchdog` 的 `Observer` **没有** `ignoreInitial` 等价选项，它只监听文件系统变化事件，不会为已有文件触发事件。

**问题**：Python 版需要**手动实现**启动时全量扫描：
```python
if self.config['full_scan_on_startup']:
    for root, dirs, files in os.walk(self.config['root_path']):
        for f in files:
            if f.endswith(('.md', '.txt')):
                self._handle_file(os.path.join(root, f))
```

**建议**：方案 5.3 节或第九章应明确提到这个差异和解决方案。这是一个**必须实现的功能**，否则 Python 版启动后不会索引任何已有文档。

### 7. `setImmediate` / `setTimeout` 在同步 KBM 上下文中的 Python 等价

原版多处使用：
- `setImmediate(() => ...)` — KBM:238, 817, 823
- `setTimeout(() => ..., delay)` — KBM:645, 852

方案第 690 行提到了 `asyncio.call_later()` 或 `threading.Timer`，方向正确。但需要注意：**KBM 的核心逻辑是同步的**（使用同步 `sqlite3`），如果用 `asyncio.call_later` 则需要 KBM 运行在事件循环中，可能与同步 DB 操作冲突。

**建议**：明确 KBM 内部定时器应使用 `threading.Timer`（因为 KBM 是同步模块），避免与 FastAPI 的 asyncio 事件循环混用。

---

## 🟢 小问题

### 8. EPA 缓存的序列化方式未提及

原版 `EPAModule._saveToCache()` 将 Float32Array 用 `Buffer.toString('base64')` 序列化为 base64 存入 `kv_store`。Python 版需要用 `base64.b64encode(array.tobytes()).decode()` 实现相同效果。

方案未提及 EPA 的 `_saveToCache` / `_loadFromCache` 方法，但这是 EPA 模块的重要功能（避免每次启动重算 PCA）。

### 9. `ResultDeduplicator` 中 candidates 可能不带 vector 属性

原版 `ResultDeduplicator.js:40` 检查 `c.vector || c._vector`，但 `_searchSpecificIndex` 返回的 result 对象不包含 `vector` 字段（只有 `text`、`score`、`sourceFile` 等）。这意味着 `deduplicate()` 可能总是走 `validCandidates.length <= 5` 的早期返回分支。

Python 版应保持相同行为，但值得标注这个可能无效的去重逻辑。

---

## 📝 第二轮修改建议总结

| 优先级 | 编号 | 建议行动 |
|--------|------|---------|
| **P0** | #1 | 确认 `metric` 和 `score` 的计算公式。需要查看原版 Rust 代码的实际 MetricKind 和 score 转换逻辑。score 范围不一致会导致检索排序完全错误 |
| **P1** | #2 | 增加通用注意事项：Python 从 SQLite BLOB 读向量必须 `.copy()` |
| **P1** | #4 | 明确事务边界：SQLite 事务内只做 DB 操作，索引更新在事务外 |
| **P1** | #6 | 补充 watchdog 无 `ignoreInitial` 等价选项，需要手动实现启动时全量扫描 |
| **P2** | #3 | 提示 `better-sqlite3` 的 `prepare` 预编译缓存在 Python `sqlite3` 中没有等价物，高频查询考虑批量化 |
| **P2** | #5 | 明确缓存淘汰策略（FIFO vs LRU），`cachetools.TTLCache` 是 LRU 而非原版 FIFO |
| **P2** | #7 | 明确 KBM 定时器应使用 `threading.Timer`（因为 KBM 是同步的） |
| **P3** | #8 | 补充 EPA `_saveToCache/_loadFromCache` 的 Python 序列化方式 |
| **P3** | #9 | 明确 Python 最低版本要求（建议 3.9+） |
| **P3** | #10 | 标注 `ResultDeduplicator` 可能因 candidates 无 vector 属性而跳过去重 |
