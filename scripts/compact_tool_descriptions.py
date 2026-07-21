"""安全的工具描述压缩 — 只做无损/低损替换，不做硬截断"""

import os, re

TK_DIR = r'C:\Users\Hetin\work\git\tea_agent\tea_agent\toolkit'
EXCLUDE = {'__init__.py', 'toolkit_comment.py', 'toolkit_test_gui.py',
           'toolkit_clean_comments.py', 'toolkit_read_pyproject.py',
           'toolkit_dynamic_skill.py'}

# === 安全替换规则 ===

# 1. action 枚举描述 → 精炼为枚举值列表（enum list 本身就在 schema 中）
ACTION_DESC_MAP = {
    'spawn=async, spawn_sync=sync blocking, list=all agents, status=query one, collect=completed results, cancel=stop, check_notifications=auto-wake check, cleanup=remove old':
        'spawn(异步)/spawn_sync(同步)/list(列表)/status(状态)/collect(收集)/cancel(取消)/check_notifications(检查通知)/cleanup(清理)',
        
    'list=列表, add=新增(需name/command/schedule), update=更新(需task_id), delete=删除, enable/disable=启停, run=立即执行, start/stop/status=调度线程, test_schedule=测试表达式':
        'list/add/update/delete/enable/disable/run/start/stop/status/test_schedule',
        
    'send=send message to agent, check_inbox=read your inbox, poll=parent collects all, clear=clear inbox':
        'send(发送)/check_inbox(收件箱)/poll(父代收集)/clear(清空)',
        
    'connect=连接服务器, list_tools=列出工具, call_tool=调用工具, disconnect=断开连接, status=查看状态':
        'connect/list_tools/call_tool/disconnect/status',
        
    'scan=重新扫描, list=列出, load=加载单个, search=搜索, recommend=推荐, add=添加, delete=删除':
        'scan/list/load/search/recommend/add/delete',
        
    'create=创建计划, decompose=智能分解目标, show=查看, review=画布审阅(不修改文件), canvas=创建空白画布, step=执行下一步, verify=验证, run=全量执行, resume=恢复, list=列表, delete=删除, insert=插入步骤, replace=替换步骤, delete_step=删除步骤, replan=重新规划':
        'create/decompose/show/review/canvas/step/verify/run/resume/list/delete/insert/replace/delete_step/replan',
        
    'build=构建项目知识库, generate_docs=生成结构化文档, query=查询符号/调用关系/影响/依赖, status=查看知识库状态':
        'build/generate_docs/query/status',
        
    'check=检查未完成任务, resume_todo=恢复TODO执行, resume_plan=恢复Plan执行':
        'check/resume_todo/resume_plan',
        
    'analyze=任务推荐管线, execute=执行管线, templates=查看模板':
        'analyze/execute/templates',
        
    'compile=编译检查, lint=ruff检查, format=black格式化, stats=统计信息, replace=文本替换, count_lines=行数统计':
        'compile/lint/format/stats/replace/count_lines',
        
    'generate=完整 schema, summary=摘要, tools=仅工具列表':
        'generate/summary/tools',
        
    'generate=生成unified diff, preview=预览+冲突检测, apply=git stash→多文件原子应用→lint/test, undo=恢复stash, verify=编译+lint+test':
        'generate/preview/apply/undo/verify',
        
    'add=添加, update=更新, read=读取, list=列表, search=搜索, index=索引, delete=删除, status=状态':
        'add/update/read/list/search/index/delete/status',
        
    'add(添加)/list(列出)/search(搜索)/forget(删除)/extract(提取对话)/auto_extract(自动提取)/semantic_search(语义搜索)/stats(统计)':
        'add/list/search/forget/extract/auto_extract/semantic_search/stats',
        
    'full=全屏, region=指定区域(x,y,w,h), monitor=指定显示器, list_monitors=列出显示器':
        'full/region/monitor/list_monitors',
        
    'detect=根据text自动检测, switch=手动切换, status=查看当前, auto=检测+切换':
        'detect/switch/status/auto',
        
    'list=列表, add=新增, update=更新, delete=删除, enable=启停, run=立即执行':
        'list/add/update/delete/enable/run',
        
    'recognize=识别图片文字, screenshot_ocr=截图并识别':
        'recognize/screenshot_ocr',
        
    'read=读取并分析, start=启动后台监听, stop=停止监听, status=查看状态':
        'read/start/stop/status',
        
    'list=列表, get=读取单个, set=修改, history=变更历史':
        'list/get/set/history',
        
    'single=单条命令, batch=批量并行':
        'single/batch',
        
    'format=格式化, check=检查':
        'format/check',
        
    'add=插入, list=列表, show=查看, run=执行, delete=删除, search=搜索, builtin=重置':
        'add/list/show/run/delete/search/builtin',
        
    'read_tab=激活标签+截图+OCR, read_region=截取屏幕区域, read_window=截取当前窗口':
        'read_tab/read_region/read_window',
        
    'move=鼠标移动, click=点击, double_click=双击, right_click=右键, drag=拖拽, position=获取坐标, scroll=滚动, type=输入文本, press=按键, hotkey=快捷键, screen_size=屏幕分辨率':
        'move/click/double_click/right_click/drag/position/scroll/type/press/hotkey/screen_size',
        
    'check=检查待办, goal=设定目标, done=完成目标, list_goals=列出':
        'check/goal/done/list_goals',
        
    'schema=查看表结构, query=按UUID查记录, topic=按topic_id列所有对话, search=按关键词搜':
        'schema/query/topic/search',
        
    'create=开始清单, check=勾选完成, show=显示, clear=清除, restore=从DB恢复':
        'create/check/show/clear/restore',
        
    'get=获取当前设置, set=设置新提示词, clear=清除自定义, status=查看来源':
        'get/set/clear/status',
        
    'trigger=触发自我分析反思, list=查看最近反思, stats=查看统计':
        'trigger/list/stats',
        
    # 已经精炼的
    'save_script/get_script/list_scripts/delete_script/prepare_script':
        'save/get/list/delete/prepare',
}

