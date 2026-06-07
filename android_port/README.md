# TeaAgent Android v0.3.0

> 🍵 智能 AI 助手 Android 客户端 — 基于 tea_agent 桌面版重构

## 功能特性

| 功能 | 状态 | 桌面版对标 |
|------|------|-----------|
| 流式对话 (SSE) | ✅ | ✅ |
| 工具调用 (Function Calling) | ✅ | ✅ |
| 原生工具 (toolkit_memory/kb) | ✅ | ✅ |
| 自我进化 (toolkit_self_evolve) | ✅ | ✅ |
| 版本化系统提示词 | ✅ | ✅ |
| 长期记忆 (SQLite) | ✅ | ✅ |
| 三级历史压缩 | ✅ | ✅ |
| SessionPipeline 架构 | ✅ | ✅ |
| 三模型配置 (main/cheap/embedding) | ✅ | ✅ |
| 深色/浅色主题 | ✅ | ✅ |
| 移动端滑动手势 | ✅ | ✅ |
| MQTT 多设备同步 | ⏳ | ✅ |
| 语音输入/输出 | ⏳ | ❌ |
| Widget 桌面小部件 | ⏳ | ❌ |
| 本地轻量推理 | ⏳ | ❌ |

## 架构设计

```
┌─────────────────────────────────────────────────┐
│                   WebView (UI)                   │
│              HTML/CSS/JS / Marked.js             │
└──────────────────────┬──────────────────────────┘
                       │ @JavascriptInterface
┌──────────────────────▼──────────────────────────┐
│                   JsBridge                       │
│         Kotlin ↔ JS 双向通信桥接                 │
└───────┬──────────┬──────────┬───────────────────┘
        │          │          │
┌───────▼──┐ ┌─────▼──────┐ ┌▼──────────────────┐
│ApiClient │ │ConfigMgr   │ │ToolComponent      │
│SSE+循环  │ │三模型配置   │ │JS/原生/受保护工具 │
└───────┬──┘ └────────────┘ └┬───────────────────┘
        │                    │
┌───────▼────────────────────▼───────────────────┐
│              SessionPipeline                    │
│     Step1:BuildMsgs → Step2:CallLLM → Step3:Exec│
└───────┬────────────────────┬───────────────────┘
        │                    │
┌───────▼────────┐  ┌───────▼──────────────────┐
│HistoryCompressor│  │  SQLite (AppDatabase)    │
│三级历史压缩     │  │ topics/messages/tools/  │
│                 │  │ config/memories          │
└────────────────┘  └──────────────────────────┘

           ┌──────────────────────┐
           │    Native Tools      │
           ├──────────────────────┤
           │ toolkit_memory       │ ← MemoryManager
           │ toolkit_kb           │ ← (简单实现)
           │ toolkit_self_evolve  │ ← SelfEvolveManager
           │ toolkit_save         │ ← 受保护元工具
           │ toolkit_reload       │ ← 受保护元工具
           └──────────────────────┘
```

### 核心组件

| 组件 | 文件 | 说明 |
|------|------|------|
| **SessionContext** | `core/SessionContext.kt` | 共享上下文，组件间数据交换 |
| **SessionComponent** | `core/SessionComponent.kt` | 组件基类，统一生命周期 |
| **SessionPipeline** | `core/SessionPipeline.kt` | 步骤化流程管理 |
| **ToolComponent** | `core/ToolComponent.kt` | 统一工具系统（JS+原生+受保护） |
| **PromptManager** | `core/PromptManager.kt` | 版本化系统提示词 |
| **MemoryManager** | `core/MemoryManager.kt` | 长期记忆管理 |
| **SelfEvolveManager** | `core/SelfEvolveManager.kt` | 自我进化管理 |
| **ConfigManager** | `core/ConfigManager.kt` | 三模型配置 |
| **HistoryCompressor** | `core/HistoryCompressor.kt` | 三级历史压缩 |
| **ApiClient** | `api/ApiClient.kt` | SSE 对话引擎 + 工具循环 |
| **JsBridge** | `bridge/JsBridge.kt` | JS ↔ Kotlin 桥接 |
| **FileHandler** | `bridge/FileHandler.kt` | 文件 & 通知 |

## 构建方式

### 前提条件

- Java 17+
- Android SDK (API 34)
- Gradle 8.5+ (使用自带 Wrapper)

### 选项 1: Make (推荐)

```bash
cd android_port
make setup     # 检查环境
make build     # 构建 APK
make install   # 安装到设备
make clean     # 清理
```

### 选项 2: 直接使用 Gradle

```bash
cd android_port/tea_agent_android
chmod +x gradlew
./gradlew assembleDebug
```

### 选项 3: 构建脚本

```bash
cd android_port
./build.sh setup   # 自动安装 SDK
./build.sh build   # 构建 APK
```

### 选项 4: Android Studio

打开 `android_port/tea_agent_android/` → 等待 Gradle 同步 → Run ▶

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.3.0 | 2026-06-04 | 架构重构：ToolComponent, SessionPipeline, PromptManager, MemoryManager, SelfEvolveManager |
| v0.2.0 | 2026-05-16 | 初始版本：WebView 前端、SSE 流式、工具调用 |

## 项目结构

```
android_port/
├── build.sh                        # Linux/macOS 构建脚本
├── build.bat                       # Windows 构建脚本
├── Makefile                        # Make 构建命令
├── README.md                       # 本文件
├── docs/
│   └── architecture.md             # 架构文档
└── tea_agent_android/              # Android 项目
    ├── build.gradle.kts            # 根级 Gradle 配置
    ├── settings.gradle.kts         # 项目设置
    ├── gradle.properties           # Gradle 属性
    ├── gradlew / gradlew.bat       # Gradle Wrapper
    └── app/
        ├── build.gradle.kts        # 应用模块配置
        └── src/
            └── main/
                ├── AndroidManifest.xml
                ├── java/com/teaagent/android/
                │   ├── MainActivity.kt         # 入口
                │   ├── AgentWebView.kt         # WebView 配置
                │   ├── api/
                │   │   └── ApiClient.kt        # SSE 引擎
                │   ├── bridge/
                │   │   ├── JsBridge.kt         # JS 桥接
                │   │   └── FileHandler.kt      # 文件&通知
                │   ├── core/
                │   │   ├── ConfigManager.kt    # 配置管理
                │   │   ├── HistoryCompressor.kt# 历史压缩
                │   │   ├── MemoryManager.kt    # 长期记忆
                │   │   ├── PromptManager.kt    # 提示词管理
                │   │   ├── SelfEvolveManager.kt# 自我进化
                │   │   ├── SessionComponent.kt # 组件基类
                │   │   ├── SessionContext.kt   # 共享上下文
                │   │   ├── SessionPipeline.kt  # 流程管理
                │   │   ├── ToolComponent.kt    # 统一工具系统
                │   │   └── ToolManager.kt      # (已废弃，保留兼容)
                │   ├── db/
                │   │   ├── AppDatabase.kt      # 数据库定义
                │   │   └── Daos.kt             # CRUD 操作
                │   └── model/
                │       └── Models.kt           # 数据模型
                ├── res/
                │   ├── layout/activity_main.xml
                │   └── values/themes.xml
                └── assets/web/
                    ├── index.html              # 主页面
                    ├── css/style.css           # 样式
                    ├── js/bridge.js            # JS 桥接库
                    ├── js/app.js               # 前端逻辑
                    └── lib/marked.min.js       # Markdown 解析
```
