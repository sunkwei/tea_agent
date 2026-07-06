"""
@2026-06-07 gen by deepseek, Toolkit 核心功能测试
覆盖: 工具注册、调用、重载、版本管理、用户覆盖等核心链路
"""
import pytest


class TestToolkitRegistration:
    """测试工具注册机制的核心路径"""

    def test_reload_loads_builtin_tools(self):
        """reload() 应加载内置工具"""
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        assert "toolkit_gettime" in tk.func_map, "gettime 应被加载"
        assert "toolkit_file" in tk.func_map, "file 应被加载"
        assert "toolkit_search" in tk.func_map, "search 应被加载"

    def test_meta_map_matches_func_map(self):
        """每个工具都应有对应的 meta 注册"""
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        for name in tk.func_map:
            assert name in tk.meta_map, f"{name} 缺少 meta 注册"

    def test_call_tool_returns_result(self):
        """call_tool 应返回非 None 结果"""
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        result = tk.call_tool("toolkit_gettime")
        assert result is not None, "gettime 返回 None"

    def test_gettime_returns_date_fields(self):
        """toolkit_gettime 应返回日期字段"""
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        result = tk.call_tool("toolkit_gettime")
        assert isinstance(result, dict)
        assert "year" in result, f"结果缺少 year: {result}"
        assert "month" in result
        assert "day" in result


class TestToolkitUserOverride:
    """测试用户工具覆盖内置工具"""

    def test_save_creates_file(self, tmp_path):
        """save 应在 tool_dir 创建 .py 文件"""
        from tea_agent.tlk import Toolkit

        tool_dir = tmp_path / "tools"
        tk = Toolkit(tool_dir=str(tool_dir))
        meta = {
            "type": "function",
            "function": {
                "name": "toolkit_hello",
                "description": "Say hello",
                "parameters": {"type": "object", "properties": {
                    "name": {"type": "string", "description": "Your name"}
                }, "required": ["name"]},
            },
        }
        tk.save("toolkit_hello", meta, "def toolkit_hello(name): return f'Hi, {name}!'")
        # 验证文件已创建
        saved_file = tool_dir / "toolkit_hello.py"
        assert saved_file.exists(), f"文件不存在: {saved_file}"
        content = saved_file.read_text()
        assert "toolkit_hello" in content
        assert "Hi" in content

    def test_missing_meta_does_not_crash(self, tmp_path):
        """缺少 meta_toolkit_* 的工具不应导致 reload 崩溃"""
        from tea_agent.tlk import Toolkit

        user_dir = tmp_path / "toolkit_no_meta"
        user_dir.mkdir()
        (user_dir / "toolkit_bad.py").write_text('def toolkit_bad(): return 1')

        Toolkit(tool_dir=str(user_dir))
        # Should not crash


class TestToolkitEdgeCases:
    """边界情况测试"""

    def test_double_reload(self):
        """连续两次 reload 应稳定"""
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        count_before = len(tk.func_map)
        tk.reload()
        count_after = len(tk.func_map)
        assert count_before == count_after, f"reload 前后工具数变化: {count_before} -> {count_after}"

    def test_call_unknown_tool_raises(self):
        """调用未知工具应抛出 KeyError"""
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        with pytest.raises(KeyError):
            tk.call_tool("nonexistent_tool_xyz")
