"""Tests for toolkit_explr module."""

import os
import tempfile

from tea_agent.toolkit.toolkit_explr import (
    _PYTHON_BUILTINS,
    _build_call_graph,
    _check_index_stale,
)


def test_build_call_graph_empty_dir():
    dirpath = tempfile.mkdtemp()
    try:
        calls, defs, classes = _build_call_graph(dirpath)
        assert isinstance(calls, dict)
        assert isinstance(defs, dict)
        assert isinstance(classes, dict)
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_build_call_graph_simple():
    dirpath = tempfile.mkdtemp()
    try:
        fpath = os.path.join(dirpath, "test_mod.py")
        with open(fpath, "w") as f:
            f.write("def foo():\n    bar()\n\ndef bar():\n    pass\n")
        calls, defs, classes = _build_call_graph(dirpath)
        assert "foo" in defs
        assert "bar" in defs
        assert "foo" in calls
        assert "bar" in calls.get("foo", [])
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_build_call_graph_class():
    dirpath = tempfile.mkdtemp()
    try:
        fpath = os.path.join(dirpath, "test_mod.py")
        with open(fpath, "w") as f:
            f.write("class MyClass:\n    def method(self):\n        pass\n")
        calls, defs, classes = _build_call_graph(dirpath)
        assert "MyClass" in classes
        assert "method" in defs
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_build_call_graph_skips_cache():
    dirpath = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(dirpath, "__pycache__"), exist_ok=True)
        fpath = os.path.join(dirpath, "__pycache__", "cached.py")
        with open(fpath, "w") as f:
            f.write("x = 1\n")
        fpath2 = os.path.join(dirpath, "real.py")
        with open(fpath2, "w") as f:
            f.write("def real():\n    pass\n")
        calls, defs, classes = _build_call_graph(dirpath)
        assert "real" in defs
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_python_builtins():
    assert "print" in _PYTHON_BUILTINS
    assert "len" in _PYTHON_BUILTINS
    assert "range" in _PYTHON_BUILTINS
    assert "append" in _PYTHON_BUILTINS
    assert "self" not in _PYTHON_BUILTINS


def test_check_index_stale_no_index():
    dirpath = tempfile.mkdtemp()
    run_dir = os.path.join(dirpath, ".tea_agent_run")
    os.makedirs(run_dir, exist_ok=True)
    try:
        # No symbol_index.json yet — function will raise FileNotFoundError
        import pytest
        with pytest.raises(FileNotFoundError):
            _check_index_stale(dirpath, run_dir)
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)
