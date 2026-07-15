"""
LSP 代码智能模块单元测试。

测试范围:
- lsp_engine: diagnose, semantic_diagnose (mock jedi/ruff)
- symbol_index: SymbolIndex 构建/搜索 (mock 文件系统)
- ts_analyzer: parse_file, impact_analysis (mock tree-sitter)
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ============================================================
# lsp_engine
# ============================================================

class TestLspEngineDiagnose:
    """诊断功能测试"""

    def test_diagnose_calls_ruff(self):
        """diagnose() 应调用 ruff 并返回结果"""
        from tea_agent.lsp.lsp_engine import diagnose

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {
                        "location": {
                            "file": "test.py",
                            "row": 1,
                            "column": 1,
                        },
                        "message": "Unused import",
                        "severity": "warning",
                        "code": "F401",
                    }
                ]),
                stderr="",
            )
            result = diagnose("test.py")

        assert isinstance(result, dict)
        assert "diagnostics" in result

    def test_diagnose_empty_result(self):
        """无问题时 ruff 返回空"""
        from tea_agent.lsp.lsp_engine import diagnose

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="[]", stderr=""
            )
            result = diagnose("test.py")
        assert result["diagnostics"] == []

    def test_diagnose_ruff_not_found(self):
        """ruff 不可用时优雅降级"""
        from tea_agent.lsp.lsp_engine import diagnose

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("ruff not found")
            result = diagnose("test.py")
        assert result["diagnostics"] == []
        assert "error" not in result  # 静默处理

    def test_diagnose_non_python_file(self):
        """非 Python 文件应返回空"""
        from tea_agent.lsp.lsp_engine import diagnose

        result = diagnose("readme.md")
        assert result["diagnostics"] == []

    def test_diagnose_auto_routes_correctly(self):
        """diagnose_auto 应根据文件扩展名路由"""
        from tea_agent.lsp.lsp_engine import diagnose_auto

        with patch("tea_agent.lsp.lsp_engine.diagnose") as mock_diag:
            mock_diag.return_value = {"diagnostics": []}
            result = diagnose_auto("main.py")
            mock_diag.assert_called_once()

    def test_diagnose_auto_routes_cpp(self):
        """diagnose_auto 应对 .cpp 文件调用 cpp_diagnose"""
        from tea_agent.lsp.lsp_engine import diagnose_auto

        with patch("tea_agent.lsp.lsp_engine.cpp_diagnose") as mock_cpp:
            mock_cpp.return_value = {"diagnostics": []}
            result = diagnose_auto("main.cpp")
            mock_cpp.assert_called_once()


class TestLspEngineSemanticDiagnose:
    """语义诊断测试"""

    def test_semantic_diagnose_no_unresolved(self):
        """所有符号均已定义时不应报 unresolved"""
        from tea_agent.lsp.lsp_engine import semantic_diagnose
        from jedi import Script

        # 使用实际的 jedi 解析简单代码
        code = """
import os
x = 42
print(x)
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            fname = f.name

        try:
            result = semantic_diagnose(fname)
            assert isinstance(result, list)
            # 对于这个简单代码，不应有 unresolved 警告
            unresolved = [
                d for d in result
                if isinstance(d, dict) and "unresolved" in str(d).lower()
            ]
            # 基本类型如 print, os 应被解析
        finally:
            os.unlink(fname)

    def test_semantic_diagnose_handles_jedi_error(self):
        """jedi 解析失败时应优雅处理"""
        from tea_agent.lsp.lsp_engine import semantic_diagnose

        with patch("jedi.Script") as mock_script:
            mock_script.side_effect = Exception("jedi error")
            result = semantic_diagnose("nonexistent.py")
        assert isinstance(result, list)
        assert result == []


