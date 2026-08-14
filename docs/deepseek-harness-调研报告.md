# DeepSeek Harness 调研报告

> 调研日期：2026-08-14 · 来源：github.com/deepseek-ai/deepseek-harness（39.3k stars, MIT, TypeScript 97%）
> 结论先行：**"一切皆插件" + 事件溯源会话日志 + 完整工具执行流水线** 三大架构支柱，其中 4 项功能可直接落地到 tea_agent。

## 一、项目概况

- **定位**：DeepSeek AI 开源的 agent harness（智能体框架），口号 *Everything is a Plugin*
- **内核**：Cordis（插件挂载/卸载/依赖管理），有配套论文《A Programming Paradigm for Spatiotemporal Composability》
- **状态**：开发者预览（v0.1.0-rc.5），官方明示"将有破坏性变更"
- **运行方式**：`npx @deepseek-ai/dsh web`（Web UI @ 127.0.0.1:3080）
- **四大运行模式**：

| 模式 | 内容 |
|------|------|
| Standard | 完整编码 agent：文件编辑/shell/搜索/skills/规划/目标/子agent/工作流 |
| Code | Standard 全能力 + **Code Mode SDK**：模型写一个 TypeScript 程序编排多步工具调用 |
| Minimal | 仅 shell + str_replace_editor 两工具，用于**基准测试**公平对比模型 |
| Creator | Standard 全能力 + 运行时检查 + 内存中插件实验 + 预设创作 |

## 二、三大架构支柱

### 1. 一切皆插件（Cordis）
- 模型适配器、工具注册表、会话日志、agent loop 本身**都是插件**
- 无特权核心：扩展 = 在旁边挂载插件，注册是"可逆效应"，插件卸载时自动回滚
- Profile/Bundle 分层组合：`web`/`headless` 是模板，用户可 `--patch` 覆盖任意配置行
- `dsh --profile web --dump-config` 打印完整插件树，任何一行都可被 patch 替换

### 2. 事件溯源会话日志（Append-only SessionEvent）
- Session = **append-only 事件日志**，全交互历史的唯一事实源
- LLM 消息历史**从日志派生**（`deriveMessages()`），从不单独存储；重放 = 同事件重新派生
- 事件类型：`turn/start` `step/start` `user/message` `assistant/chunk`（**原始 chunk**，token 级重放保真）`tool/call` `tool/result` `todo/write` `request/header` ...
- **不变量："Model-visible means logged"** — 任何到达模型请求的内容必须能从日志重建，运行时断言
- 从同一事件流派生：**Fork、resume、transcripts、telemetry、search、replay**
- 会话可 **fork**（`ctx.sessions.fork(source, boundary?, childSessionId?)`），分支实验

### 3. 工具执行流水线（完整钩子链）
```
tool/call 事件(执行前记录) → pre-execute 瀑布(hooks/权限/沙箱)
→ monotonic guards(拒绝或弃权) → approval(一次性审批,缺失=拒绝)
→ execute 瀑布(超时/重试/指标) → 工具本体
→ fs/write-intent, fs/edit-intent(文件系统守卫)
→ post-execute 瀑布(接受/阻止/替换/加上下文)
→ 结果归一化(异常→isError) → finalizeContent(内容不变量)
→ tool/result(冻结权威结果) → additionalContexts FIFO(结果后注入)
```

## 三、防御模式（defensive-patterns.md，真实踩坑总结）

