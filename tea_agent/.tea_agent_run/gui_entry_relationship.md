# gui_entry_relationship
<!-- created:2026-05-16 10:24:11 category:analysis tags:gui,main_db_gui,entry,architecture,relationship brief:main_db_gui.py(冻结备份) 与 gui.py(活跃主入口) 的双入口关系说明 -->


# main_db_gui.py 与 gui.py 的关系

## 背景
`main_db_gui.py` 原是 GUI 唯一入口（~2007行，TkGUI 类 70个方法）。为降低修改风险，采用双入口策略。

## 双入口策略

| 文件 | 角色 | 启动方式 |
|------|------|---------|
| `tea_agent/gui.py` | **主入口** (活跃开发) | `python -m tea_agent.gui` |
| `tea_agent/main_db_gui.py` | **救急备份** (冻结) | `python -m tea_agent.main_db_gui` |

## 规则
1. **main_db_gui.py 不再修改**（或极其慎重）。它是 GUI 的最后安全网。
2. **所有 GUI 改动发生在 gui.py 及 _gui/ 包下的组件**。
3. 如果 gui.py 修改导致 GUI 无法启动，开发者在终端用 `python -m tea_agent.main_db_gui` 恢复交互能力，继续与模型对话修复 gui.py。
4. GUI 是唯一的交互通道（与模型对话依赖 GUI），如果 GUI 彻底挂掉且无备份入口，只能 git revert。因此 main_db_gui.py 的冻结至关重要。

## 文件结构
```
tea_agent/
  gui.py             ← 主入口，导入 _gui 组件
  _gui/              ← 私有组件包
    __init__.py
    _interfaces.py
    _tk_impl.py
    _tray.py
    _images.py
    _markdown.py
    _renderer.py
  main_db_gui.py     ← 冻结的紧急回退
```

## 启动方式汇总

| 方式 | 命令 | 状态 |
|------|------|------|
| 主入口 | `python -m tea_agent.gui` | ✅ 解析到 gui.py |
| 紧急回退 | `python -m tea_agent.main_db_gui` | ✅ 自包含 |
| CLI命令 | `tea_agent` (console_scripts) | ✅ |

## 变更历史

### 2026-05-21: 重构 gui/ → _gui/
- `tea_agent/gui/` 目录重命名为 `tea_agent/_gui/`（私有组件包，避免与 gui.py 模块冲突）
- `gui.py` 成为唯一主入口模块（自带 `main()`）
- 删除 `__main__.py`（不再需要桥接到 main_db_gui）
- `python -m tea_agent.gui` 直接解析到 `gui.py`
- commit: `102b755`
