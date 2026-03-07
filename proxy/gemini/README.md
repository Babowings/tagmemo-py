# Gemini Proxy

这里放的是 Gemini 原生协议到 TagMemo 记忆层的适配器。

它解决的问题不是“把 Gemini 变成 OpenAI 协议”，而是：**让 Gemini CLI 继续发送原生 Gemini 请求，同时在发往官方 Gemini 之前先补一层 TagMemo 记忆。**

## 当前架构

请求链路如下：

1. Gemini CLI 向本代理发送原生 Gemini 请求
2. 代理从 `contents` 中提取最新用户问题和历史
3. 代理调用 TagMemo `POST /v1/memory/query`
4. 代理把 `memory_context` 注入到 Gemini `systemInstruction`
5. 代理把增强后的请求转发到官方 Gemini API
6. 官方 Gemini 的响应暂时按原样回传，不做复杂重写

关键原则：

- TagMemo 只负责记忆检索
- 最终回答仍由官方 Gemini 生成
- 代理不改写 Gemini 的整体协议形状，只做最小必要适配

## 已实现能力

`server.py` 当前支持：

- `/v1beta/models/{model}:generateContent`
- `/v1beta/models/{model}:streamGenerateContent`
- 同一组路径的 `/chat/...` 前缀兼容形式
- 从 Gemini `contents` 映射出 TagMemo 所需的 `message` / `history`
- 调用 `POST /v1/memory/query`
- 将命中的 `memory_context` 追加到 `systemInstruction`
- 对部分不合法 Gemini 参数做最小清洗，例如 `thinkingBudget`
- 非流式 JSON 返回透传
- 流式 SSE 返回透传

## 运行方式

先启动 TagMemo 主服务：

```bash
uv run python app.py --port 3100
```

再启动 Gemini 代理：

```bash
uv run python proxy/gemini/server.py --port 3102
```

健康检查：

```bash
curl http://127.0.0.1:3102/health
```

## 环境变量

可选配置如下：

- `TAGMEMO_BASE_URL`：默认 `http://127.0.0.1:3100`
- `TAGMEMO_MEMORY_PATH`：默认 `/v1/memory/query`
- `GEMINI_UPSTREAM_BASE_URL`：默认 `https://generativelanguage.googleapis.com`
- `GEMINI_UPSTREAM_API_KEY`：默认空；若设置，则代理固定使用该 key 请求官方 Gemini
- `PROXY_TIMEOUT_SECONDS`：默认 `180`

认证建议：

- 联调阶段可以直接转发客户端带来的 `x-goog-api-key`
- 稳定使用时更建议在代理进程里设置 `GEMINI_UPSTREAM_API_KEY`
- 这样可以避免 CLI 没有重新加载环境变量，或请求头透传不一致导致的认证问题

## Gemini CLI 配置

把 Gemini CLI 的 base URL 指到本代理，而不是主 TagMemo 服务：

```env
GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:3102
GOOGLE_GEMINI_API_KEY=<real-gemini-key>
```

如果你已经在代理侧配置了 `GEMINI_UPSTREAM_API_KEY`，CLI 侧这个 key 仍可以保留占位，但真正请求官方 Gemini 时会优先使用代理配置。

## 已验证内容

- 可以接收 Gemini CLI 实际使用的原生 Gemini 路径
- 可以兼容带 `/chat/` 前缀的 base URL 写法
- 可以命中 TagMemo `/v1/memory/query`
- 可以把返回的 `memory_context` 注入原始 Gemini 请求
- `tests/test_gemini_proxy.py` 当前已覆盖关键映射与转发行为

运行定向测试：

```bash
uv run pytest -q tests/test_gemini_proxy.py
```

## 当前边界

- 目前重点是“请求成功带着记忆到达官方 Gemini”
- 官方 Gemini 返回后的高级解析和协议整形暂未深做
- 如果上游返回 `API_KEY_INVALID`、`RESOURCE_EXHAUSTED` 等错误，当前会尽量保留上游原始错误语义
- 由于使用google ai studio 的 api 没有gemini-3.1-pro的额度，暂未验证从官方 gemini 返回的逻辑