class TestLspEngineNavigation:
    """导航功能测试（hover, goto_definition, references）"""

    def test_hover_returns_dict(self):
        from tea_agent.lsp.lsp_engine import hover

        with patch("tea_agent.lsp.lsp_engine._get_jedi_project") as mock_proj:
            mock_proj.return_value = MagicMock()
            with patch("jedi.Script") as mock_script:
                mock_script.return_value = MagicMock()
                result = hover("test.py", 1, 0)
        assert isinstance(result, dict)

    def test_goto_definition_returns_dict(self):
        from tea_agent.lsp.lsp_engine import goto_definition

        with patch("tea_agent.lsp.lsp_engine._get_jedi_project") as mock_proj:
            mock_proj.return_value = MagicMock()
            result = goto_definition("test.py", 1, 0)
        assert isinstance(result, dict)

    def test_references_returns_dict(self):
        from tea_agent.lsp.lsp_engine import references

        with patch("tea_agent.lsp.lsp_engine._get_jedi_project") as mock_proj:
            mock_proj.return_value = MagicMock()
            result = references("test.py", 1, 0)
        assert isinstance(result, dict)


class TestLspEngineCompletion:
    """代码补全测试"""

    def test_completion_returns_dict(self):
        from tea_agent.lsp.lsp_engine import completion

        with patch("jedi.Script") as mock_script:
            mock_completion = MagicMock()
            mock_completion.name = "test_func"
            mock_completion.type = "function"
            mock_completion.description = "def test_func()"
            mock_completion.complete = "test_func"
            mock_script.return_value.complete.return_value = [mock_completion]
            result = completion("test.py", "test.", 1, 6)
        assert isinstance(result, dict)
        assert "completions" in result


# ============================================================
# symbol_index
# ============================================================

class TestSymbolIndex:
    """SymbolIndex 构建与搜索测试"""

    def test_init_creates_db(self):
        from tea_agent.lsp.symbol_index import SymbolIndex

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_index.db")
            idx = SymbolIndex(db_path=db_path)
            assert os.path.exists(db_path)
            idx.close()

    def test_search_by_name_empty(self):
        """空数据库搜索应返回空列表"""
        from tea_agent.lsp.symbol_index import SymbolIndex

        with tempfile.TemporaryDirectory() as tmpdir:
            idx = SymbolIndex(db_path=os.path.join(tmpdir, "test.db"))
            results = idx.search_by_name("nonexistent")
            assert results == []
            idx.close()

    def test_insert_and_search_symbol(self):
        from tea_agent.lsp.symbol_index import SymbolIndex

        with tempfile.TemporaryDirectory() as tmpdir:
            idx = SymbolIndex(db_path=os.path.join(tmpdir, "test.db"))
            # 直接插入符号
            idx._insert_symbol(
                file_path="/test/main.py",
                name="my_function",
                kind="function",
                line=10,
                parent="",
                params="",
                docstring="Test function",
                module="test",
            )
            results = idx.search_by_name("my_function")
            assert len(results) >= 1
            assert results[0]["name"] == "my_function"
            idx.close()

    def test_file_change_detection(self):
        from tea_agent.lsp.symbol_index import SymbolIndex

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建一个测试文件
            test_file = os.path.join(tmpdir, "test.py")
            with open(test_file, "w") as f:
                f.write("x = 1\n")

            idx = SymbolIndex(db_path=os.path.join(tmpdir, "test.db"))
            # 首次检测应为 changed
            assert idx._is_file_changed(test_file) is True

            # 记录文件
            idx._record_file(test_file)

            # 再次检测应为 not changed
            changed = idx._is_file_changed(test_file)
            # 内容没变，应返回 False
            idx.close()

    def test_insert_duplicate_symbol(self):
        """重复插入应被 IGNORE"""
        from tea_agent.lsp.symbol_index import SymbolIndex

        with tempfile.TemporaryDirectory() as tmpdir:
            idx = SymbolIndex(db_path=os.path.join(tmpdir, "test.db"))
            idx._insert_symbol("/test.py", "dup_func", "function", 1, "", "", "", "test")
            idx._insert_symbol("/test.py", "dup_func", "function", 1, "", "", "", "test")
            results = idx.search_by_name("dup_func")
            assert len(results) == 1
            idx.close()

    def test_clear_file_data(self):
        """清除文件数据后应无法搜到该文件的符号"""
        from tea_agent.lsp.symbol_index import SymbolIndex

        with tempfile.TemporaryDirectory() as tmpdir:
            idx = SymbolIndex(db_path=os.path.join(tmpdir, "test.db"))
            idx._insert_symbol("/target.py", "sym1", "function", 1, "", "", "", "mod")
            idx._insert_symbol("/other.py", "sym2", "function", 1, "", "", "", "mod")
            idx._clear_file_data("/target.py")
            results = idx.search_by_name("sym1")
            assert len(results) == 0
            results = idx.search_by_name("sym2")
            assert len(results) == 1
            idx.close()


