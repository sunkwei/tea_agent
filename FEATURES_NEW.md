# Tea Agent 新增功能说明

## 2026-05-19 更新：三大代码理解能力增强

### 1. MCP Client 支持 (`toolkit_mcp.py`)

#### 功能概述
MCP (Model Context Protocol) 客户端工具，让 Tea Agent 能够连接外部 MCP Server，使用第三方工具和服务。

#### 使用示例

**连接文件系统 MCP Server：**
```python
toolkit_mcp(
    action='connect',
    server_name='filesystem',
    command='npx',
    args=['-y', '@modelcontextprotocol/server-filesystem', '/path/to/allow']
)
```

**列出可用工具：**
```python
toolkit_mcp(action='list_tools', server_name='filesystem')
```

**调用工具：**
```python
toolkit_mcp(
    action='call_tool',
    server_name='filesystem',
    tool_name='read_file',
    tool_args={'path': '/tmp/test.txt'}
)
```

**查看连接状态：**
```python
toolkit_mcp(action='status')
```

**断开连接：**
```python
toolkit_mcp(action='disconnect', server_name='filesystem')
```

#### 支持的传输方式
- **stdio**（默认）：通过标准输入输出与本地进程通信
- **sse**：通过 Server-Sent Events 与远程服务器通信

#### 安装 MCP 库
```bash
pip install mcp
# 或使用可选依赖
pip install tea_agent[mcp]
```

#### 常见 MCP Server 示例
```bash
# 文件系统
npx -y @modelcontextprotocol/server-filesystem /allowed/path

# 数据库
npx -y @modelcontextprotocol/server-sqlite ./mydb.sqlite

# Git
npx -y @modelcontextprotocol/server-git

# 更多服务器请访问: https://github.com/modelcontextprotocol/servers
```

---

### 2. 代码搜索增强 (`toolkit_search.py`)

#### 功能概述
在互联网搜索基础上，新增项目内代码搜索能力，支持全文搜索和符号搜索。

#### 新增搜索类型

**全文搜索（类似 grep/ripgrep）：**
```python
toolkit_search(
    query='def login',
    search_type='code',
    root_path='/path/to/project',
    glob_pattern='*.py',  # 可选，过滤文件类型
    max_results=20
)
```

**符号搜索（查找函数/类定义）：**
```python
toolkit_search(
    query='MyClass',
    search_type='symbol',
    root_path='/path/to/project',
    max_results=10
)
```

**互联网搜索（原有功能）：**
```python
toolkit_search(
    query='Python async tutorial',
    search_type='web',  # 默认值，可省略
    engine='duckduckgo'  # 或 'baidu'
)
```

#### 实现细节
- **优先使用 ripgrep (rg)**：如果系统安装了 ripgrep，自动使用以获得最佳性能
- **Python 回退实现**：如果 ripgrep 不可用，使用纯 Python 实现的全文搜索
- **智能目录过滤**：自动跳过 `.git`、`node_modules`、`__pycache__`、`venv` 等目录
- **多语言支持**：支持 Python、JavaScript、TypeScript、Java、C/C++、Go、Rust、Ruby 等

#### 返回结果格式
```json
[
  {
    "file": "src/auth.py",
    "line": 42,
    "content": "def login(username, password):",
    "match": "def login"
  },
  {
    "file": "src/api.py",
    "line": 15,
    "content": "class LoginHandler:",
    "match": "Login"
  }
]
```

---

### 3. 高级代码编辑 (`toolkit_edit.py`)

#### 功能概述
提供精准的代码编辑能力，支持 diff/patch 应用、行级插入/删除/替换，替代"全文覆盖写入"的粗暴方式。

#### 编辑操作

**应用 diff/patch：**
```python
toolkit_edit(
    file_path='src/main.py',
    action='apply_patch',
    content='@@ -10,3 +10,4 @@\n def foo():\n+    pass\n     return 1'
)
```

**插入行：**
```python
toolkit_edit(
    file_path='src/main.py',
    action='insert_lines',
    start_line=10,
    new_content='def new_function():\n    pass'
)
```

