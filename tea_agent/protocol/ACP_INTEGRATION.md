# ACP (Agent Client Protocol) 集成指南

## 概述

Tea Agent 实现了 [Agent Client Protocol (ACP) v1.2.1](https://github.com/formulahendry/vscode-acp)，
作为 VS Code 扩展 **vscode-acp** 的兼容 Agent。

ACP 是一个**基于 JSON-RPC 2.0 over stdio** 的协议，Agent 进程通过 stdin/stdout
与 VS Code 双向通信。

## 快速开始

### 1. 安装 VS Code 扩展

在 VS Code 扩展市场搜索 **"ACP Client"**（作者: formulahendry）并安装。

### 2. 配置 Agent

在 VS Code 设置 (`settings.json`) 中添加：

```json
"acp.agents": {
    "Tea Agent": {
        "command": "python",
        "args": ["-m", "tea_agent.protocol"],
        "env": {}
    }
}
```

### 3. 连接

- 点击 VS Code 侧边栏的 **ACP** 图标
- 从 Agent 列表中选择 **"Tea Agent"**
- 点击 **Connect** 按钮

### 4. 开始对话

连接成功后，ACP 面板会显示聊天界面。输入消息即可与 Tea Agent 交互。

## 命令行选项

```bash
# 默认：stdio JSON-RPC 模式（用于 vscode-acp）
python -m tea_agent.protocol

# 详细日志（对调试有用）
python -m tea_agent.protocol --verbose

# 静默模式
python -m tea_agent.protocol --quiet

# 旧版 HTTP 模式（REST API + SSE）
python -m tea_agent.protocol --http
python -m tea_agent.protocol --http --port 8082

# 指定配置文件
python -m tea_agent.protocol --config /path/to/config.yaml
```

## 架构

```
┌─────────────────────────────────────────────────────┐
│                    VS Code                           │
│  ┌──────────────────────────────────────────────┐   │
│  │           vscode-acp 扩展                     │   │
│  │  ┌─────────┐  ┌──────────┐  ┌────────────┐  │   │
│  │  │ Agent   │  │ Session  │  │ FileSystem │  │   │
│  │  │ Manager │  │ Manager  │  │ Terminal   │  │   │
│  │  └────┬────┘  └────┬─────┘  └──────┬─────┘  │   │
│  └───────┼────────────┼───────────────┼────────┘   │
│          │   JSON-RPC │ 2.0 over     │             │
│          │   stdin/   │ stdout       │             │
├──────────┼────────────┼───────────────┼────────────┤
│          │   child    │ process      │             │
│  ┌───────┴────────────┴───────────────┴────────┐   │
│  │              Tea Agent ACP                   │   │
│  │  ┌───────────┐  ┌────────────────────┐      │   │
│  │  │ acp_agent │  │ acp_client_methods │      │   │
│  │  │ (服务器)  │  │ (调用 VS Code)    │      │   │
│  │  └─────┬─────┘  └─────────┬──────────┘      │   │
│  │        │                  │                  │   │
│  │  ┌─────┴──────────────────┴──────────┐       │   │
│  │  │      acp_jsonrpc (传输层)          │       │   │
│  │  └───────────────────────────────────┘       │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## 支持的协议方法

### 生命周期

| 方法 | 方向 | 描述 |
|------|------|------|
| `initialize` | client → agent | 握手，交换能力 |
| `authenticate` | client → agent | 认证 |
| `logout` | client → agent | 登出 |

### 提供商/模型

| 方法 | 方向 | 描述 |
|------|------|------|
| `providers/list` | client → agent | 列出可用模型 |
| `providers/set` | client → agent | 设置当前模型 |
| `providers/disable` | client → agent | 禁用提供商 |

### 会话管理

| 方法 | 方向 | 描述 |
|------|------|------|
| `session/new` | client → agent | 创建新会话 |
| `session/load` | client → agent | 加载已有会话 |
| `session/list` | client → agent | 列出会话 |
| `session/delete` | client → agent | 删除会话 |
| `session/fork` | client → agent | 复刻会话 |
| `session/resume` | client → agent | 恢复会话 |
| `session/close` | client → agent | 关闭会话 |
| `session/prompt` | client → agent | 发送提示词 |
| `session/cancel` | client → agent | 取消当前轮次 |
| `session/set_mode` | client → agent | 设置模式 |
| `session/set_config_option` | client → agent | 设置配置项 |

### 文档事件（通知）

| 方法 | 方向 | 描述 |
|------|------|------|
| `document/didOpen` | client → agent | 文档打开 |
| `document/didChange` | client → agent | 文档变更 |
| `document/didClose` | client → agent | 文档关闭 |
| `document/didSave` | client → agent | 文档保存 |
| `document/didFocus` | client → agent | 文档聚焦 |

### 内联编辑建议 (NES)

| 方法 | 方向 | 描述 |
|------|------|------|
| `nes/start` | client → agent | 开始内联编辑 |
| `nes/suggest` | client → agent | 生成编辑建议 |
| `nes/accept` | client → agent | 接受建议 |
| `nes/reject` | client → agent | 拒绝建议 |
| `nes/close` | client → agent | 关闭 NES 会话 |

### 扩展点

| 方法 | 方向 | 描述 |
|------|------|------|
| `ext/request` | client → agent | 自定义扩展请求 |
| `ext/notification` | client → agent | 自定义通知 |

### 客户端方法（Agent → Client）

Agent 可以通过以下方法调用 VS Code 的能力：

| 方法 | 描述 |
|------|------|
| `fs/read_text_file` | 读取文件（含未保存缓冲区） |
| `fs/write_text_file` | 写入文件并打开编辑器 |
| `session/request_permission` | 请求用户授权 |
| `session/update` | 流式更新内容块 |
| `session/update_config` | 更新配置选项 |
| `session/update_commands` | 更新可用命令 |
| `session/info_update` | 更新会话信息 |
| `terminal/create` | 创建终端 |
| `terminal/output` | 读取终端输出 |
| `terminal/wait_for_exit` | 等待终端退出 |
| `terminal/kill` | 杀死终端 |
| `terminal/release` | 释放终端 |
| `elicitation/create` | 创建表单 |
| `elicitation/complete` | 提交表单数据 |
| `mcp/connect` | 连接 MCP 服务器 |
| `mcp/message` | 发送 MCP 消息 |
| `mcp/disconnect` | 断开 MCP 服务器 |

## 协议流程

典型的 ACP 会话流程：

```
Client                      Agent
  │                           │
  │──── initialize ──────────>│  ← 握手
  │<─── InitializeResponse ───│
  │                           │
  │──── session/new ─────────>│  ← 创建会话（带 cwd）
  │<─── NewSessionResponse ───│
  │                           │
  │──── session/prompt ──────>│  ← 发消息
  │<─── session/update ───────│  ← 流式内容块（可选）
  │<─── session/update ───────│
  │<─── session/update ───────│
  │<─── PromptResponse ───────│  ← 最终响应
  │                           │
  │──── session/cancel ──────>│  ← 取消（可选）
  │<─── CancelResponse ───────│
  │                           │
  │──── session/delete ──────>│  ← 清理
  │<─── DeleteResponse ───────│
```

### Agent 请求 VS Code 操作

```
Agent                      Client (VS Code)
  │                           │
  │── fs/read_text_file ─────>│  ← Agent 需要读取文件
  │<── { content: "..." } ────│
  │                           │
  │── fs/write_text_file ────>│  ← Agent 需要写入文件
  │<── { success: true } ─────│
  │                           │
  │── terminal/create ───────>│  ← Agent 需要执行命令
  │<── { terminalId } ────────│
```

## 项目结构

```
tea_agent/protocol/
├── __init__.py                  # 模块导出
├── __main__.py                  # CLI 入口（--http / 默认 stdio）
├── acp_jsonrpc.py               # JSON-RPC 2.0 传输层
├── acp_agent.py                 # ACP Agent 服务端（协议处理器）
├── acp_client_methods.py        # Agent→Client 方法调用
├── acp_server.py                # HTTP 遗留模式（可选）
├── test_acp_smoke.py            # 冒烟测试（24项断言）
```

## 测试

```bash
# 运行冒烟测试（24项断言覆盖所有 handler）
python -m tea_agent.protocol.test_acp_smoke

# 预期输出：3/3 passed, 0 failed
```

## 配置

Tea Agent 使用 `~/.tea_agent/config.yaml` 作为默认配置文件。
可以通过 `--config` 参数指定其他路径。

重要配置项：

```yaml
main_model: deepseek-v4-flash   # 主模型
cheap_model: deepseek-v4-flash  # 轻量模型
embedding_model: ...            # 嵌入模型
```

## 故障排查

### Agent 无法连接

1. 确认 `python -m tea_agent.protocol` 在终端可以正常运行
2. 检查 VS Code 设置中 `acp.agents` 配置是否正确
3. 查看 VS Code 输出面板（"ACP Client" 频道）的日志
4. 尝试 `--verbose` 模式运行 Agent

### 流式输出不工作

确保在 `acp.autoApprovePermissions` 设置中允许流式更新。

### 文件操作失败

Agent 通过 `fs/read_text_file` 和 `fs/write_text_file` 读取/写入文件。
这些操作需要 VS Code 的授权。确保在权限对话框中点击"允许"。

## 贡献指南

1. Fork 项目并创建特性分支
2. 添加或修改协议处理器（在 `acp_agent.py` 中）
3. 添加客户端方法（在 `acp_client_methods.py` 中）
4. 更新 `test_acp_smoke.py` 的测试覆盖
5. 运行测试：`python -m tea_agent.protocol.test_acp_smoke`
6. 提交 PR

### 添加新的协议方法

1. 在 `acp_agent.py` 的 `_register_handlers()` 中注册：
   ```python
   t.on_request("my/custom_method", self._handle_my_custom_method)
   ```
2. 实现 handler：
   ```python
   def _handle_my_custom_method(self, params, msg_id):
       return {"result": "ok"}
   ```
3. 在 `test_acp_smoke.py` 中添加测试断言

---

*Tea Agent — 自我进化的 AI Agent*
