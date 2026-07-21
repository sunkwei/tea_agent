# version: 1.1.0 — 6 phase modes + backward compat (pragmatic→develop)

import logging

logger = logging.getLogger("toolkit")

def toolkit_mode(action: str, text: str = "", mode: str = ""):
    """
    Agent 工作阶段模式管理。6 个 phase mode + 兼容旧 pragmatic/creative。

    Phase Modes:
      design  — 架构设计：分析需求、设计方案、不写代码
      develop — 代码开发：实现功能、修改文件、编译验证
      test    — 测试调试：跑测试、定位根因、修 bug
      review  — 代码审查：审阅质量、发现隐患、给建议
      docs    — 文档撰写：写 README/CHANGELOG/注释
      devops  — 部署发布：构建、打包、发布、CI/CD
      creative — 自由发散（兼容保留）

    兼容: pragmatic→develop, mixed→develop
    模式以 CRITICAL 优先级注入记忆，影响后续所有回复。
    """
    logger.info(f"toolkit_mode: action={action!r}, mode={mode!r}, text={repr(text)[:80]}")

    import json
    import re

    # ── 各 phase 关键词 ──
    PHASE_KW = {  # noqa: N806
        "design": [
            "设计", "架构", "方案", "规划", "选型", "权衡", "评估",
            "design", "architecture", "plan", "proposal", "blueprint",
            "可行性", "技术方案", "调研", "对比", "原型", "prototype",
            "模块划分", "接口设计", "数据模型", "流程图",
            "toolkit_explr", "toolkit_search", "toolkit_plan", "toolkit_kb",
        ],
        "develop": [
            "实现", "开发", "编写", "添加", "修改", "删除", "重构",
            "implement", "develop", "code", "add", "modify", "remove", "refactor",
            "功能", "feature", "逻辑", "logic", "接口", "api", "算法", "algorithm",
            "必须", "需要", "要求", "确保", "保证", "确定",
            "toolkit_edit", "toolkit_self_evolve", "toolkit_exec", "toolkit_file",
        ],
        "test": [
            "测试", "单测", "覆盖", "回归", "调试", "排查", "定位",
            "test", "debug", "coverage", "pytest", "unittest", "mock",
            "报错", "错误", "异常", "崩溃", "失败", "断言",
            "修复", "fix", "bug", "defect", "fault", "traceback",
            "toolkit_run_tests", "toolkit_lsp",
        ],
        "review": [
            "审查", "评审", "review", "检查", "审视", "审计",
            "代码质量", "code quality", "安全", "security", "性能", "performance",
            "规范", "standard", "最佳实践", "best practice", "反模式",
            "隐患", "漏洞", "vulnerability", "风险",
            "toolkit_diff", "toolkit_lsp", "toolkit_search",
        ],
        "docs": [
            "文档", "说明", "readme", "changelog", "注释", "手册",
            "documentation", "docs", "docstring", "guide", "tutorial",
            "记录", "record", "总结", "summary", "撰写", "编写",
            "toolkit_read_pyproject", "toolkit_kb",
        ],
        "devops": [
            "部署", "发布", "构建", "打包", "上线", "回滚",
            "deploy", "release", "build", "package", "publish", "rollback",
            "版本", "version", "bump", "ci/cd", "pipeline", "docker",
            "toolkit_build", "toolkit_release_version", "toolkit_git_push_all_remotes",
        ],
    }

    # ── 各模式指令（格式化多行，注入为 CRITICAL memory）──
    MODE_INSTRUCTIONS = {  # noqa: N806
        "design": (
            "🏗️ 当前处于【架构设计模式】。你的角色是架构设计师：\n"
            "1. 分析需求、识别约束、评估可行性\n"
            "2. 设计方案：模块划分、接口定义、数据流、技术选型\n"
            "3. 输出：架构图（文字描述）、方案对比表、关键决策理由\n"
            "4. ❌ 不写代码、不修改文件、不执行编译\n"
            "5. 优先使用：toolkit_explr / toolkit_search / toolkit_plan / toolkit_kb"
        ),
        "develop": (
            "💻 当前处于【代码开发模式】。你的角色是开发工程师：\n"
            "1. 理解需求 → 制定修改计划 → 逐文件实施\n"
            "2. 修改前备份，修改后编译验证\n"
            "3. 一次只改一个关注点，保持变更可回滚\n"
            "4. 输出：代码 diff + 修改说明 + 测试结果\n"
            "5. 优先使用：toolkit_edit / toolkit_self_evolve / toolkit_exec / toolkit_run_tests"
        ),
        "test": (
            "🧪 当前处于【测试调试模式】。你的角色是测试/调试工程师：\n"
            "1. 运行测试 → 分析失败 → 定位根因 → 修复 → 回归\n"
            "2. 只修复 bug，不重构架构，不添加新功能\n"
            "3. 每次修复后验证全量测试通过\n"
            "4. 输出：失败原因 + 修复方案 + 测试结果\n"
            "5. 优先使用：toolkit_run_tests / toolkit_lsp / toolkit_exec / toolkit_file"
        ),
        "review": (
            "🔍 当前处于【代码审查模式】。你的角色是代码复审专家：\n"
            "1. 通读整体结构 → 逐段分析 → 关注正确性/可读性/安全性/性能\n"
            "2. 评审意见要具体、可操作，附带代码示例\n"
            "3. ❌ 不修改代码，只给出改进建议\n"
            "4. 输出：问题分级（严重/建议/风格）+ 改进方案\n"
            "5. 优先使用：toolkit_file / toolkit_diff / toolkit_lsp / toolkit_search"
        ),
        "docs": (
            "📝 当前处于【文档撰写模式】。你的角色是技术文档工程师：\n"
            "1. 整理项目结构、API 说明、使用指南\n"
            "2. 更新 README / CHANGELOG / 注释\n"
            "3. ❌ 不修改功能代码\n"
            "4. 输出：Markdown 文档，清晰、结构好\n"
            "5. 优先使用：toolkit_file / toolkit_read_pyproject / toolkit_kb"
        ),
        "devops": (
            "🚀 当前处于【部署发布模式】。你的角色是 DevOps 工程师：\n"
            "1. 版本管理、构建打包、发布部署\n"
            "2. 处理 CI/CD、依赖管理、环境配置\n"
            "3. ❌ 不修改业务逻辑代码\n"
            "4. 输出：构建日志 + 发布说明 + 验证结果\n"
            "5. 优先使用：toolkit_build / toolkit_release_version / toolkit_git_push_all_remotes"
        ),
        # 兼容旧模式
        "pragmatic": (
            "💻 当前处于【代码开发模式】(兼容 pragmatic)。你的角色是开发工程师：\n"
            "1. 结构化思考，分步验证，考虑边界条件\n"
            "2. 修改前备份，修改后编译验证\n"
            "3. 优先使用：toolkit_edit / toolkit_self_evolve / toolkit_exec / toolkit_run_tests"
        ),
        "creative": (
            "🎨 当前处于【自由发散模式】。你可以：\n"
            "1. 打破边界：无视常规约束，大胆提出疯狂想法\n"
            "2. 跨域联想：把不同领域的概念碰撞，创造新连接\n"
            "3. 反向思维：如果反过来会怎样？如果放大100倍？如果归零？\n"
            "4. 输出风格：诗意、画面感、故事性，用隐喻和类比\n"
            "5. 优先使用：toolkit_search / toolkit_kb / toolkit_screenshot"
        ),
        "mixed": (
            "💻 当前处于【代码开发模式】(默认)。你的角色是开发工程师：\n"
            "1. 理解需求 → 制定计划 → 逐文件实施\n"
            "2. 修改前备份，修改后编译验证\n"
            "3. 优先使用：toolkit_edit / toolkit_self_evolve / toolkit_exec / toolkit_run_tests"
        ),
    }

    MODE_ALIASES = {"pragmatic": "develop", "mixed": "develop"}  # noqa: N806
    ALL_MODES = set(MODE_INSTRUCTIONS.keys())  # noqa: N806

    def _detect_phase(input_text: str) -> str:
        """根据关键词评分检测最匹配的 phase mode。"""
        if not input_text or not input_text.strip():
            return "develop"
        text_lower = input_text.lower()
        scores = {}
        for phase, kws in PHASE_KW.items():
            score = 0
            for kw in kws:
                if kw.lower() in text_lower:
                    score += 3 if kw in text_lower.split() else 1
            scores[phase] = score

        # 额外规则加权
        if re.search(r'(设计|架构|方案|选型|可行性)', input_text):
            scores["design"] += 4
        if re.search(r'(实现|开发|修改|添加|删除|重构|必须|需要)', input_text):
            scores["develop"] += 3
        if re.search(r'(测试|调试|修复|bug|报错|异常|失败)', input_text):
            scores["test"] += 5
        if re.search(r'(审查|review|检查|代码质量|安全|隐患)', input_text):
            scores["review"] += 4
        if re.search(r'(文档|readme|changelog|说明|总结|注释)', input_text):
            scores["docs"] += 4
        if re.search(r'(部署|发布|构建|打包|版本|release)', input_text):
            scores["devops"] += 4

        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "develop"

    def _resolve_mode(target: str) -> str:
        """解析模式：别名 → 实际 mode，无效 → develop。"""
        if target in ALL_MODES:
            return target
        if target in MODE_ALIASES:
            return MODE_ALIASES[target]
        return "develop"

    def _get_memory_manager():
        """获取 memory manager。"""
        from tea_agent.memory import MemoryManager
        from tea_agent.store import Storage
        try:
            from tea_agent.session_ref import get_agent
            agent = get_agent()
            if agent and hasattr(agent, "db"):
                return MemoryManager(agent.db, extraction_threshold=1, dedup_threshold=0.3)
        except Exception:
            logger.exception('op_failed')

        return MemoryManager(Storage(), extraction_threshold=1, dedup_threshold=0.3)

    def _get_existing_mode_memory(mm):
        """获取现有 mode memory。"""
        all_mems = mm.storage.get_active_memories(limit=100)
        for m in all_mems:
            c = m.get("content") or ""
            if m.get("category") == "instruction" and "当前处于" in c and "模式" in c:
                return m
        return None

    def _set_mode(mm, target_mode: str, old_mem=None):
        """设置模式（删除旧 memory + 写入新 memory）。"""
        if old_mem:
            mm.storage.delete_memory(old_mem["id"])
        instruction = MODE_INSTRUCTIONS.get(target_mode, MODE_INSTRUCTIONS["develop"])
        mm.storage.add_memory(
            content=instruction,
            category="instruction",
            priority=0,
            importance=5,
            tags="mode,phase,personality",
        )
        return target_mode

    def _current_mode(mm) -> str:
        """读取当前 mode。"""
        m = _get_existing_mode_memory(mm)
        if not m:
            return "develop"
        c = m.get("content", "")
        if "架构设计" in c:
            return "design"
        if "代码开发" in c:
            return "develop"
        if "测试调试" in c:
            return "test"
        if "代码审查" in c:
            return "review"
        if "文档撰写" in c:
            return "docs"
        if "部署发布" in c:
            return "devops"
        if "自由发散" in c:
            return "creative"
        return "develop"

    _VALID_MSG = "支持: design/develop/test/review/docs/devops/creative (兼容 pragmatic→develop, mixed→develop)"  # noqa: N806
    _LABELS = {  # noqa: N806
        "design": "🏗️ 架构设计 — 分析需求、设计方案、不写代码",
        "develop": "💻 代码开发 — 实现功能、修改文件、编译验证",
        "test": "🧪 测试调试 — 跑测试、定位根因、修 bug",
        "review": "🔍 代码审查 — 审阅质量、发现隐患、给建议",
        "docs": "📝 文档撰写 — 写 README/CHANGELOG/注释",
        "devops": "🚀 部署发布 — 构建、打包、发布、CI/CD",
        "creative": "🎨 自由发散 — 异想天开、跨域联想、打破边界",
    }

    # === 主逻辑 ===
    if action == "detect":
        detected = _detect_phase(text)
        return {"ok": True, "detected": detected, "text_snippet": text[:100] if text else "", "labels": _LABELS, "returncode": 0}

    elif action == "switch":
        resolved = _resolve_mode(mode)
        if resolved == "develop" and mode not in ALL_MODES and mode not in MODE_ALIASES:
            return {"ok": False, "error": f"无效模式: {mode}", "returncode": 1}
        mm = _get_memory_manager()
        old = _get_existing_mode_memory(mm)
        _set_mode(mm, resolved, old)
        return {"ok": True, "switched_to": resolved, "requested": mode, "instruction": MODE_INSTRUCTIONS.get(resolved, "")[:100] + "...", "returncode": 0}

    elif action == "auto":
        detected = _detect_phase(text)
        mm = _get_memory_manager()
        current = _current_mode(mm)
        if detected == current:
            return {"ok": True, "mode": detected, "switched": False, "reason": "模式未变化", "returncode": 0}
        old = _get_existing_mode_memory(mm)
        _set_mode(mm, detected, old)
        return {"ok": True, "mode": detected, "switched": True, "from": current, "to": detected, "instruction": MODE_INSTRUCTIONS.get(detected, "")[:100] + "...", "returncode": 0}

    elif action == "status":
        mm = _get_memory_manager()
        old = _get_existing_mode_memory(mm)
        if old:
            current = _current_mode(mm)
            return {"ok": True, "has_mode": True, "mode": current, "content": old["content"], "priority": old["priority"], "id": old["id"], "labels": _LABELS, "returncode": 0}
        else:
            return {"ok": True, "has_mode": False, "mode": "develop (default)", "message": "未设置模式，默认 develop", "tip": "使用 toolkit_mode(action='auto', text='用户输入')", "valid_modes": list(_LABELS.keys()), "returncode": 0}

    else:
        return {"ok": False, "error": f"未知 action: {action}", "returncode": 1}


def meta_toolkit_mode() -> dict:
    """Meta for toolkit_mode v1.1.0 — 6 phase modes."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_mode",
            "description": (
                "Agent 工作阶段模式管理。6 个 phase："
                "design=架构设计(不写代码)/develop=代码开发/test=测试调试/"
                "review=代码审查/docs=文档撰写/devops=部署发布。"
                "兼容旧 pragmatic→develop, creative=自由发散。"
                "detect=自动检测/switch=手动切换/status=查看当前/auto=检测+切换"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["detect", "switch", "status", "auto"],
                        "description": "detect/switch/status/auto"
                    },
                    "text": {
                        "type": "string",
                        "description": "用户输入文本，用于自动检测模式"
                    },
                    "mode": {
                        "type": "string",
                        "enum": [
                            "design", "develop", "test", "review", "docs", "devops",
                            "creative", "pragmatic", "mixed"
                        ],
                        "description": (
                            "[switch] 目标模式: design/develop/test/review/docs/devops/creative, "
                            "兼容 pragmatic→develop, mixed→develop"
                        )
                    },
                },
                "required": ["action"]
            }
        }
    }
