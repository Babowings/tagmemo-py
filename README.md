# 🧠 TagMemo-py — 超级 RAG 智能对话系统 (Python 版)

TagMemo-py 是 [TagMemo](https://github.com/nicepkg/VCPToolBox) 的纯 Python 重构版，用 **浪潮式 RAG (Wave RAG)** 构建具有深度记忆能力的智能对话系统。

> 原版基于 Node.js + Rust N-API (~5,362 行)，本版使用 Python + usearch + numpy 以 ~5,400 行等价实现，**无需编译 Rust**。

## 核心特性

- **EPA 投影分析** — 基于加权 PCA/SVD 的语义深度探测，评估查询的逻辑深度(L)和跨域共振(R)
- **Residual Pyramid** — Gram-Schmidt 正交分解，多层级残差能量建模
- **TagMemo V3.7 TagBoost** — 世界观门控 + 语言补偿 + 共现拉回 + 核心标签追踪
- **Shotgun Query** — 当前 query + 最多 3 个历史分段并行搜索，SVD 去重
- **动态 β 公式** — `β = σ(L · log(1+R) - S · noise_penalty)`，自适应调节 Tag 权重
- **ContextVectorManager** — 衰减聚合 + 语义宽度计算 + 会话分段
- **SemanticGroupManager** — 词元激活 + 组向量预计算 + 查询增强
- **Rerank 重排序** (可选) — 断路器 + Token 预算 + 批次分割 + 降级兜底
- **时间感知检索** — 自然语言时间表达式解析 → 按日期范围从磁盘检索日记文件
- **查询缓存** — 可配置大小/TTL + 命中统计 + 定期清理
- **rag_params 热加载** — 保存 `rag_params.json` 后参数自动生效，无需重启

## 快速开始

### 前置要求

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** 包管理器

### 1. 安装 uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 克隆项目 & 安装依赖

```bash
git clone <repo-url> TagMemo-py
cd TagMemo-py
uv sync                  # 创建 .venv 并安装全部依赖
uv sync --extra dev      # 含开发依赖 (pytest, ruff 等)
```

### 3. 配置环境

```bash
cp config.env.example config.env
```

编辑 `config.env`，至少填入 Embedding API 凭证：

```env
# Embedding API (必需)
API_Key=sk-your-embedding-api-key
API_URL=https://api.openai.com/v1/embeddings
WhitelistEmbeddingModel=text-embedding-3-small
VECTORDB_DIMENSION=1536

# Chat API (可选，不配置则以 Debug 模式运行，只返回记忆)
CHAT_API_KEY=sk-your-chat-api-key
CHAT_API_URL=https://api.openai.com/v1/chat/completions
CHAT_MODEL=gpt-4o

# Rerank (可选，填入后自动启用)
RERANK_API_URL=https://api.jina.ai/
RERANK_API_KEY=jina_xxx
RERANK_MODEL=jina-reranker-v2-base-multilingual
```

完整配置项请参见 [config.env.example](config.env.example)。

### 4. 准备知识库

将 Markdown/TXT 文件放入 `data/dailynote/` 目录（按子文件夹分"日记本"）：

```
data/dailynote/
  日记本A/
    2024-01-01.md
    2024-01-02.md
  日记本B/
    notes.md
```

文件中的 `Tag:` 行会被自动提取为语义标签：

```markdown
# 2024-01-15 日记

今天学习了向量数据库的原理...

Tag: 向量数据库, 机器学习, RAG
```

### 5. 启动

```bash
# HTTP 服务模式 (默认端口 3100)
uv run python app.py

# 指定端口 & 主机
uv run python app.py --port 8080 --host 0.0.0.0

# 交互式 CLI 模式
uv run python app.py --cli
```

## API 端点

TagMemo-py 对外暴露的 API 与原版完全兼容：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI 兼容 Chat Completions (自动注入记忆) |
| `/v1/memory/query` | POST | 独立记忆查询接口 |
| `/v1/memory/delete` | POST | 删除记忆（按 path(paths) 或 diaryName，支持 dryRun） |
| `/status` | GET | 服务状态、引擎统计、缓存命中率 |
| `/v1/cache/clear` | POST | 清空查询缓存 |
| `/v1/params/reload` | POST | 手动重载 rag_params.json |

### 示例请求

```bash
# 对话 (流式)
curl -X POST http://localhost:3100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "stream": true,
    "messages": [{"role": "user", "content": "我之前提过的向量数据库是什么？"}]
  }'

# 独立记忆查询
curl -X POST http://localhost:3100/v1/memory/query \
  -H "Content-Type: application/json" \
  -d '{"message": "向量数据库", "history": []}'

# 删除记忆（按 diaryName）
curl -X POST http://localhost:3100/v1/memory/delete \
  -H "Content-Type: application/json" \
  -d '{"diaryName": "VCP开发", "dryRun": true}'
```

## 项目结构

```
TagMemo-py/
├── app.py                     FastAPI 服务 + CLI 入口
├── config.env.example         环境配置模板
├── rag_params.json            算法参数 (热加载)
├── pyproject.toml             项目元数据 + 依赖 (uv/pip)
│
├── tagmemo/                   核心包
│   ├── __init__.py
│   ├── engine.py              TagMemoEngine — 核心编排 (11 步查询管线)
│   ├── knowledge_base.py      KnowledgeBaseManager — 向量库 + TagBoost V3.7
│   ├── epa.py                 EPAModule — 加权 PCA/SVD
│   ├── residual_pyramid.py    ResidualPyramid — Gram-Schmidt 正交分解
│   ├── result_deduplicator.py ResultDeduplicator — SVD 去重
│   ├── embedding_service.py   EmbeddingService — API + FIFO 缓存
│   ├── embedding_utils.py     批量嵌入工具 (并发 + 重试)
│   ├── context_vector.py      ContextVectorManager — 会话上下文向量
│   ├── semantic_groups.py     SemanticGroupManager — 语义组管理
│   ├── reranker.py            Reranker — 断路器 + 批次重排
│   ├── time_parser.py         TimeExpressionParser — 时间解析
│   ├── time_expressions.py    时间表达式配置数据
│   ├── text_sanitizer.py      TextSanitizer — 文本清洗
│   ├── text_chunker.py        TextChunker — Token 分块
│   └── vector_index.py        VectorIndex — usearch 适配层
│
├── tests/                     测试
│   ├── conftest.py
│   ├── test_text_sanitizer.py
│   ├── test_text_chunker.py
│   ├── test_time_parser.py
│   ├── test_vector_index.py
│   ├── test_epa.py
│   └── test_memory_delete.py
│
├── data/dailynote/            知识库文档 (用户数据)
├── VectorStore/               向量索引 + SQLite 存储 (自动生成)
└── REFACTORING_PLAN.md        重构方案文档
```

## 与 JS 版差异

| 维度 | JS 版 | Python 版 |
|------|-------|----------|
| 向量索引 | rust-vexus-lite (Rust N-API) | usearch Python binding (同 C++ 核心) |
| 数值计算 | Float32Array + nalgebra | numpy (LAPACK/OpenBLAS) |
| HTTP 框架 | Express | FastAPI + Uvicorn |
| SQLite | better-sqlite3 | sqlite3 标准库 |
| 文件监听 | chokidar | watchdog |
| 部署 | 需编译 Rust | `uv sync` 即可运行 |

## 开发

```bash
# 安装开发依赖
uv sync --extra dev

# 运行测试
uv run pytest

# 运行测试 (含覆盖率)
uv run pytest --cov=tagmemo --cov-report=term-missing

# 代码检查
uv run ruff check .

# 代码格式化
uv run ruff format .
```

## 数据兼容性

- **SQLite 数据库**: JS 版与 Python 版完全互通
- **config.env / rag_params.json**: 纯文本格式，直接复用
- **.usearch 索引文件**: 理论兼容（同 C++ 核心），加载失败时自动从 SQLite 重建

## 许可证

MIT
