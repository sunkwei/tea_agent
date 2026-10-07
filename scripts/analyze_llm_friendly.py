#!/usr/bin/env python3
"""分析Python代码的LLM友好度指标。"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class LLMFriendlyAnalyzer:
    """分析Python代码的LLM友好度。"""
    
    def __init__(self):
        self.issues = []
        self.metrics = {
            'function_count': 0,
            'class_count': 0,
            'import_count': 0,
            'avg_function_length': 0,
            'max_function_length': 0,
            'total_lines': 0,
            'comment_lines': 0,
            'docstring_lines': 0,
            'type_hint_count': 0,
            'error_handling_count': 0,
        }
    
    def analyze_file(self, filepath: str) -> Dict:
        """分析单个文件。"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {'error': str(e)}
        
        # 基本指标
        self.metrics['total_lines'] = len(content.split('\n'))
        
        # AST分析
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return {'error': f'Syntax error: {e}'}
        
        # 统计导入
        self.metrics['import_count'] = len([
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ])
        
        # 统计类和函数
        functions = []
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node)
            elif isinstance(node, ast.ClassDef):
                classes.append(node)
        
        self.metrics['function_count'] = len(functions)
        self.metrics['class_count'] = len(classes)
        
        # 分析函数长度
        func_lengths = []
        for func in functions:
            if func.body:
                start_line = func.lineno
                end_line = func.end_lineno if hasattr(func, 'end_lineno') else start_line
                length = end_line - start_line + 1
                func_lengths.append(length)
        
        if func_lengths:
            self.metrics['avg_function_length'] = sum(func_lengths) / len(func_lengths)
            self.metrics['max_function_length'] = max(func_lengths)
        
        # 检查LLM友好度问题
        self._check_llm_issues(tree, content, filepath)
        
        return {
            'metrics': self.metrics.copy(),
            'issues': self.issues.copy(),
            'score': self._calculate_score()
        }
    
    def _check_llm_issues(self, tree: ast.AST, content: str, filepath: str):
        """检查LLM友好度问题。"""
        lines = content.split('\n')
        
        # 检查1：文件顶部是否有过多导入
        import_lines = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                import_lines.append(node.lineno)
        
        if import_lines:
            max_import_line = max(import_lines)
            if max_import_line > 30:  # 前30行都是导入
                self.issues.append({
                    'type': 'too_many_imports',
                    'description': f'文件顶部导入语句过多（到第{max_import_line}行）',
                    'line': 1,
                    'severity': 'medium'
                })
        
        # 检查2：函数过长
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if hasattr(node, 'end_lineno'):
                    length = node.end_lineno - node.lineno + 1
                    if length > 50:  # 超过50行的函数
                        self.issues.append({
                            'type': 'long_function',
                            'description': f'函数 {node.name} 过长（{length}行）',
                            'line': node.lineno,
                            'severity': 'medium'
                        })
        
        # 检查3：缺少类型提示
        functions_without_hints = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                has_hints = False
                if node.returns:
                    has_hints = True
                for arg in node.args.args:
                    if arg.annotation:
                        has_hints = True
                        break
                if not has_hints:
                    functions_without_hints += 1
        
        if functions_without_hints > 0:
            self.issues.append({
                'type': 'missing_type_hints',
                'description': f'{functions_without_hints}个函数缺少类型提示',
                'line': 1,
                'severity': 'low'
            })
        
        # 检查4：缺少文档字符串
        functions_without_docs = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if not (node.body and isinstance(node.body[0], ast.Expr) and 
                       isinstance(node.body[0].value, ast.Str)):
                    functions_without_docs += 1
        
        if functions_without_docs > 0:
            self.issues.append({
                'type': 'missing_docstrings',
                'description': f'{functions_without_docs}个函数缺少文档字符串',
                'line': 1,
                'severity': 'medium'
            })
        
        # 检查5：错误处理不足
        try_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                try_count += 1
        
        if try_count == 0 and self.metrics['function_count'] > 3:
            self.issues.append({
                'type': 'no_error_handling',
                'description': '没有错误处理（try-except）',
                'line': 1,
                'severity': 'low'
            })
    
    def _calculate_score(self) -> int:
        """计算LLM友好度评分（0-100）。"""
        score = 100
        
        # 扣分项
        for issue in self.issues:
            if issue['severity'] == 'high':
                score -= 20
            elif issue['severity'] == 'medium':
                score -= 10
            else:
                score -= 5
        
        # 加分项
        if self.metrics['type_hint_count'] > 10:
            score += 5
        if self.metrics['docstring_lines'] > 10:
            score += 5
        if self.metrics['error_handling_count'] > 3:
            score += 5
        
        return max(0, min(100, score))


def analyze_directory(directory: str, recursive: bool = True) -> Dict:
    """分析目录中的所有Python文件。"""
    results = {}
    path = Path(directory)
    
    pattern = '**/*.py' if recursive else '*.py'
    for py_file in path.glob(pattern):
        analyzer = LLMFriendlyAnalyzer()
        result = analyzer.analyze_file(str(py_file))
        results[str(py_file)] = result
    
    return results


def print_report(results: Dict):
    """打印分析报告。"""
    print("\n" + "="*60)
    print("LLM 友好度分析报告")
    print("="*60)
    
    for filepath, result in results.items():
        if 'error' in result:
            print(f"\n❌ {filepath}: {result['error']}")
            continue
        
        metrics = result['metrics']
        issues = result['issues']
        score = result['score']
        
        print(f"\n📄 {filepath}")
        print(f"   评分: {score}/100")
        print(f"   总行数: {metrics['total_lines']}")
        print(f"   函数数: {metrics['function_count']}")
        print(f"   类数: {metrics['class_count']}")
        print(f"   平均函数长度: {metrics['avg_function_length']:.1f}行")
        print(f"   最大函数长度: {metrics['max_function_length']}行")
        
        if issues:
            print(f"   ⚠️ 问题:")
            for issue in issues:
                print(f"      - [{issue['severity']}] {issue['description']}")
        else:
            print("   ✅ 无LLM友好度问题")
    
    # 汇总统计
    total_files = len(results)
    valid_results = {k: v for k, v in results.items() if 'error' not in v}
    avg_score = sum(r['score'] for r in valid_results.values()) / len(valid_results) if valid_results else 0
    
    print(f"\n📊 汇总统计:")
    print(f"   总文件数: {total_files}")
    print(f"   平均评分: {avg_score:.1f}/100")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python analyze_llm_friendly.py <目录或文件> [--no-recursive]")
        sys.exit(1)
    
    target = sys.argv[1]
    recursive = "--no-recursive" not in sys.argv
    
    if os.path.isfile(target):
        analyzer = LLMFriendlyAnalyzer()
        result = analyzer.analyze_file(target)
        print_report({target: result})
    elif os.path.isdir(target):
        results = analyze_directory(target, recursive)
        print_report(results)
    else:
        print(f"错误: {target} 不存在")
        sys.exit(1)
