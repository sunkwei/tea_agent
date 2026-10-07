#!/usr/bin/env python3
"""优化tea_agent/agent.py的LLM友好度。"""

import ast
import sys
from pathlib import Path


def analyze_agent_py():
    """分析agent.py的结构。"""
    filepath = "tea_agent/agent.py"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    tree = ast.parse(content)
    
    # 统计函数
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append({
                'name': node.name,
                'lineno': node.lineno,
                'end_lineno': getattr(node, 'end_lineno', node.lineno),
                'length': getattr(node, 'end_lineno', node.lineno) - node.lineno + 1
            })
    
    # 找出长函数
    long_functions = [f for f in functions if f['length'] > 50]
    
    print("函数分析:")
    print(f"总函数数: {len(functions)}")
    print(f"长函数数(>50行): {len(long_functions)}")
    
    print("\n长函数列表:")
    for func in long_functions:
        print(f"  {func['name']}: {func['length']}行 (第{func['lineno']}-{func['end_lineno']}行)")
    
    return long_functions


def optimize_post_chat_pipeline():
    """优化_post_chat_pipeline函数。"""
    # 这个函数可以拆分成几个更小的函数：
    # 1. _save_conversation_to_db
    # 2. _update_token_usage
    # 3. _push_to_level2
    # 4. _start_background_threads
    
    pass


def optimize_do_task_evaluation():
    """优化_do_task_evaluation函数。"""
    # 这个函数可以拆分成：
    # 1. _extract_tools_used
    # 2. _evaluate_task
    # 3. _crystallize_skill
    # 4. _save_lessons
    
    pass


if __name__ == "__main__":
    long_functions = analyze_agent_py()
    
    print("\n优化建议:")
    print("1. 将_post_chat_pipeline拆分成4个子函数")
    print("2. 将_do_task_evaluation拆分成4个子函数")
    print("3. 添加类型提示")
    print("4. 添加文档字符串")
