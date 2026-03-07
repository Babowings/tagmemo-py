# Antigravity Proxy

这里预留给 Antigravity 协议代理实验。

当前状态：

- 目录已创建
- 暂无正式适配器实现
- 后续若要接入，应先通过 `proxy/common/request_inspector.py` 确认客户端实际请求协议

推荐落地顺序：

1. 先抓包确认真实请求路径、头和 body
2. 再实现 Antigravity 原生协议到 TagMemo 记忆层的映射
3. 最后把增强后的原始请求转发到对应官方上游

在真正实现之前，这个目录只是预留位，不代表已经具备可运行代理能力。
