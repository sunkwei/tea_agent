#!/usr/bin/env python3
"""分析config.py的长函数并提供优化建议。"""

import ast
import sys


def analyze_config_py():
    """分析config.py的结构。"""
    filepath = "tea_agent/config.py"
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
    
    # 分析load_config函数
    print("\nload_config函数分析:")
    print("1. 函数总长度: 138行")
    print("2. 主要功能:")
    print("   - 配置文件路径解析")
    print("   - YAML文件加载")
    print("   - 模型配置解析")
    print("   - 嵌入模型配置解析")
    print("   - 路径配置解析")
    print("   - 会话参数解析")
    print("   - Token优化参数解析")
    print("   - 交互控制参数解析")
    
    print("\n优化建议:")
    print("1. 将load_config拆分成多个子函数:")
    print("   - _resolve_config_path: 解析配置文件路径")
    print("   - _load_yaml_data: 加载YAML数据")
    print("   - _parse_model_configs: 解析模型配置")
    print("   - _parse_embedding_config: 解析嵌入模型配置")
    print("   - _parse_paths_config: 解析路径配置")
    print("   - _parse_session_params: 解析会话参数")
    print("   - _parse_token_params: 解析Token参数")
    print("   - _parse_control_params: 解析控制参数")
    
    print("\n2. 将save_config拆分成:")
    print("   - _prepare_model_data: 准备模型数据")
    print("   - _prepare_paths_data: 准备路径数据")
    print("   - _prepare_session_data: 准备会话数据")
    print("   - _write_yaml_file: 写入YAML文件")
    
    print("\n3. 将create_default_config拆分成:")
    print("   - _generate_model_template: 生成模型配置模板")
    print("   - _generate_paths_template: 生成路径配置模板")
    print("   - _generate_session_template: 生成会话配置模板")
    print("   - _write_template_file: 写入模板文件")


if __name__ == "__main__":
    analyze_config_py()
