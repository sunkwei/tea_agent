# TeaAgent Android 架构文档

> @2026-05-16 gen by tea_agent

## 设计原则

1. **薄原生层**：Kotlin 层只提供系统能力（文件、通知、存储），不包含业务逻辑
2. **厚前端层**：所有 UI 和交互逻辑在 WebView 的 JS 中实现
3. **远端推理**：AI 推理全部在远程 tea_agent 后端完成
4. **与桌面版一致**：视觉风格、交互模式与桌面版 HtmlFrame 保持一致

## 数据流

```
用户输入文本
    │
    ▼
app.js: sendMessage()
    │ TeaBridge.sendMessage()
    ▼
JsBridge.sendMessage() [Kotlin]
    │ ApiClient.chatStream()
    ▼
OkHttp POST → tea_agent 后端
    │ SSE stream
    ▼
onToken / onThinking / onToolCall / onDone
    │ JsBridge.emitEvent()
    ▼
TeaBridge.emit() [JS]
    │
    ▼
app.js: 更新 DOM
```

## 安全模型

- **文件访问**：仅限应用私有目录 + 公共文档目录（FileHandler.resolveFile）
- **网络**：默认允许 HTTP（`usesCleartextTraffic=true`），用于开发环境连接本地后端
- **WebView**：禁用文件访问的 URL 重定向，所有 URL 在 WebView 内处理

## 后端 API 协议

### SSE 事件类型

| type | 说明 | 数据字段 |
|------|------|---------|
| `token` | 流式文本 | `{"text": "..."}` |
| `thinking` | 模型思考 | `{"text": "..."}` |
| `tool_call` | 工具调用 | `{"name":"...", "args":{...}, "result":"..."}` |
| `done` | 本轮完成 | `{"used_tools": bool}` |
| `status` | 状态消息 | `{"text": "..."}` |
| `error` | 错误 | `{"message": "..."}` |

## 扩展计划

- [ ] MQTT 支持（与桌面版 chat_room_connector 互通）
- [ ] 语音输入（Android SpeechRecognizer）
- [ ] TTS 语音输出
- [ ] 本地轻量推理（通过 ollama Android 端口或 llama.cpp）
- [ ] Widget 桌面小部件
- [ ] 通知栏快捷操作
- [ ] 多会话管理