# 2. 函数级 description 精简（保留核心功能描述，去掉冗余列举）
FUNC_DESC_MAP = {
    'Sub-agent generation system v2.1. Each sub-agent has an independent LiteSession, isolated from parent context. Supports sync/async spawn, concurrency, status query, result collection, context injection, tool permissions, and inter-agent messaging.':
        '多Agent生成系统。支持同步/异步生成子Agent、并发执行、状态查询、结果收集、上下文注入、工具权限和Agent间通信。',
        
    'Sub-agent message passing. Send/receive/check messages between sub-agents. Use \'send\' to send a message to another agent by ID, \'check_inbox\' to read your own inbox, \'poll\' for parent to collect all pending messages.':
        '子Agent消息通信。支持Agent间发送/接收/检查消息。',
        
    'Plandex 风格 Plan→Execute→Verify 三步工作流。create=创建计划, decompose=智能分解目标, show=查看, review=画布审阅(不修改文件), canvas=创建空白画布, step=执行下一步, verify=验证, run=全量执行, resume=恢复, list=列表, delete=删除, insert=插入步骤, replace=替换步骤, delete_step=删除步骤, replan=重新规划。':
        'Plan→Execute→Verify 三步工作流。支持计划创建、分解、执行、验证和动态调整。',
        
    'Flush a STP (Stream Tag Protocol) buffer to disk. After the model outputs [[STREAM:key=NAME:path=FILE:enc=b64]]...content...[[/STREAM]], call this with stream_id=NAME to write the captured content to FILE. Supports base64 and raw encoding. This side-channel bypasses the JSON tool-call argument size limit entirely.':
        'STP流缓冲区落盘。将模型通过流协议输出的内容写入文件，绕过JSON工具调用参数大小限制。',
        
    '统一长期记忆管理。action: add(添加)/list(列出)/search(搜索)/forget(删除)/extract(提取对话)/auto_extract(自动提取)/semantic_search(语义搜索)/stats(统计)。add需content；forget需id；search可选query；list可选limit。':
        '统一长期记忆管理。支持添加/列出/搜索/删除/提取/语义搜索等操作，持久化存储。',
        
    'Toolkit_auto_pipeline not found in toolkit, using custom_commands style':
        None,  # 删除这条（不是 description，是调试信息）
}

# 3. 参数 description 前缀清除（无损）
PARAM_PREFIX_PATTERNS = [
    (r'\[[^\]]*\]\s*', ''),           # 去掉 [xxx] 前缀
    (r'^(操作类型|处理操作|查询类型|注释模式|目标模式)[：:]\s*', ''),  # 去掉冗余前缀
]


def clean_func_desc(text: str) -> str:
    """清理函数级 description"""
    # 去掉 \\n 换行符
    text = text.replace('\\n', ' ').replace('\n', ' ').strip()
    # 合并多余空格
    text = re.sub(r'\s+', ' ', text)
    return text


def clean_param_desc(text: str) -> str:
    """清理参数 description（只做前缀清除）"""
    for pattern, repl in PARAM_PREFIX_PATTERNS:
        new = re.sub(pattern, repl, text)
        if new != text:
            text = new
            break  # 只做一次
    return text


def process_file(fp: str) -> bool:
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    name = os.path.basename(fp)
    
    # 1. 替换 action 枚举描述（精确匹配）
    for old_desc, new_desc in ACTION_DESC_MAP.items():
        if old_desc in content:
            content = content.replace(old_desc, new_desc)
    
    # 2. 替换函数级描述
    for old_desc, new_desc in FUNC_DESC_MAP.items():
        if old_desc in content:
            if new_desc is None:
                # 删除这行
                content = content.replace(f'"{old_desc}"', '')
            else:
                content = content.replace(old_desc, new_desc)
    
    # 3. 清除参数 description 前缀
    # 找到所有 "description": "..." 并清理前缀
    def clean_param(match):
        full = match.group(0)
        inner = match.group(1)
        cleaned = clean_param_desc(inner)
        if cleaned != inner:
            return f'"description": "{cleaned}"'
        return full
    
    content = re.sub(
        r'"description":\s*"([^"]{5,})"',
        clean_param,
        content
    )
    
    # 4. 函数级 description 清理换行
    def clean_func(match):
        full = match.group(0)
        inner = match.group(1)
        cleaned = clean_func_desc(inner)
        if cleaned != inner:
            return f'"description": "{cleaned}"'
        return full
    
    content = re.sub(
        r'"description":\s*"([^"]{30,})"',
        clean_func,
        content
    )
    
    if content != original:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False


def main():
    modified = 0
    for f in sorted(os.listdir(TK_DIR)):
        if f in EXCLUDE: continue
        fp = os.path.join(TK_DIR, f)
        if not os.path.isfile(fp): continue
        if process_file(fp):
            modified += 1
            print(f'  ✅ {f}')
    
    print(f'\n完成: {modified} 个文件被修改')


if __name__ == '__main__':
    main()
