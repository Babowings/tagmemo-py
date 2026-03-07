# Proxy Workspace

`proxy/` 用来放置和主 TagMemo 服务解耦的 Provider 协议代理。它的目标不是替代 `app.py`，而是在外部客户端使用原生 Provider 协议时，提供一层“记忆增强中间层”。

当前最完整的实现是 Gemini 代理：

- 外部客户端仍说 Gemini 原生协议
- Proxy 先向 TagMemo 查询记忆
- Proxy 再把增强后的请求转发到官方 Gemini

## 目录结构

- `common/`: 共享调试工具，目前包含请求抓包器
- `gemini/`: 已实现的 Gemini CLI / API 协议代理
- `antigravity/`: 预留目录
- `copilot/`: 预留目录

## 推荐调试顺序

### 1. 先抓包，确认真实协议

先不要假设 CLI 走的是 OpenAI 风格路径。先用 `common/request_inspector.py` 把真实请求路径、头和 body 打出来。

```bash
uv run python proxy/common/request_inspector.py --port 3101
```

然后把目标客户端的 Base URL 临时指向 `http://127.0.0.1:3101`。

### 2. 再实现 Provider 代理

确认清楚原生协议后，再在对应子目录里实现真正的转发适配器。

### 3. 最后接入 TagMemo 记忆层

Proxy 适配器通常应该：

1. 解析外部客户端的原生请求
2. 提取最新用户问题和必要历史
3. 调用 TagMemo `POST /v1/memory/query`
4. 把返回的 `memory_context` 注入 Provider 原生请求
5. 将增强后的原始请求转发给官方上游

## 运行约定

- TagMemo 主服务默认跑在 `http://127.0.0.1:3100`
- Provider Proxy 自己跑在单独端口，例如 Gemini 默认 `3102`
- 抓包器默认跑在 `3101`

这样做的原因是职责边界清晰：

- `3100` 负责记忆检索、OpenAI 风格聊天、后台与审计
- `3101` 负责抓包排查
- `3102+` 负责 Provider 协议适配

## 当前状态

- `gemini/`：可用，已支持 `generateContent` 与 `streamGenerateContent`
- `antigravity/`：仅目录占位
- `copilot/`：仅目录占位
