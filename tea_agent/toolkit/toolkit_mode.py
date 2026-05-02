## llm generated tool func, created Sat May  2 10:33:15 2026
# version: 1.0.1

# @2026-05-02 gen by tea_agent, Agent人格模式管理：严谨收敛 vs 自由发散
# version: 1.0.1

def toolkit_mode(action: str, text: str = "", mode: str = ""):
    """
    Agent 人格模式管理。两种核心模式：
    
    🎯 pragmatic (严谨收敛):
       - 代码开发、bug排查、需求遵从
       - 结构化思维、逐步验证、精确输出
       - 关键词: bug/修复/代码/错误/测试/debug/实现/需求/严谨
    
    🎨 creative (自由发散):
       - 异想天开、创意发散、打破边界
       - 自由联想、跨域碰撞、大胆假设
       - 关键词: 创意/想象/如果/设计/梦想/探索/未来/故事
    
    模式以 CRITICAL 优先级注入记忆，确保后续所有回复遵循。
    """
    import json
    import re
    
    PRAGMATIC_KW = [
        'bug', '修复', 'fix', '错误', '报错', '异常', '崩溃', '测试', 'test',
        '代码', 'code', '实现', 'implement', '需求', 'requirement', '严谨',
        '审查', 'review', '提交', 'commit', '部署', 'deploy', '性能', 'perf',
        '排查', 'debug', '调试', '编译', 'compile', '优化', 'optimize',
        '接口', 'api', '参数', 'param', '类型', 'type', '重构', 'refactor',
        '文档', 'doc', '版本', 'version', '发布', 'release', '验证', 'verify',
        '配置', 'config', '依赖', 'dependency', '兼容', 'compatible',
        '确保', '保证', '确定', '一定', '必须', '严格',
        'toolkit_exec', 'toolkit_self_evolve', 'toolkit_run_tests',
        'toolkit_config', 'toolkit_pkg', 'toolkit_build',
    ]
    
    CREATIVE_KW = [
        '创意', '想象', '如果', '假设', '可能', '或许', '探索', '实验',
        '设计', 'design', '架构', 'architecture', '梦想', '未来', '故事',
        '小说', '诗', '艺术', '哲学', '思考', '发散', '自由',
        '异想天开', '天马行空', '创新', 'innovate', '突破', '颠覆',
        '隐喻', '比喻', '类比', '跨界', '融合', '混搭', '颠覆性',
        '科幻', '奇幻', '魔法', '宇宙', '维度', '平行世界',
        '灵感', 'inspiration', '创造', 'create', '设想', '构想',
        'toolkit_ocr', 'toolkit_screenshot', 'toolkit_search',
        'toolkit_speak', 'toolkit_kb', 'toolkit_subconscious',
    ]
    
    MODE_INSTRUCTIONS = {
        "pragmatic": (
            "🎯 当前处于【严谨收敛模式】。你必须："
            "1. 结构化思考：分步骤、列出验证点、考虑边界条件"
            "2. 精确执行：代码需编译验证，修改前先理解根因"
            "3. 遵从需求：严格对齐用户意图，不过度发挥"
            "4. 输出风格：简洁、准确、可操作，用表格和代码块"
            "5. 优先使用：toolkit_exec/toolkit_self_evolve/toolkit_run_tests"
        ),
        "creative": (
            "🎨 当前处于【自由发散模式】。你可以："
            "1. 打破边界：无视常规约束，大胆提出疯狂想法"
            "2. 跨域联想：把不同领域的概念碰撞，创造新连接"
            "3. 反向思维：如果反过来会怎样？如果放大100倍？如果归零？"
            "4. 输出风格：诗意、画面感、故事性，用隐喻和类比"
            "5. 优先使用：toolkit_search/toolkit_kb/toolkit_speak/toolkit_subconscious"
        ),
        "mixed": (
            "🔀 当前处于【混合模式】。根据用户输入灵活切换风格："
            "技术问题用严谨收敛、创意话题用自由发散。"
            "自行判断最合适的回应方式。"
        ),
    }
    
    def _detect_mode(input_text: str) -> str:
        if not input_text or not input_text.strip():
            return "mixed"
        text_lower = input_text.lower()
        prag_score = 0
        creat_score = 0
        for kw in PRAGMATIC_KW:
            if kw.lower() in text_lower:
                prag_score += 3 if kw in text_lower.split() else 1
        for kw in CREATIVE_KW:
            if kw.lower() in text_lower:
                creat_score += 3 if kw in text_lower.split() else 1
        if re.search(r'(如果|假设|想象|可否|能否|怎么样|如何设计)', input_text):
            creat_score += 2
        if re.search(r'(必须|需要|要求|修复|实现|添加|删除|修改)', input_text):
            prag_score += 2
        if prag_score > creat_score * 1.5:
            return "pragmatic"
        elif creat_score > prag_score * 1.5:
            return "creative"
        else:
            return "mixed"
    
    def _get_memory_manager():
        from tea_agent.memory import MemoryManager
        from tea_agent.store import Storage
        return MemoryManager(Storage(), extraction_threshold=1, dedup_threshold=0.3)
    
    def _get_existing_mode_memory(mm):
        all_mems = mm.storage.get_active_memories(limit=100)
        for m in all_mems:
            c = m.get("content") or ""
            if m.get("category") == "instruction" and "当前处于" in c and "模式" in c:
                return m
        return None
    
    def _set_mode(mm, target_mode: str, old_mem=None):
        if old_mem:
            mm.storage.delete_memory(old_mem["id"])
        instruction = MODE_INSTRUCTIONS.get(target_mode, MODE_INSTRUCTIONS["mixed"])
        mm.storage.add_memory(
            content=instruction,
            category="instruction",
            priority=0,
            importance=5,
            tags="mode,tone,personality",
        )
        return target_mode
    
    def _current_mode(mm):
        m = _get_existing_mode_memory(mm)
        if not m:
            return "mixed"
        c = m.get("content", "")
        if "严谨收敛" in c: return "pragmatic"
        if "自由发散" in c: return "creative"
        return "mixed"
    
    # === 主逻辑 ===
    if action == "detect":
        detected = _detect_mode(text)
        return (0, json.dumps({
            "detected": detected,
            "text_snippet": text[:100] if text else "",
            "labels": {
                "pragmatic": "🎯 严谨收敛 — 代码开发、bug排查、需求遵从",
                "creative": "🎨 自由发散 — 异想天开、创意发散、打破边界",
                "mixed": "🔀 混合 — 根据具体情况灵活切换",
            }
        }, ensure_ascii=False, indent=2), "")
    
    elif action == "switch":
        if mode not in ("pragmatic", "creative", "mixed"):
            return (1, "", f"无效模式: {mode}。支持: pragmatic/creative/mixed")
        mm = _get_memory_manager()
        old = _get_existing_mode_memory(mm)
        _set_mode(mm, mode, old)
        return (0, json.dumps({
            "switched_to": mode,
            "instruction": MODE_INSTRUCTIONS.get(mode, "")[:80] + "...",
        }, ensure_ascii=False, indent=2), "")
    
    elif action == "auto":
        detected = _detect_mode(text)
        mm = _get_memory_manager()
        current = _current_mode(mm)
        if detected == current:
            return (0, json.dumps({"mode": detected, "switched": False, "reason": "模式未变化"}, ensure_ascii=False), "")
        old = _get_existing_mode_memory(mm)
        _set_mode(mm, detected, old)
        return (0, json.dumps({
            "mode": detected, "switched": True,
            "from": current, "to": detected,
            "instruction": MODE_INSTRUCTIONS.get(detected, "")[:80] + "...",
        }, ensure_ascii=False, indent=2), "")
    
    elif action == "status":
        mm = _get_memory_manager()
        old = _get_existing_mode_memory(mm)
        if old:
            return (0, json.dumps({
                "has_mode": True,
                "content": old["content"],
                "priority": old["priority"],
                "id": old["id"],
            }, ensure_ascii=False, indent=2), "")
        else:
            return (0, json.dumps({
                "has_mode": False,
                "message": "未设置模式。默认使用 mixed。",
                "tip": "使用 toolkit_mode(action='auto', text='用户输入') 自动检测并设置",
            }, ensure_ascii=False, indent=2), "")
    
    else:
        return (1, "", f"未知 action: {action}")


