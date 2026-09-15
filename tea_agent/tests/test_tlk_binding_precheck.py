"""tlk.call_tool 入参绑定预检测试。

线上 toolkit_exec 的 "got an unexpected keyword argument 'command'" 属全工具通病：
模型给等价但不存在的键。51 个工具逐个加 **kwargs 是打补丁，在唯一汇聚点
（Toolkit.call_tool）预检一次才是修根因。
"""
import pytest

from tea_agent import tlk


@pytest.fixture(scope="module")
def tk():
    return tlk.Toolkit()


class TestBindingPrecheck:
    def test_unknown_kwarg_message_is_self_correcting(self, tk):
        """未知键必须点名该键并列出合法参数名（旧行为只给裸 TypeError 文本）。"""
        with pytest.raises(TypeError) as ei:
            tk.call_tool("toolkit_file", action="read", file_path="x.py")
        msg = str(ei.value)
        assert "file_path" in msg, msg          # 点名模型真正写错的键
        assert "filename" in msg, msg           # 给出正确参数名
        assert "只接受" in msg, msg

    def test_missing_required_arg_is_named(self, tk):
        """缺必填参数时提示里必须含必填清单，否则模型不知道该补什么。"""
        with pytest.raises(TypeError) as ei:
            tk.call_tool("toolkit_file")
        assert "action" in str(ei.value)

    def test_valid_call_unaffected(self, tk):
        """合法调用不得被预检改变行为。"""
        r = tk.call_tool("toolkit_file", action="list", path=".")
        assert isinstance(r, str) and r

    def test_tool_with_var_kwargs_takes_extras(self, tk):
        """声明 **kwargs 的工具（toolkit_exec）自行解释等价键，预检不得拦截。"""
        r = tk.call_tool("toolkit_exec", command="echo precheck-ok", timeout=10)
        assert r["ok"] and r["stdout"].strip() == "precheck-ok", r

    def test_precheck_covers_cached_whitelist_tools(self, tk):
        """预检必须位于缓存分支之前。

        toolkit_file 属缓存白名单：若只在非缓存分支检查，恰好漏掉这类工具
        —— 而它们同样是模型高频传错键的对象。
        """
        assert "toolkit_file" in tk._CACHE_WHITELIST
        with pytest.raises(TypeError) as ei:
            tk.call_tool("toolkit_file", action="read", filename="x",
                         wrong_key_because_model_hallucinated=1)
        assert "wrong_key_because_model_hallucinated" in str(ei.value)

    def test_unknown_tool_still_keyerror(self, tk):
        """不存在的工具仍抛 KeyError（保持既有契约，不得退化成 TypeError）。"""
        with pytest.raises(KeyError):
            tk.call_tool("nonexistent_tool_xyz")


class TestSignatureCacheInvalidation:
    def test_reload_clears_signature_cache(self, tk):
        """签名缓存必须在 reload 后失效。

        否则工具改了参数（save/rollback 后 reload），call_tool 仍按旧签名预检，
        会把新版的合法调用判为非法 —— 制造出一类新的、更难发现的故障。
        """
        tk.call_tool("toolkit_file", action="list", path=".")
        assert "toolkit_file" in tk._sig_cache, "预检应已缓存签名"
        tk.reload()
        assert tk._sig_cache == {}, "reload 后签名缓存未清空"

    def test_cache_repopulated_after_reload(self, tk):
        """清空后必须能重新建立，且不影响正常调用。"""
        tk.reload()
        r = tk.call_tool("toolkit_file", action="list", path=".")
        assert isinstance(r, str) and r
        assert "toolkit_file" in tk._sig_cache


class TestBindingErrorOnCallableWithoutSignature:
    def test_callable_without_signature_is_not_blocked(self, tk, monkeypatch):
        """取不到签名的可调用对象不得被拦截（宁放勿误杀）。

        某些 C 扩展可调用对象 inspect.signature 会抛 ValueError；此时预检必须
        放行、保持原调用行为，而不是把一个能正常工作的工具判死。
        """
        def exploding_signature(_obj, **kw):
            raise ValueError("no signature for builtin")

        monkeypatch.setattr(tlk.inspect, "signature", exploding_signature)
        tk._sig_cache.clear()  # 前序用例已缓存签名，需清空才会真正走到取签名分支
        try:
            assert tk._binding_error("toolkit_file", tk.func_map["toolkit_file"],
                                     {"whatever": 1}) is None
        finally:
            tk._sig_cache.clear()

    def test_typeerror_from_signature_is_not_blocked(self, tk, monkeypatch):
        """inspect.signature 抛 TypeError 时同样放行。"""
        def raising_signature(_obj, **kw):
            raise TypeError("unusable")

        monkeypatch.setattr(tlk.inspect, "signature", raising_signature)
        tk._sig_cache.clear()
        try:
            assert tk._binding_error("toolkit_file", tk.func_map["toolkit_file"], {}) is None
        finally:
            tk._sig_cache.clear()
