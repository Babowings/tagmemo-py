# Copilot Proxy

这里预留给 Copilot 协议代理实验。

当前状态：

- 目录已创建
- 暂无正式适配器实现
- 若后续需要接入，应先使用 [../README.md](../README.md) 中描述的抓包流程确认真实请求协议

建议实施顺序：

1. 用 `proxy/common/request_inspector.py` 抓到 Copilot 客户端真实请求
2. 确认它的请求路径、鉴权头、流式协议和工具调用格式
3. 单独实现 Copilot -> TagMemo memory query -> Copilot upstream 的适配逻辑

在真正实现前，这个目录只作为占位说明，不应被视为可直接使用的代理。