1. **正交结果独立报告** — 进程可能同时 timeout 且 exit 0（捕获了信号）；`timedOut`/`signal`/`exitCode` 各报各的，禁止嵌套，否则调用方把截断运行读成成功
2. **公共契约双侧归一化** — 实现方多种错误形态，统一为一种出口再进公共 API；消费者不用猜异常来自哪层
3. **异步状态 ≠ 同步状态** — `whenIdle()` 不代表某条消息的结果；真正拥有 run 的调用方必须显式定义区间（从 durable 收件回执到整体 idle）
4. **Dispose 必须到达静止态** — kill 后要 await done；**先关监听/通知注册表再杀**，让迟到完成保持静默
5. **回调异常隔离在 dispatcher** — 用户 listener 抛异常不得 reject 外层 promise 或饿死后续 listener
6. **环境变量清洗（Scrubbed Env）** — spawn 命令用清洗后环境：**丢弃 `*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASSWORD*`**，防 harness 凭据泄入输出/spill 文件
7. **符号链接安全删除** — symlink/junction 用 `lstatSync().isSymbolicLink()` + `unlinkSync`，不 follow 进目标；Windows `rmSync(link)` 对 junction 抛 ERR_FS_EISDIR

## 四、其他亮点

- **无模型工具结果裁剪**：`ctx.toolResultPruner` 用确定性规则裁剪工具结果（不调 LLM），配合 token-meter 重放测量
- **Capability Seams**：Service Definition + Service Provider + Consumer 三角色；fs/subprocess **共享执行世界**，换 provider（远程沙箱 E2B）→ Bash/PTY/LSP 整体迁移
- **Subagent providers**：inprocess / fork-in-process / dsh-sdk / **acp / codex / claude-code**（委托给其他产品）
- **Hooks 兼容**：hooks-claude-code / hooks-codex，兼容现有生态 hooks 格式
- **Compaction seam**：compaction-basic + compaction-tool-result-pruner 可插拔

## 五、对 tea_agent 的借鉴清单（按优先级）

### P0 — 安全缺陷（实证缺失，立即做）
| 项 | 现状 | 行动 |
|----|------|------|
| 环境变量清洗 | `toolkit_exec.py`（661行）**0 处** env 处理，子进程继承全部凭据 | spawn 时构建 scrubbed env，丢弃 `*KEY*/*SECRET*/*TOKEN*/*PASSWORD*` |

### P1 — 高价值，近期
| 项 | 借鉴点 | 落地思路 |
|----|--------|----------|
| 工具执行 hooks | pre/post 瀑布 + approval + 结果改写 + additionalContexts | 在 permission.py 前置检查基础上，加 post-execute 钩子与结果改写链 |
| Session fork | `ctx.sessions.fork()` 分支实验 | chat_history.db 增加 fork lineage（复制事件流到新 topic） |
| 防御模式落地 | 正交结果独立报告 / 回调异常隔离 / dispose 静止态 | 直接写入 toolkit_exec 与后台线程代码 |

### P2 — 中期
| 项 | 借鉴点 | 落地思路 |
|----|--------|----------|
| 事件溯源日志 | append-only 事件流 + 原始 chunk 保真 + "model-visible means logged" | 渐进式：会话表增加 `assistant/chunk` 原始流存储 |
| Code Mode | 模型写代码编排多步工具 | 升级 toolkit_auto_pipeline：支持"模型生成 Python 编排脚本" |
| 无模型压缩 | tool-result-pruner 确定性裁剪 | compaction/ 增加规则式工具结果裁剪，省 LLM 调用 |

### P3 — 探索
| 项 | 借鉴点 |
|----|--------|
| Minimal mode | 两工具最小环境做模型基准测试（可配合 toolkit_eval_loop） |
| Capability seams | fs/subprocess 共享执行世界，整体换 provider |
| Hooks 兼容 | 兼容 Claude Code / Codex hooks 格式 |

## 六、一句话总结

DeepSeek Harness 的三个设计哲学值得我们吸收：
1. **可追溯性即基础设施**：append-only 事件日志让 fork/resume/replay/search 全部免费获得
2. **能力可替换性优先于能力本身**：每项能力都是可换的插件/seam，换来整体迁移能力
3. **防御模式文档化**：把踩过的坑写成 bug-class 规则，新人/新代码直接对照

最急迫的收获：**给 toolkit_exec 加环境变量清洗**（安全缺陷），以及**工具执行 post-hooks**（能力增强）。
