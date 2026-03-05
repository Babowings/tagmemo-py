由于我们要将该问答系统接入到各类**标准大语言模型客户端（如 NextChat, Chatbox, LobeChat 等）**，你目前的 **流式处理（Stream=True）实现上** 还存在几处会导致这类客户端“死机、断连或报错”的长连接协议兼容性问题。

请重点修复以下 4 个协议层的“外皮”问题，即可将其完美作为外挂大模型后端服务。

---

## 1. 回合切割符不符合标准的 OpenAI SSE Chunk 格式

在长连接对话中，标准前端在收到数据流时会执行严格的 `JSON.parse()` 操作。

### 现状：
进入下一轮工具循环或者单纯为了在工具执行隔离日志前提供一个断行时，你写了：
```python
yield b"\n"
```
这个裸露的换行符是不包含 `data: ` 前缀并且不是合法结构体的数据。当类似 Chatbox 或标准的 OpenAI SDK 收到底层的 `\n` 时，会引发 `SyntaxError: Unexpected token` 解析崩溃，导致整个对话对话框直接变成大红字然后“死掉”。

### 修复指引：
你不能抛出没有任何包装控制符的空包。请在丢弃 `\n` 的地方，将原逻辑替换成可以被前端合理反序列化的合法空壳字典块，例如：
```python
separator_payload = {
    "id": f"chatcmpl-vcp-sep-{int(time.time()*1000)}",
    "object": "chat.completion.chunk",
    "choices": [{"index": 0, "delta": {"content": "\n"}, "finish_reason": None}]
}
yield f"data: {json.dumps(separator_payload, ensure_ascii=False)}\n\n".encode("utf-8")
```

---

## 2. 缺失 SSE 幽灵心跳保活机制（防卡死/超时断流）

### 现状：
流式对话下，如果你的检索组件去本地进行大范围的 TagBoost V3.7 或是被 LLM 的高延迟工具调用阻塞，可能数秒或长达十多秒时间不向客户端 yield 任何字节。
多数客户端的网络层具备“超过 10 秒读不到 Stream 就强行切断 TCP”的防假死保护。这会导致系统在后端干完活了，其实前端页面已经结束连接。

### 修复指引：
你需要为你的生成器提供一个保活协程/定时器支持。在长等待过程中，发送 SSE 标准允许的注释行：
```python
# 例如每隔 5 秒 yield 这样一条对逻辑无影响的心跳：
yield b": vcp-keepalive\n\n"
```
*（这是原项目解决该问题的标准做法。可借助 `asyncio.wait` 加入超时打断抛出来实现）*

---

## 3. 流式转发管道丢失了 `force_show_vcp` 标识支持

### 现状：
原版项目针对类似 Claude Code CLI 或需要完整审计日志的调用者设计了专用的路由 `/v1/chatvcp/completions`。
但在目前的 `app.py` 内部处理中，非流式响应带有 `force_show_vcp=force_show_vcp` 的下发传递，而对应的 `_handle_stream_response(upstream_body, metrics)` 函数调用不仅没有接收这个参数，也没有将过程强制推送回大模型的消息界面里的逻辑。

### 修复指引：
在 `_handle_stream_response` 签名增加 `force_show_vcp: bool = False` 参数，并在其内部组装最终 `JSON.dumps()` 给前端推送 Chunk 时，将工具提取历史记录作为强制文字追加在生成的回答之前或之后（对齐 `_handle_normal_response` 末尾的那段 `force_show_vcp` 判断包装）。

---

## 4. 彻底抛弃了 VCPInfoHandler 过程透明流

### 现状：
在原版项目中，当大模型挂起去执行内部工具时，服务器会通过 `vcpInfoHandler.streamVcpInfo` 伪造一种“打字机动画”，流式输出《🔍 正在查阅XXX》的过程结构给前端，使得整个工具调用变得肉眼可见。
而当前系统中的 `_execute_compatible_tool` 彻底退居静默状态，用户除了干瞪眼等待外，看不到你的强大机制正在做深层聚合检索。

### 修复指引：
如果你只作为单纯外挂，可以不补。
如果你想给用户原汁原味的体验，可以在执行 `_execute_compatible_tool` 前后，主动封装一段包含“系统内部提示文本”的 Chunk JSON 回传。
