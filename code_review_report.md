# Tea Agent 代码审查报告

> 生成时间: 2026-07-15
> 审查范围: tea_agent/ 全部模块
> 审查文件数: 100+ Python 文件

---

## 一、总览

| 维度 | 状态 | 说明 |
|------|------|------|
| 语法编译 | ✅ | 核心模块全通过 |
| Lint (ruff) | ⚠️ | 30/100 文件存在问题，共 120+ 条 |
| 冗余代码 | ⚠️ | 2 处死代码，22 处未使用导入 |
| 循环导入 | ⚠️ | 4 组循环依赖（GUI 模块内部） |
| 安全 | ⚠️ | 5 处硬编码安全敏感值 |
| 类型注解 | ⚠️ | 函数注解覆盖率 48.7%，参数 76.3% |

---

## 二、🔴 严重问题 (需立即修复)

### 2.1 未定义名称 (F821) — 运行时必崩溃

| 文件 | 行号 | 问题 |
|------|------|------|
| `agent.py` | 667 | `SkillCrystallizer` 未定义 |
| `agent.py` | 676 | `SkillRegistry` 未定义 |
| `pattern_market.py` | 386,415 | `RoleAgent` 未定义 |
| `acp_agent.py` | 102,103,1416,1417,1419 | `Optional` 未导入 |
| `acp_agent.py` | 127,131,1163,1198 | `Agent` 未导入 |
| `acp_server.py` | 46,49 | `Storage` 未导入 |
| `acp_server.py` | 47,112 | `Agent` 未导入 |
| `server.py` | 1169 | `uvicorn` 未导入 |

### 2.2 死代码 (运行后不可达)

| 文件 | 行号 | 描述 |
|------|------|------|
| `toolkit_ocr.py` | 237 | `return` 后不可达代码 |
| `toolkit_proactive.py` | 153 | `return` 后不可达表达式 |

---

## 三、🟡 中等风险

### 3.1 循环导入

```
tea_agent.gui → tea_agent._gui._renderer → tea_agent.gui
tea_agent.gui → tea_agent._gui._tray → tea_agent.gui
tea_agent.gui → tea_agent._gui._images → tea_agent.gui
```

> 注：这些循环在实际运行时通过 `noqa: E402` 标记绕过，但存在隐患。

### 3.2 硬编码安全值

| 文件 | 行号 | 描述 |
|------|------|------|
| `server.py` | 241,866,1376 | 硬编码 API Key 模式 |
| `toolkit_exec.py` | 579 | 硬编码密码字符串 |
| `toolkit_sudo_gui.py` | 73 | 硬编码密码字符串 |

### 3.3 B904 — `raise ... from` 缺失

`acp_agent.py`, `acp_server.py`, `server.py` 共 4 处 `except` 中 `raise` 未使用 `from err`，丢失异常链。

---

## 四、🟢 轻度/风格问题

### 4.1 分号多语句 (E702)
`demo/snake/renderer.py`, `demo/tetris/generate_tetris_data.py`, `demo/tetris/train_tetris_cnn.py` 共 12 处

### 4.2 try-except-pass (SIM105)
10 处可用 `contextlib.suppress` 替代

### 4.3 if-else→三元运算符 (SIM108)
8 处可简化为三元运算符

### 4.4 类型比较 (E721)
`config.py`, `gui_dialogs.py`, `server.py` 使用 `==` 比较类型

### 4.5 日志 f-string (logging-fstring)
200+ 处 logger 调用使用 f-string 而非延迟求值 % 格式化

### 4.6 硬编码路径
100+ 处硬编码 Unix/Windows 路径（主要是 `/health`, `/v1/chat/completions` 等 URL 路由定义，非 bug）

### 4.7 未使用变量 (F841)
`agent_as_tool.py`, `acp_agent.py`, `test_workflow.py` 等 5 处

---

## 五、统计摘要

| 指标 | 数值 |
|------|------|
| 总函数数 | 2,226 |
| 有类型注解函数 | 1,085 (48.7%) |
| 总参数数 | 3,168 |
| 有类型注解参数 | 2,417 (76.3%) |
| 类属性注解 | 100% |
| 编译错误 | 0 |
| Lint 警告 | 120+ |

---

## 六、修复优先级

### P0 — 阻塞发布
1. 修复 `agent.py` 中 `SkillCrystallizer`/`SkillRegistry` 未导入
2. 修复 `acp_agent.py`/`acp_server.py` 中 `Optional`/`Agent`/`Storage` 未导入
3. 修复 `server.py` 中 `uvicorn` 未导入
4. 修复 `pattern_market.py` 中 `RoleAgent` 未导入

### P1 — 下个版本修复
5. 清理死代码 (`toolkit_ocr.py`, `toolkit_proactive.py`)
6. 修复 `raise ... from err` 异常链丢失
7. 审计硬编码安全值

### P2 — 技术债务
8. 简化 try-except-pass → contextlib.suppress
9. 清理未使用变量和导入
10. 提升 GUI 模块类型注解覆盖率 (当前 ~5%)

---

## 七、正面发现

- ✅ 核心模块 `store/` (DB层) 编译 100% 通过，类型注解优秀
- ✅ `multi_agent/` 子系统架构清晰，`workflow_engine.py` 注解率 85.7%
- ✅ `session/` 模块 100% 函数类型注解
- ✅ `prompt_manager.py`, `config.py` 类型注解覆盖率 95%+
- ✅ DAG 可视化子系统 (`dag_dot_renderer.py`, `_dag_thumbnail.py`) 设计良好
- ✅ 无 Python 3.11+ 兼容性问题