def meta_toolkit_mode() -> dict:
    return {"type": "function", "function": {"name": "toolkit_mode", "description": "Agent 人格模式管理。detect=基于用户输入自动检测模式, switch=手动切换, status=查看当前。严谨(pragmatic)=代码开发/排bug/遵从需求；自由(creative)=异想天开/发散创意/打破边界。模式以CRITICAL记忆注入，影响后续所有回复。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["detect", "switch", "status", "auto"], "description": "detect=根据text自动检测, switch=手动切换, status=查看当前, auto=检测+切换"}, "text": {"type": "string", "description": "[detect/auto] 用户输入文本，用于自动检测模式"}, "mode": {"type": "string", "enum": ["pragmatic", "creative", "mixed"], "description": "[switch] 目标模式: pragmatic=严谨收敛, creative=自由发散, mixed=自动"}}, "required": ["action"]}}}


def meta_toolkit_mode() -> dict:
    return {"type": "function", "function": {"name": "toolkit_mode", "description": "Agent 人格模式管理。detect=基于用户输入自动检测模式, switch=手动切换, status=查看当前。严谨(pragmatic)=代码开发/排bug/遵从需求；自由(creative)=异想天开/发散创意/打破边界。模式以CRITICAL记忆注入，影响后续所有回复。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["detect", "switch", "status", "auto"], "description": "detect=根据text自动检测, switch=手动切换, status=查看当前, auto=检测+切换"}, "text": {"type": "string", "description": "[detect/auto] 用户输入文本，用于自动检测模式"}, "mode": {"type": "string", "enum": ["pragmatic", "creative", "mixed"], "description": "[switch] 目标模式: pragmatic=严谨收敛, creative=自由发散, mixed=自动"}}, "required": ["action"]}}}
