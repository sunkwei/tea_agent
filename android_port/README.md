# TeaAgent Android v0.2.0

> 标准 Android 聊天应用，对标 tea_agent 桌面版核心能力。

## 🎯 功能

| 功能 | 实现 |
|------|------|
| 流式对话 | SSE (OkHttp) |
| 工具调用 | JS 动态执行 (toolkit_mgrt/reload) |
| 主题管理 | SQLite 持久化 |
| Token 统计 | 实时显示 prompt/completion/total |
| 历史压缩 | Level 1/2/3 三级策略 |
| 三模型配置 | main / cheap / embedding |
| 主题切换 | 深色 / 浅色 |
| 视觉区分 | user(蓝) / thinking(黄) / tool(绿) / assistant(灰) |

## 🏗️ 架构

```
WebView (HTML/CSS/JS)
    ↕ @JavascriptInterface
JsBridge (Kotlin)
    ↕
ApiClient ← SSE → LLM API
ToolManager ← SQLite
HistoryCompressor ← SQLite
ConfigManager ← SQLite
```

## 📂 项目结构

```
tea_agent_android/
├── app/src/main/java/com/teaagent/android/
│   ├── MainActivity.kt          # 入口
│   ├── AgentWebView.kt          # WebView 配置
│   ├── bridge/JsBridge.kt       # JS 桥接
│   ├── bridge/FileHandler.kt    # 文件 & 通知
│   ├── api/ApiClient.kt         # SSE + 工具调用循环
│   ├── db/AppDatabase.kt        # SQLite 表定义
│   ├── db/Daos.kt               # CRUD
│   ├── core/ConfigManager.kt    # 三模型配置
│   ├── core/ToolManager.kt      # JS 工具管理
│   ├── core/HistoryCompressor.kt # 历史压缩
│   └── model/Models.kt          # 数据类
├── app/src/main/assets/web/     # Web 前端
└── docs/architecture.md
```

## 🚀 构建

Android Studio → 打开 `tea_agent_android/` → Run
