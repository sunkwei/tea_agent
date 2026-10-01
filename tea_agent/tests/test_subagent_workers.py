"""回归测试: toolkit_subagent 的 max_concurrent / TEA_SUBAGENT_WORKERS 真实生效。

历史缺陷: max_concurrent 参数只存在于签名/docstring/schema，从未生效——
全局线程池硬编码 max_workers=5，用户传 10 实际仍 5（accept-and-ignore）。

本组测试钉住行为契约:
  1. TEA_SUBAGENT_WORKERS 决定池初始容量（缺省 5，钳制 [1,64]，非法回退 5）
  2. spawn(max_concurrent=N>当前) 时池扩容到 N
  3. 池只扩不缩（后续小值不缩小）
  4. spawn 后任务经线程池真实提交

元验证: 旧实现（无 _env_workers/_get_executor，_executor 恒为 5）上，
  以下测试因属性缺失 / 池容量恒 5 而全部变红。
"""

import importlib
from unittest.mock import patch

import pytest

MOD = "tea_agent.toolkit.toolkit_subagent"


@pytest.fixture
def subagent_mod(monkeypatch):
    """提供模块并保证模块级池状态在测试间隔离。"""
    monkeypatch.delenv("TEA_SUBAGENT_WORKERS", raising=False)
    mod = importlib.import_module(MOD)
    saved = (mod._executor, mod._executor_workers)
    # 用全新小池替换，避免污染其他测试
    from concurrent.futures import ThreadPoolExecutor
    mod._executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="subagent-t")
    mod._executor_workers = 5
    yield mod
    mod._executor.shutdown(wait=False)
    mod._executor, mod._executor_workers = saved


class TestEnvWorkers:
    """TEA_SUBAGENT_WORKERS 解析（纯函数 _env_workers）。"""

    def test_env_workers_default(self, subagent_mod):
        assert subagent_mod._env_workers() == 5

    def test_env_workers_value(self, subagent_mod, monkeypatch):
        monkeypatch.setenv("TEA_SUBAGENT_WORKERS", "12")
        assert subagent_mod._env_workers() == 12

    def test_env_workers_invalid_falls_back(self, subagent_mod, monkeypatch):
        monkeypatch.setenv("TEA_SUBAGENT_WORKERS", "not-a-number")
        assert subagent_mod._env_workers() == 5

    def test_env_workers_clamps_low(self, subagent_mod, monkeypatch):
        monkeypatch.setenv("TEA_SUBAGENT_WORKERS", "-3")
        assert subagent_mod._env_workers() == 1

    def test_env_workers_clamps_high(self, subagent_mod, monkeypatch):
        monkeypatch.setenv("TEA_SUBAGENT_WORKERS", "9999")
        assert subagent_mod._env_workers() == 64


class TestPoolScaling:
    """max_concurrent 扩容行为（只扩不缩）。"""

    def test_spawn_expands_pool(self, subagent_mod):
        with patch(f"{MOD}._execute_subagent") as mock_exec:
            mock_exec.return_value = {"status": "completed"}
            r = subagent_mod.toolkit_subagent(
                action="spawn", goal="t", max_concurrent=10
            )
        assert r["status"] == "pending"
        assert subagent_mod._executor_workers == 10
        assert subagent_mod._executor._max_workers == 10

    def test_pool_never_shrinks(self, subagent_mod):
        with patch(f"{MOD}._execute_subagent"):
            subagent_mod.toolkit_subagent(action="spawn", goal="t", max_concurrent=8)
        assert subagent_mod._executor_workers == 8
        # 更小的 max_concurrent 不缩容
        with patch(f"{MOD}._execute_subagent"):
            subagent_mod.toolkit_subagent(action="spawn", goal="t", max_concurrent=3)
        assert subagent_mod._executor_workers == 8
        assert subagent_mod._executor._max_workers == 8

    def test_spawn_submits_through_pool(self, subagent_mod):
        with patch(f"{MOD}._execute_subagent") as mock_exec:
            mock_exec.return_value = {"status": "completed"}
            subagent_mod.toolkit_subagent(action="spawn", goal="t")
        assert mock_exec.called, "spawn 必须经线程池提交 _execute_subagent"

    def test_clamped_concurrent(self, subagent_mod):
        with patch(f"{MOD}._execute_subagent"):
            subagent_mod.toolkit_subagent(action="spawn", goal="t", max_concurrent=999)
        assert subagent_mod._executor_workers == 64
