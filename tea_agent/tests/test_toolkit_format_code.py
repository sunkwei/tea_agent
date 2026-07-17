"""Tests for toolkit_format_code module."""

import os
import tempfile

from tea_agent.toolkit.toolkit_format_code import _detect_language


def test_detect_language_python():
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        fpath = f.name
    try:
        assert _detect_language(fpath) == "python"
    finally:
        os.unlink(fpath)


def test_detect_language_cpp():
    with tempfile.NamedTemporaryFile(suffix=".cpp", delete=False) as f:
        fpath = f.name
    try:
        assert _detect_language(fpath) == "cpp"
    finally:
        os.unlink(fpath)


def test_detect_language_c_header():
    with tempfile.NamedTemporaryFile(suffix=".h", delete=False) as f:
        fpath = f.name
    try:
        assert _detect_language(fpath) == "cpp"
    finally:
        os.unlink(fpath)


def test_detect_language_unknown():
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        fpath = f.name
    try:
        assert _detect_language(fpath) == "unknown"
    finally:
        os.unlink(fpath)


def test_detect_language_directory_python():
    dirpath = tempfile.mkdtemp()
    try:
        pyfile = os.path.join(dirpath, "test.py")
        with open(pyfile, "w") as f:
            f.write("x = 1\n")
        assert _detect_language(dirpath) == "python"
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)


def test_detect_language_directory_cpp():
    dirpath = tempfile.mkdtemp()
    try:
        cppfile = os.path.join(dirpath, "test.cpp")
        with open(cppfile, "w") as f:
            f.write("int main() { return 0; }\n")
        assert _detect_language(dirpath) == "cpp"
    finally:
        import shutil
        shutil.rmtree(dirpath, ignore_errors=True)
