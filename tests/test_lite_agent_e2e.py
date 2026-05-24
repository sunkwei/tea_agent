"""
端到端集成测试：LiteAgent → TaskDecomposer → LiteAgentPool → LiteOrchestrator

使用 mock LLM 验证完整流程，无需真实 API。
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tea_agent.multi_agent import (
    LiteAgent,
    LiteAgentConfig,
    LiteAgentModelConfig,
    LiteAgentPool,
    LiteOrchestrator,
    TaskDecomposer,
    SubTask,
    ResultAggregator,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_mock_response(content: str = "", tool_calls: list = None):
    """构造一个 mock ChatCompletion 响应。"""
    from types import SimpleNamespace

    tc_objs = []
    if tool_calls:
        for tc in tool_calls:
            tc_objs.append(SimpleNamespace(
                id=tc.get("id", "call_1"),
                type="function",
                function=SimpleNamespace(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                ),
            ))

    msg = SimpleNamespace(
        content=content or None,
        tool_calls=tc_objs if tc_objs else None,
    )
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


class TestLiteAgentE2E(unittest.TestCase):
    """端到端测试：LiteAgent 与 mock LLM"""

    def setUp(self):
        self.lite = LiteAgent(config_dict={
            "api_key": "sk-test",
            "api_url": "http://mock:8080/v1",
            "model_name": "mock-model",
            "max_iterations": 5,
            "keep_turns": 3,
        })

        # 注册一个 mock 工具
        def echo_tool(msg: str) -> str:
            return f"ECHO: {msg}"

        self.lite.register_tool("echo", echo_tool, {
            "description": "回显消息",
            "parameters": {
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        })

    def test_lite_agent_with_tool_call(self):
        """测试 LiteAgent 工具调用循环（mock）"""
        # 第一次调用返回 tool_calls，第二次返回最终文本
        mock_responses = [
            _make_mock_response(tool_calls=[{
                "id": "call_1",
                "function": {"name": "echo", "arguments": '{"msg": "Hello World"}'},
            }]),
            _make_mock_response(content="工具已返回: ECHO: Hello World"),
        ]

        with patch.object(self.lite._client.chat.completions, 'create',
                          side_effect=mock_responses):
            result = self.lite.run("用 echo 工具回显 Hello World")

        self.assertIn("ECHO: Hello World", result)
        # 验证历史已更新
        self.assertTrue(any("echo" in str(m) for m in self.lite._history))

    def test_lite_agent_simple_text(self):
        """测试无工具调用的简单回复"""
        mock_response = _make_mock_response(content="你好，有什么可以帮助你的？")

        with patch.object(self.lite._client.chat.completions, 'create',
                          return_value=mock_response):
            result = self.lite.run("你好")

        self.assertIn("你好", result)

    def test_lite_agent_respects_max_iterations(self):
        """测试 max_iterations 限制"""
        # 一直返回 tool_calls，直到达到上限
        tool_call_resp = _make_mock_response(tool_calls=[{
            "id": "call_1",
            "function": {"name": "echo", "arguments": '{"msg": "loop"}'},
        }])

        with patch.object(self.lite._client.chat.completions, 'create',
                          return_value=tool_call_resp):
            result = self.lite.run("无限循环任务")

        self.assertIn("达到最大迭代次数", result)


class TestOrchestratorE2E(unittest.TestCase):
    """端到端测试：LiteOrchestrator 完整流程"""

    def setUp(self):
        self.base_config = {
            "api_key": "sk-test",
            "api_url": "http://mock:8080/v1",
            "model_name": "mock-model",
        }

    def test_orchestrator_single_mode(self):
        """测试编排器单一Agent模式"""
        orch = LiteOrchestrator(config_dict=self.base_config, max_workers=2)

        mock_response = _make_mock_response(content="任务完成：代码已审查")
        with patch.object(orch._master._client.chat.completions, 'create',
                          return_value=mock_response):
            result = orch.execute("审查代码", mode="single")
            # single mode 会走分解+执行的完整流程
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 0)

    def test_orchestrator_manual_mode(self):
        """测试编排器手动模式"""
        orch = LiteOrchestrator(config_dict=self.base_config, max_workers=2)

        subtasks = [
            SubTask(id="t1", description="任务1", agent_type="general"),
            SubTask(id="t2", description="任务2", agent_type="general"),
        ]
        mapping = {"t1": "agent_t1", "t2": "agent_t2"}

        # 注册 general 模板
        orch.register_agent_type("general", role="通用助手")

        # Mock 子Agent的 LLM 调用
        mock_resp = _make_mock_response(content="子任务完成")

        # 需要 mock 各个子Agent
        with patch.object(
            orch._master._client.chat.completions, 'create',
            return_value=mock_resp
        ):
            result = orch.execute_manual("测试任务", subtasks, mapping)
            self.assertIsInstance(result, str)

    def test_full_flow_with_mock_decompose(self):
        """完整流程：分解→分发→收集→合并（mock所有LLM调用）"""
        orch = LiteOrchestrator(config_dict=self.base_config, max_workers=2)

        # 注册类型
        orch.register_agent_type("coder", role="代码专家")
        orch.register_agent_type("reviewer", role="审查专家")

        # Mock 分解器返回预设子任务
        mock_decompose = [
            SubTask(id="t1", description="编写代码", agent_type="coder"),
            SubTask(id="t2", description="审查代码", agent_type="reviewer"),
        ]

        with patch.object(orch.decomposer, 'decompose', return_value=mock_decompose):
            # Mock 子Agent执行
            with patch.object(
                orch._master._client.chat.completions, 'create',
                return_value=_make_mock_response(content="子任务结果")
            ):
                result = orch.execute("实现并审查一个排序函数")
                self.assertIsInstance(result, str)
                self.assertTrue(len(result) > 0)

                # 验证执行历史
                history = orch.get_execution_history()
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0]["mode"], "auto")
                self.assertEqual(len(history[0]["subtasks"]), 2)


class TestTaskDecomposerIntegration(unittest.TestCase):
    """测试 TaskDecomposer 与 LiteAgent 集成"""

    def test_decompose_with_rules_fallback(self):
        """无 LLM 时回退到规则分解"""
        d = TaskDecomposer(agent_types=["coder", "reviewer", "tester"])
        subtasks = d.decompose("编写并测试一个用户登录功能")
        self.assertGreater(len(subtasks), 0)
        for st in subtasks:
            self.assertIsInstance(st, SubTask)
            self.assertTrue(st.id)
            self.assertTrue(st.description)

    def test_execution_order_complex(self):
        """复杂依赖的执行顺序"""
        d = TaskDecomposer()
        tasks = [
            SubTask(id="init", description="初始化", dependencies=[]),
            SubTask(id="build_a", description="构建A", dependencies=["init"]),
            SubTask(id="build_b", description="构建B", dependencies=["init"]),
            SubTask(id="test_a", description="测试A", dependencies=["build_a"]),
            SubTask(id="test_b", description="测试B", dependencies=["build_b"]),
            SubTask(id="integrate", description="集成", dependencies=["test_a", "test_b"]),
        ]
        batches = d.get_execution_order(tasks)
        self.assertEqual(len(batches), 4)
        # [init] → [build_a, build_b] → [test_a, test_b] → [integrate]
        self.assertEqual([t.id for t in batches[0]], ["init"])
        self.assertEqual(set(t.id for t in batches[1]), {"build_a", "build_b"})
        self.assertEqual(set(t.id for t in batches[2]), {"test_a", "test_b"})
        self.assertEqual([t.id for t in batches[3]], ["integrate"])


class TestLiteAgentHistoryManagement(unittest.TestCase):
    """测试对话历史管理"""

    def setUp(self):
        self.lite = LiteAgent(config_dict={
            "api_key": "sk-test",
            "api_url": "http://mock:8080/v1",
            "model_name": "mock-model",
            "keep_turns": 2,
        })

    def test_history_survives_multiple_runs(self):
        """多次 run() 之间历史累积"""
        mock_r = _make_mock_response(content="OK")

        with patch.object(self.lite._client.chat.completions, 'create',
                          return_value=mock_r):
            self.lite.run("任务A")
            self.lite.run("任务B")
            self.lite.run("任务C")

        # keep_turns=2 → 最多保留 4 条消息（2轮）
        self.assertLessEqual(len(self.lite._history), 4)

    def test_reset_history(self):
        """reset_history 清空对话"""
        self.lite._append_to_history("user", "Hello")
        self.lite._append_to_history("assistant", "Hi")
        self.assertEqual(len(self.lite._history), 2)

        self.lite.reset_history()
        self.assertEqual(len(self.lite._history), 0)


class TestConfigYAMLLoading(unittest.TestCase):
    """测试 YAML 配置加载"""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.yaml_path = os.path.join(self.tmpdir, "test_config.yaml")

        yaml_content = """
main_model:
  api_key: sk-yaml-test
  api_url: http://yaml:8080/v1
  model_name: yaml-model
  temperature: 0.3
  max_tokens: 2048

max_iterations: 20
keep_turns: 6
system_prompt: "你是一个测试助手"
"""
        with open(self.yaml_path, "w") as f:
            f.write(yaml_content)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_from_yaml(self):
        """从 YAML 文件加载配置"""
        lite = LiteAgent(config_path=self.yaml_path)
        self.assertEqual(lite._model, "yaml-model")
        self.assertEqual(lite._temperature, 0.3)
        self.assertEqual(lite._max_tokens, 2048)
        self.assertEqual(lite._cfg.max_iterations, 20)
        self.assertEqual(lite._cfg.keep_turns, 6)
        self.assertEqual(lite._system_prompt, "你是一个测试助手")


if __name__ == "__main__":
    unittest.main(verbosity=2)
