## 最后更新: 2026-05-20
# tea_agent 项目知识库

> 自动生成: 2026-05-19 07:57
> 工具: Python AST + symbol_index.json
>
> 符号: 1204 唯一 · 函数: 1126 · 类: 78

## 项目概览

| 指标 | 值 |
|------|-----|
| 核心源文件 | 103 |
| 总行数 | 27,589 |
| 函数 | 1126 |
| 类 | 78 |
| 公开函数 | 556 |
| Python 版本 | >= 3.10 |
| 入口点 | tea_agent.main_db_gui:main |

## 架构分层

```
tea_agent/
├── main_db_gui.py          (2274行) 主 GUI 入口 (TkGUI)
├── gui.py                  (1148行) 重构版 GUI (组件化)
├── cli.py                  (416行)  CLI 入口
├── tea_agent.py            (330行)  Agent 主控
├── tlk.py                  (612行)  Toolkit 管理
├── agent_core.py           (623行)  核心逻辑基类
├── basesession.py          (624行)  会话基类
├── onlinesession.py        (1254行) 在线会话(工具调用)
├── config.py               (607行)  配置管理
├── memory.py               (723行)  记忆管理
├── reflection.py           (292行)  反思管理
├── prompt_manager.py       (282行)  提示词管理
├── embedding_util.py       (354行)  嵌入引擎
├── project_memory.py       (127行)  项目记忆
├── merge_db.py             (718行)  数据库合并
├── logging_setup.py         (98行)  日志配置
├── session/                        会话 Mixin 组件
│   ├── session_api.py      (333行)  API 调用
│   ├── session_memory.py   (220行)  记忆注入
│   ├── session_pipeline.py (204行)  流水线
│   ├── session_summarizer.py(767行) 摘要生成
│   ├── session_tool.py     (232行)  工具调用
│   ├── session_prompts.py   (53行)  提示词
│   └── session_ref.py       (28行)  引用
├── store/                          存储层
│   ├── _core.py            (619行)  核心存储
│   ├── _conversations.py   (201行)  对话存储
│   ├── _memories.py        (192行)  记忆存储
│   ├── _topics.py          (151行)  主题存储
│   ├── _summaries.py       (155行)  摘要存储
│   ├── _vectors.py         (187行)  向量存储
│   └── ...
├── toolkit/                        工具函数 (40文件)
│   ├── toolkit_exec.py     (350行)  命令执行
│   ├── toolkit_file.py     (134行)  文件操作
│   ├── toolkit_kb.py       (174行)  知识库
│   ├── toolkit_memory.py   (165行)  记忆工具
│   ├── toolkit_explr.py    (557行)  项目探索
│   └── ...
├── _gui/                           GUI 组件 (22文件)
│   ├── _renderer.py        (431行)  渲染器
│   ├── _markdown.py        (425行)  Markdown/HTML
│   ├── _stream_manager.py  (147行)  流式管理
│   ├── _console.py         (124行)  控制台
│   └── ...
└── skills/                        技能系统
    └── __init__.py         (371行)  技能管理
```

## 核心类

| 类 | 模块 | 说明 |
|----|------|------|
| TkGUI | main_db_gui.py / gui.py | 主 GUI 窗口 |
| BaseChatSession | basesession.py | 会话基类 |
| OnlineToolSession | onlinesession.py | 在线工具调用会话 |
| TeaAgent | tea_agent.py | Agent 主控 |
| Toolkit | tlk.py | 工具库管理 |
| AgentCore | agent_core.py | 核心逻辑 |
| AgentConfig | config.py | 配置管理 |
| MemoryManager | memory.py | 记忆管理 |
| ReflectionManager | reflection.py | 反思管理 |
| Storage | store/_core.py | 数据库存储 |
| EmbeddingEngine | embedding_util.py | 嵌入引擎 |
| SystemPromptManager | prompt_manager.py | 提示词管理 |
| ChatRenderer | _gui/_renderer.py | HTML 渲染 |
| SkillManager | skills/__init__.py | 技能管理 |

## 核心流程

### 对话流程
```
用户输入 → TkGUI.send_msg()
  → TeaAgent.chat() → OnlineToolSession.chat_stream()
    → Pipeline 执行:
      1. inject_memories     (注入记忆)
      2. add_user_message    (添加用户消息)
      3. summarize_if_needed (必要时摘要)
      4. chat / task / general (三种模式)
      5. tool_loop           (工具调用循环)
    → 流式回调 → GUI 渲染
  → _post_chat_pipeline      (入库 + Token + 摘要)
  → _render_and_show_chat    (HtmlFrame 渲染)
```

### 渲染流程
```
chat_messages[] → _filtered_messages()
  → _group_into_rounds()    (按 user 分组)
  → _chat_to_markdown()     (转 Markdown)
    ├── html.escape()       (HTML 转义)
    ├── _escape_orphan_brackets() (孤立方括号转义)
    └── _build_tool_blocks() (工具轮分组)
  → markdown.markdown()     (Markdown→HTML)
  → _fix_double_escape_in_code() (修复双重转义)
  → _sanitize_html_control_chars() (清洗控制字符)
  → _validate_html_structure() (校验结构)
  → HtmlFrame.load_html()   (渲染)
```

## 最近修复 (2026-05-20)

| 修复 | 文件 | 说明 |
|------|------|------|
| 类常量缺失 | basesession.py | 添加 _KB_THRESHOLD, _DEFAULT_TOOL_THRESHOLD 等 5 个常量 + import os/sys |
| 双重转义误伤 | _markdown.py | _fix_double_escape_in_code 改为精确替换双重转义 pattern，保护内联代码 |

## 索引文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 (函数+类) |
| tags | ctags 格式标签文件 |
| kb.md | 本文档 |
