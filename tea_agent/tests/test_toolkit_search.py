"""Tests for toolkit_search module."""

import os
import tempfile

from tea_agent.toolkit.toolkit_search import _search_symbol


def _make_py_file(content="def foo():\n    pass\n"):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f.write(content)
    f.close()
    return f.name


def test_search_symbol_found():
    dirpath = tempfile.mkdtemp()
    try:
        fpath = os.path.join(dirpath, "test_mod.py")
        with open(fpath, "w") as f:
            f.write("def hello():\n    pass\n\ndef world():\n    pass\n")
        result = _search_symbol("hello", dirpath, 20)
        assert result["ok"] is True
        assert any(r["name"] == "hello" for r in result["results"])
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_search_symbol_not_found():
    dirpath = tempfile.mkdtemp()
    try:
        fpath = os.path.join(dirpath, "test_mod.py")
        with open(fpath, "w") as f:
            f.write("def foo():\n    pass\n")
        result = _search_symbol("nonexistent_symbol", dirpath, 20)
        assert result["ok"] is True
        assert "未找到" in result.get("message", "")
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_search_symbol_empty_directory():
    dirpath = tempfile.mkdtemp()
    try:
        result = _search_symbol("foo", dirpath, 20)
        assert result["ok"] is True
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_search_symbol_class():
    dirpath = tempfile.mkdtemp()
    try:
        fpath = os.path.join(dirpath, "test_mod.py")
        with open(fpath, "w") as f:
            f.write("class MyClass:\n    def method(self):\n        pass\n")
        result = _search_symbol("MyClass", dirpath, 20)
        assert result["ok"] is True, f"ok={result.get('ok')}, err={result.get('error')}"
        results = result.get("results", [])
        assert len(results) > 0, f"No class found. result={result}"
        assert results[0]["name"] == "MyClass"
        assert results[0]["type"] == "class"
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)