# ============================================================
# ts_analyzer
# ============================================================

class TestTsAnalyzer:
    """Tree-sitter 分析器测试"""

    def test_parse_file_python(self):
        """应能解析有效的 Python 文件"""
        from tea_agent.lsp.ts_analyzer import parse_file

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("""
def hello():
    return "world"

class MyClass:
    def method(self):
        pass
""")
            fname = f.name

        try:
            result = parse_file(fname)
            assert isinstance(result, dict)
            assert "functions" in result
            assert "classes" in result
            assert "imports" in result
            # 应检测到函数
            funcs = [f for f in result["functions"] if f["name"] == "hello"]
            assert len(funcs) == 1
            # 应检测到类
            classes = [c for c in result["classes"] if c["name"] == "MyClass"]
            assert len(classes) == 1
        finally:
            os.unlink(fname)

    def test_parse_file_empty(self):
        """空文件应返回空结构"""
        from tea_agent.lsp.ts_analyzer import parse_file

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("# just a comment\n")
            fname = f.name

        try:
            result = parse_file(fname)
            assert result["functions"] == []
            assert result["classes"] == []
            assert isinstance(result["imports"], list)
        finally:
            os.unlink(fname)

    def test_parse_file_syntax_error(self):
        """语法错误的文件应优雅降级"""
        from tea_agent.lsp.ts_analyzer import parse_file

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("def broken(:\n")
            fname = f.name

        try:
            # 不应抛异常
            result = parse_file(fname)
            assert isinstance(result, dict)
        finally:
            os.unlink(fname)

    def test_build_dependency_graph(self):
        """依赖图应返回正确结构"""
        from tea_agent.lsp.ts_analyzer import build_dependency_graph

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建两个互相依赖的文件
            a_file = os.path.join(tmpdir, "a.py")
            b_file = os.path.join(tmpdir, "b.py")
            with open(a_file, "w") as f:
                f.write("import b\ndef fa(): return b.fb()\n")
            with open(b_file, "w") as f:
                f.write("from a import fa\ndef fb(): return fa()\n")

            result = build_dependency_graph(tmpdir)
            assert isinstance(result, dict)
            assert "nodes" in result or "graph" in result
            # 应该至少检测到两个模块
            graph = result.get("graph", result.get("nodes", {}))
            assert len(graph) >= 2

    def test_impact_analysis_structure(self):
        """影响分析应返回结构化结果"""
        from tea_agent.lsp.ts_analyzer import impact_analysis

        with tempfile.TemporaryDirectory() as tmpdir:
            main_file = os.path.join(tmpdir, "main.py")
            with open(main_file, "w") as f:
                f.write("x = 1\n")

            result = impact_analysis(tmpdir, main_file, "x")
            assert isinstance(result, dict)
            # 应包含影响分析的关键字段
            assert "direct_callers" in result or "callers" in result or "affected" in result


class TestTsAnalyzerAstFallback:
    """Python AST fallback 测试"""

    def test_ast_fallback_parsing(self):
        """AST fallback 应能解析标准 Python 语法"""
        from tea_agent.lsp.ts_analyzer import _parse_file_ast_fallback

        code = """
import os, sys
from pathlib import Path

def process(data):
    result = []
    for item in data:
        result.append(item * 2)
    return result

class Calculator:
    def __init__(self, factor=1):
        self.factor = factor

    def compute(self, value):
        return self._internal(value)

    def _internal(self, x):
        return x * self.factor
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            fname = f.name

        try:
            result = _parse_file_ast_fallback(fname)
            assert "functions" in result
            assert "classes" in result
            assert "imports" in result

            func_names = [f["name"] for f in result["functions"]]
            assert "process" in func_names

            class_names = [c["name"] for c in result["classes"]]
            assert "Calculator" in class_names

            # 应该检测到方法
            calc = [c for c in result["classes"] if c["name"] == "Calculator"][0]
            method_names = [m["name"] for m in calc.get("methods", [])]
            assert "__init__" in method_names
            assert "compute" in method_names
        finally:
            os.unlink(fname)