**删除行：**
```python
toolkit_edit(
    file_path='src/main.py',
    action='delete_lines',
    start_line=10,
    end_line=15
)
```

**替换行：**
```python
toolkit_edit(
    file_path='src/main.py',
    action='replace_lines',
    start_line=10,
    end_line=15,
    new_content='def updated_function():\n    pass'
)
```

**预览变更（不写入文件）：**
```python
toolkit_edit(
    file_path='src/main.py',
    action='preview_patch',
    content='@@ -10,3 +10,4 @@\n...'
)
```

#### 安全特性
- **自动备份**：编辑前自动创建 `.bak` 备份文件（可通过 `backup=False` 禁用）
- **预览模式**：支持预览编辑结果而不实际写入文件
- **智能验证**：应用 patch 前验证上下文匹配
- **双重实现**：优先使用系统 `patch` 命令，回退到 Python 实现

#### 与 `toolkit_file` 的对比

| 特性 | `toolkit_file(write)` | `toolkit_edit` |
|------|----------------------|----------------|
| 编辑粒度 | 全文覆盖 | 行级精准编辑 |
| 适用场景 | 新建文件/小文件 | 大文件/局部修改 |
| 安全性 | 低（覆盖全文件） | 高（只修改目标行） |
| 预览支持 | 否 | 是 |
| 自动备份 | 否 | 是 |
| diff 生成 | 否 | 是 |

---

## 配置更新

### pyproject.toml
- 添加 `jieba>=0.42.0` 到核心依赖（记忆去重使用）
- 添加 `mcp>=1.0.0` 到可选依赖
- 新增 `all` 可选依赖组（包含 desktop + mcp）

### 安装命令
```bash
# 仅安装核心功能
pip install tea_agent

# 安装 MCP 支持
pip install tea_agent[mcp]

# 安装桌面自动化 + MCP
pip install tea_agent[all]
```

---

## 使用场景示例

### 场景 1：分析项目代码结构
```python
# 1. 搜索所有登录相关函数
toolkit_search(query='login', search_type='code', root_path='.', glob_pattern='*.py')

# 2. 查找特定的类定义
toolkit_search(query='AuthService', search_type='symbol', root_path='.')

# 3. 读取相关文件
toolkit_file(action='read', path='src/auth.py')
```

### 场景 2：使用外部工具（通过 MCP）
```python
# 1. 连接数据库 MCP Server
toolkit_mcp(action='connect', server_name='db', command='npx',
           args=['-y', '@modelcontextprotocol/server-sqlite', './data.db'])

# 2. 列出可用数据库工具
toolkit_mcp(action='list_tools', server_name='db')

# 3. 执行查询
toolkit_mcp(action='call_tool', server_name='db',
           tool_name='query', tool_args={'sql': 'SELECT * FROM users'})
```

### 场景 3：精准代码修改
```python
# 1. 搜索需要修改的代码
toolkit_search(query='old_function_name', search_type='code', root_path='src')

# 2. 预览修改效果
toolkit_edit(file_path='src/main.py', action='preview_patch',
            content='@@ -42,3 +42,3 @@\n-def old_name():\n+def new_name():\n     pass')

# 3. 应用修改
toolkit_edit(file_path='src/main.py', action='apply_patch',
            content='@@ -42,3 +42,3 @@\n-def old_name():\n+def new_name():\n     pass')
```

---

## 下一步改进方向

这三个新功能显著提升了 Tea Agent 的代码理解能力，但仍有改进空间：

1. **MCP Server 支持**：让 Tea Agent 自身成为 MCP Server，供其他 AI 工具调用
2. **LSP 集成**：获取代码诊断信息、代码补全、跳转定义等能力
3. **代码格式化**：集成 black/isort 等工具，自动格式化编辑后的代码
4. **多文件编辑**：同时编辑多个相关文件（如重命名函数时更新所有调用点）
5. **重构工具**：提取方法、内联变量、移动类等高级重构能力
