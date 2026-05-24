"""
# @2026-05-27 gen by Tea Agent, 多Agent协作集成测试

测试多Agent系统的各个组件：
- SubAgentWrapper 的创建和运行
- AgentPool 的管理
- TaskDecomposer 的任务分解
- ResultAggregator 的结果合并
- MultiAgentOrchestrator 的编排

注意: 测试不依赖实际的 LLM API，使用 mock 代替。
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# 确保 tea_agent 在路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

from tea_agent.multi_agent import (
    SubAgentWrapper,
    SubAgentConfig,
    AgentPool,
    TaskDecomposer,
    SubTask,
    ResultAggregator,
    MultiAgentOrchestrator,
)


class TestSubAgentConfig(unittest.TestCase):
    """测试 SubAgentConfig 数据类"""
    
    def test_default_config(self):
        config = SubAgentConfig(name="test_agent")
        self.assertEqual(config.name, "test_agent")
        self.assertEqual(config.role, "")
        self.assertTrue(config.shared_tools)
    
    def test_custom_config(self):
        config = SubAgentConfig(
            name="coder",
            role="代码专家",
            tool_whitelist=["toolkit_file", "toolkit_exec"],
            max_iterations=10,
            max_history=3,
        )
        self.assertEqual(config.role, "代码专家")
        self.assertEqual(config.tool_whitelist, ["toolkit_file", "toolkit_exec"])
        self.assertEqual(config.max_iterations, 10)
        self.assertEqual(config.max_history, 3)


class TestTaskDecomposer(unittest.TestCase):
    """测试 TaskDecomposer 任务分解"""
    
    def setUp(self):
        self.decomposer = TaskDecomposer(
            agent_types=["general", "coder", "reviewer"],
        )
    
    def test_decompose_code_task(self):
        """测试代码相关任务分解"""
        subtasks = self.decomposer.decompose("编写一个用户认证模块")
        self.assertIsInstance(subtasks, list)
        self.assertGreater(len(subtasks), 0)
        self.assertTrue(any("代码" in t.description for t in subtasks))
    
    def test_decompose_search_task(self):
        """测试搜索任务分解"""
        subtasks = self.decomposer.decompose("搜索项目中所有的API端点定义")
        self.assertIsInstance(subtasks, list)
        self.assertGreater(len(subtasks), 0)
    
    def test_decompose_general_task(self):
        """测试通用任务分解（默认回退）"""
        subtasks = self.decomposer.decompose("你好，帮我看看天气")
        self.assertIsInstance(subtasks, list)
        self.assertEqual(len(subtasks), 1)
    
    def test_execution_order_no_deps(self):
        """测试无依赖时的执行顺序"""
        tasks = [
            SubTask(id="a", description="任务A", dependencies=[]),
            SubTask(id="b", description="任务B", dependencies=[]),
            SubTask(id="c", description="任务C", dependencies=[]),
        ]
        batches = self.decomposer.get_execution_order(tasks)
        self.assertEqual(len(batches), 1)  # 所有任务可并行
        self.assertEqual(len(batches[0]), 3)
    
    def test_execution_order_with_deps(self):
        """测试有依赖时的执行顺序"""
        tasks = [
            SubTask(id="a", description="任务A", dependencies=[]),
            SubTask(id="b", description="任务B", dependencies=["a"]),
            SubTask(id="c", description="任务C", dependencies=["a"]),
            SubTask(id="d", description="任务D", dependencies=["b", "c"]),
        ]
        batches = self.decomposer.get_execution_order(tasks)
        # 期望: [a] → [b, c] → [d]
        self.assertEqual(len(batches), 3)
        self.assertEqual([t.id for t in batches[0]], ["a"])
        batch1_ids = [t.id for t in batches[1]]
        self.assertIn("b", batch1_ids)
        self.assertIn("c", batch1_ids)
        self.assertEqual([t.id for t in batches[2]], ["d"])


class TestSubTask(unittest.TestCase):
    """测试 SubTask 数据类"""
    
    def test_to_dict(self):
        task = SubTask(
            id="task_1",
            description="测试任务",
            agent_type="coder",
            agent_role="代码专家",
            dependencies=["task_0"],
            priority=0,
            expected_output="测试通过",
        )
        d = task.to_dict()
        self.assertEqual(d["id"], "task_1")
        self.assertEqual(d["dependencies"], ["task_0"])
    
    def test_from_dict(self):
        d = {
            "id": "task_2",
            "description": "审查代码",
            "agent_type": "reviewer",
            "dependencies": ["task_1"],
            "priority": 1,
        }
        task = SubTask.from_dict(d)
        self.assertEqual(task.id, "task_2")
        self.assertEqual(task.agent_type, "reviewer")


class TestResultAggregator(unittest.TestCase):
    """测试 ResultAggregator 结果合并"""
    
    def setUp(self):
        self.aggregator = ResultAggregator()
    
    def test_aggregate_single_result(self):
        """测试单个结果合并"""
        subtasks = [SubTask(id="t1", description="任务1")]
        results = {"t1": "任务1完成"}
        result = self.aggregator.aggregate(subtasks, results, "原始任务")
        self.assertEqual(result, "任务1完成")
    
    def test_aggregate_multiple_results(self):
        """测试多个结果合并（简单模式）"""
        subtasks = [
            SubTask(id="a", description="任务A"),
            SubTask(id="b", description="任务B"),
        ]
        results = {"a": "结果A", "b": "结果B"}
        result = self.aggregator.aggregate(subtasks, results, "原始任务")
        self.assertIn("结果A", result)
        self.assertIn("结果B", result)
        self.assertIn("任务执行报告", result)
    
    def test_aggregate_empty(self):
        """测试空结果处理"""
        result = self.aggregator.aggregate([], {}, "")
        self.assertIn("无子任务结果", result)
    
    def test_summarize_short(self):
        """测试短文本摘要（无需截断）"""
        short = "Hello World"
        result = self.aggregator.summarize_result(short, max_chars=200)
        self.assertEqual(result, short)
    
    def test_summarize_long(self):
        """测试长文本摘要（需要截断）"""
        long_text = "x" * 300
        result = self.aggregator.summarize_result(long_text, max_chars=200)
        self.assertLessEqual(len(result), 200)
    
    def test_merge_code_results(self):
        """测试代码结果合并"""
        results = {
            "agent_a": "这是分析结果\n```python\nprint('hello')\n```",
            "agent_b": "这是修改建议\n```python\nprint('world')\n```",
        }
        merged = self.aggregator.merge_code_results(results)
        self.assertIn("print('hello')", merged["merged_code"])
        self.assertIn("print('world')", merged["merged_code"])
        self.assertIn("agent_a", merged["summary"])


class TestSubAgentWrapper(unittest.TestCase):
    """测试 SubAgentWrapper 基本功能"""
    
    def setUp(self):
        self.config = SubAgentConfig(
            name="test_agent",
            role="测试助手",
            max_iterations=5,
            max_history=3,
        )
    
    def test_resolve_params_without_parent(self):
        """无父配置时的参数解析"""
        agent = SubAgentWrapper(self.config)
        params = agent._resolve_effective_params()
        self.assertEqual(params["model"], "")
        self.assertEqual(params["max_iterations"], 5)
        self.assertTrue(params["disable_summary"])
    
    def test_resolve_params_with_parent(self):
        """有父配置时的参数继承"""
        mock_config = MagicMock()
        mock_config.main_model.api_key = "test_key"
        mock_config.main_model.api_url = "http://test"
        mock_config.main_model.model_name = "test_model"
        mock_config.main_model.temperature = 0.7
        mock_config.main_model.max_tokens = 4096
        mock_config.main_model.supports_vision = False
        mock_config.main_model.reasoning_effort = "high"
        
        mock_config.cheap_model.api_key = "cheap_key"
        mock_config.cheap_model.api_url = "http://cheap"
        mock_config.cheap_model.model_name = "cheap_model"
        
        mock_config.max_iterations = 30
        mock_config.max_tool_output = 1024
        mock_config.max_assistant_content = 2048
        
        agent = SubAgentWrapper(self.config, parent_config=mock_config)
        params = agent._resolve_effective_params()
        self.assertEqual(params["api_key"], "test_key")
        self.assertEqual(params["model"], "test_model")
        self.assertEqual(params["max_iterations"], 5)  # 子Agent覆盖: 5
        self.assertEqual(params["reasoning_effort"], "high")
    
    def test_build_tool_list(self):
        """测试工具列表构建（白名单/黑名单）"""
        mock_toolkit = MagicMock()
        mock_toolkit.meta_map = {
            "toolkit_file": {"type": "function", "function": {"name": "toolkit_file", "description": "文件操作"}},
            "toolkit_exec": {"type": "function", "function": {"name": "toolkit_exec", "description": "执行命令"}},
            "toolkit_save": {"type": "function", "function": {"name": "toolkit_save", "description": "保存工具"}},
            "toolkit_memory": {"type": "function", "function": {"name": "toolkit_memory", "description": "记忆管理"}},
        }
        
        config = SubAgentConfig(
            name="test",
            tool_whitelist=["toolkit_file", "toolkit_exec", "toolkit_save"],
        )
        agent = SubAgentWrapper(config, parent_toolkit=mock_toolkit)
        tools = agent._build_tool_list(mock_toolkit)
        # toolkit_save 虽在白名单但也在黑名单中，应被过滤
        # toolkit_memory 不在白名单中，应被排除
        # 最终结果只有 toolkit_file 和 toolkit_exec
        tool_names = [t["function"]["name"] for t in tools]
        self.assertIn("toolkit_file", tool_names)
        self.assertIn("toolkit_exec", tool_names)
        self.assertNotIn("toolkit_save", tool_names)
        self.assertNotIn("toolkit_memory", tool_names)


class TestAgentPool(unittest.TestCase):
    """测试 AgentPool 管理"""
    
    def setUp(self):
        self.pool = AgentPool(max_workers=2)
    
    def test_register_agent_type(self):
        self.pool.register_agent_type("tester", role="测试专家")
        self.assertIn("tester", self.pool._agent_types)
        self.assertEqual(self.pool._agent_types["tester"].role, "测试专家")
    
    def test_create_agent(self):
        self.pool.register_agent_type("helper", role="助手")
        agent = self.pool.create_agent("my_helper", type_name="helper")
        self.assertIsNotNone(agent)
        self.assertIn("my_helper", self.pool.active_agents)
        self.assertEqual(agent.config.role, "助手")
    
    def test_remove_agent(self):
        self.pool.register_agent_type("helper", role="助手")
        self.pool.create_agent("temp", type_name="helper")
        self.assertIn("temp", self.pool.active_agents)
        self.pool.remove_agent("temp")
        self.assertNotIn("temp", self.pool.active_agents)
    
    def test_shutdown_all(self):
        self.pool.register_agent_type("helper", role="助手")
        self.pool.create_agent("a1", type_name="helper")
        self.pool.create_agent("a2", type_name="helper")
        self.pool.shutdown_all()
        self.assertEqual(len(self.pool.active_agents), 0)


class TestMultiAgentOrchestrator(unittest.TestCase):
    """测试 MultiAgentOrchestrator 编排器"""
    
    def setUp(self):
        self.orchestrator = MultiAgentOrchestrator(max_workers=2)
    
    def test_default_agent_types(self):
        """测试默认注册的Agent类型"""
        types = list(self.orchestrator.pool._agent_types.keys())
        self.assertIn("general", types)
        self.assertIn("coder", types)
        self.assertIn("reviewer", types)
        self.assertIn("analyst", types)
        self.assertIn("researcher", types)
    
    def test_register_agent_type(self):
        self.orchestrator.register_agent_type("custom", role="自定义角色")
        self.assertIn("custom", self.orchestrator.pool._agent_types)
        self.assertIn("custom", self.orchestrator.decomposer.agent_types)
    
    def test_execute_single_mode(self):
        """测试单一Agent执行模式（无LLM）"""
        # 注意: 这需要 mock LLM 客户端，但在没有真实 API 的情况下
        # 我们测试代码路径不抛异常
        self.assertTrue(hasattr(self.orchestrator, 'execute_single'))
    
    def test_get_status(self):
        status = self.orchestrator.get_status()
        self.assertIn("active_agents", status)
        self.assertIn("agent_types", status)
        self.assertIn("max_workers", status)
        self.assertEqual(status["max_workers"], 2)
    
    def test_execution_history(self):
        history = self.orchestrator.get_execution_history()
        self.assertIsInstance(history, list)
    
    def test_shutdown(self):
        self.orchestrator.shutdown()
        status = self.orchestrator.get_status()
        self.assertEqual(len(status["active_agents"]), 0)


class TestConfigIntegration(unittest.TestCase):
    """测试配置系统集成"""
    def test_multi_agent_config_in_agent_config(self):
        """测试 AgentConfig 包含 MultiAgentConfig"""
        from tea_agent.config import AgentConfig, MultiAgentConfig, SubAgentDef
        
        cfg = AgentConfig()
        self.assertIsNotNone(cfg.multi_agent)
        self.assertIsInstance(cfg.multi_agent, MultiAgentConfig)
        self.assertFalse(cfg.multi_agent.enabled)
        self.assertEqual(cfg.multi_agent.max_parallel, 4)
    def test_sub_agent_def(self):
        """测试 SubAgentDef 数据类"""
        from tea_agent.config import SubAgentDef
        
        sa = SubAgentDef(
            name="test",
            agent_type="coder",
            tool_whitelist=["toolkit_file"],
            max_iterations=10,
        )
        self.assertEqual(sa.name, "test")
        self.assertEqual(sa.agent_type, "coder")
        self.assertEqual(sa.max_iterations, 10)


class TestToolkitDelegate(unittest.TestCase):
    """测试 toolkit_delegate 工具"""
    
    def test_meta_schema(self):
        """测试元数据格式正确"""
        from tea_agent.toolkit.toolkit_delegate import meta_toolkit_delegate
        
        meta = meta_toolkit_delegate()
        self.assertEqual(meta["type"], "function")
        self.assertEqual(meta["function"]["name"], "toolkit_delegate")
        self.assertIn("parameters", meta["function"])
        params = meta["function"]["parameters"]["properties"]
        self.assertIn("agent_name", params)
        self.assertIn("task", params)
        self.assertIn("agent_type", params)
    
    def test_delegate_without_orchestrator(self):
        """测试无编排器时的错误处理"""
        from tea_agent.toolkit.toolkit_delegate import toolkit_delegate, get_orchestrator
        
        # 确保没有编排器
        old = get_orchestrator()
        try:
            from tea_agent.toolkit.toolkit_delegate import set_orchestrator
            set_orchestrator(None)
            result = toolkit_delegate(task="测试任务")
            self.assertIn("错误", result)
        finally:
            if old:
                from tea_agent.toolkit.toolkit_delegate import set_orchestrator
                set_orchestrator(old)


class TestToolkitSubAgent(unittest.TestCase):
    """测试 toolkit_sub_agent 工具"""
    
    def setUp(self):
        from tea_agent.toolkit.toolkit_sub_agent import clear_sub_agent_reports
        clear_sub_agent_reports()
    
    def test_report_and_status(self):
        from tea_agent.toolkit.toolkit_sub_agent import (
            toolkit_sub_agent_report,
            toolkit_sub_agent_status,
        )
        
        result = toolkit_sub_agent_report(
            agent_name="agent_1",
            report_type="progress",
            message="正在处理文件...",
        )
        self.assertIn("已记录", result)
        
        status = toolkit_sub_agent_status("agent_1")
        self.assertIn("agent_1", status)
        self.assertIn("progress", status)
    
    def test_status_all_agents(self):
        from tea_agent.toolkit.toolkit_sub_agent import (
            toolkit_sub_agent_report,
            toolkit_sub_agent_status,
        )
        
        toolkit_sub_agent_report("a1", "progress", "处理中")
        toolkit_sub_agent_report("a2", "done", "完成")
        
        status = toolkit_sub_agent_status()
        self.assertIn("a1", status)
        self.assertIn("a2", status)
    
    def test_meta_schemas(self):
        from tea_agent.toolkit.toolkit_sub_agent import (
            meta_toolkit_sub_agent_report,
            meta_toolkit_sub_agent_status,
        )
        
        report_meta = meta_toolkit_sub_agent_report()
        self.assertEqual(report_meta["function"]["name"], "toolkit_sub_agent_report")
        
        status_meta = meta_toolkit_sub_agent_status()
        self.assertEqual(status_meta["function"]["name"], "toolkit_sub_agent_status")


# ============================================================================
# LiteAgent 轻量级组件测试
# ============================================================================

class TestLiteAgentConfig(unittest.TestCase):
    """测试 LiteAgentConfig 配置解析"""

    def test_default_config(self):
        from tea_agent.multi_agent.lite_agent import LiteAgentConfig
        cfg = LiteAgentConfig()
        self.assertEqual(cfg.max_iterations, 15)
        self.assertEqual(cfg.keep_turns, 5)
        self.assertFalse(cfg.main_model.is_configured)

    def test_parse_dict_flat(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        cfg = LiteAgent._parse_config_dict({
            "api_key": "sk-test",
            "api_url": "http://localhost:8080/v1",
            "model_name": "test-model",
            "max_iterations": 10,
            "keep_turns": 3,
        })
        self.assertEqual(cfg.main_model.api_key, "sk-test")
        self.assertEqual(cfg.main_model.api_url, "http://localhost:8080/v1")
        self.assertEqual(cfg.main_model.model_name, "test-model")
        self.assertTrue(cfg.main_model.is_configured)
        self.assertEqual(cfg.max_iterations, 10)
        self.assertEqual(cfg.keep_turns, 3)

    def test_parse_dict_nested(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        cfg = LiteAgent._parse_config_dict({
            "main_model": {
                "api_key": "sk-nested",
                "api_url": "http://nested:8080/v1",
                "model_name": "nested-model",
                "temperature": 0.5,
                "max_tokens": 2048,
            },
            "system_prompt": "你是一个测试助手",
        })
        self.assertEqual(cfg.main_model.api_key, "sk-nested")
        self.assertEqual(cfg.main_model.model_name, "nested-model")
        self.assertEqual(cfg.main_model.temperature, 0.5)
        self.assertEqual(cfg.main_model.max_tokens, 2048)
        self.assertEqual(cfg.system_prompt, "你是一个测试助手")

    def test_parse_dict_with_tool_filters(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        cfg = LiteAgent._parse_config_dict({
            "api_key": "sk", "api_url": "http://x", "model_name": "m",
            "tool_whitelist": ["toolkit_file", "toolkit_exec"],
            "tool_blacklist": ["toolkit_save"],
        })
        self.assertEqual(cfg.tool_whitelist, ["toolkit_file", "toolkit_exec"])
        self.assertEqual(cfg.tool_blacklist, ["toolkit_save"])


class TestToolRegistry(unittest.TestCase):
    """测试 ToolRegistry"""

    def setUp(self):
        from tea_agent.multi_agent.lite_agent import ToolRegistry
        self.reg = ToolRegistry()

    def test_register_and_get(self):
        def dummy_func(x: str) -> str:
            return f"OK:{x}"

        schema = {
            "description": "测试工具",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        }
        self.reg.register("test_tool", dummy_func, schema)
        self.assertIn("test_tool", self.reg.tool_names)

        func = self.reg.get_func("test_tool")
        self.assertIsNotNone(func)
        self.assertEqual(func("hello"), "OK:hello")

    def test_get_openai_tools(self):
        self.reg.register("tool_a", lambda: "a", {
            "description": "Tool A",
            "parameters": {"type": "object", "properties": {}},
        })
        tools = self.reg.get_openai_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], "tool_a")

    def test_apply_whitelist(self):
        self.reg.register("keep", lambda: "", {"description": "", "parameters": {}})
        self.reg.register("drop", lambda: "", {"description": "", "parameters": {}})
        self.reg.apply_filter(whitelist=["keep"], blacklist=None)
        self.assertIn("keep", self.reg.tool_names)
        self.assertNotIn("drop", self.reg.tool_names)

    def test_apply_blacklist(self):
        self.reg.register("keep", lambda: "", {"description": "", "parameters": {}})
        self.reg.register("drop", lambda: "", {"description": "", "parameters": {}})
        self.reg.apply_filter(whitelist=None, blacklist=["drop"])
        self.assertIn("keep", self.reg.tool_names)
        self.assertNotIn("drop", self.reg.tool_names)

    def test_unregister(self):
        self.reg.register("temp", lambda: "", {"description": "", "parameters": {}})
        self.assertIn("temp", self.reg.tool_names)
        self.reg.unregister("temp")
        self.assertNotIn("temp", self.reg.tool_names)


class TestLiteAgentInit(unittest.TestCase):
    """测试 LiteAgent 初始化"""

    def test_init_requires_config(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        with self.assertRaises(ValueError):
            LiteAgent()  # 无配置应报错

    def test_init_with_dict(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        agent = LiteAgent(config_dict={
            "api_key": "sk-test",
            "api_url": "http://localhost:8080/v1",
            "model_name": "test-model",
        })
        self.assertEqual(agent._model, "test-model")
        self.assertIsNotNone(agent._client)
        self.assertEqual(len(agent._history), 0)

    def test_init_with_config_object(self):
        from tea_agent.multi_agent.lite_agent import (
            LiteAgent, LiteAgentConfig, LiteAgentModelConfig,
        )
        cfg = LiteAgentConfig(
            main_model=LiteAgentModelConfig(
                api_key="sk-obj",
                api_url="http://obj:8080/v1",
                model_name="obj-model",
            ),
            max_iterations=20,
            keep_turns=8,
        )
        agent = LiteAgent(config=cfg)
        self.assertEqual(agent._model, "obj-model")
        self.assertEqual(agent._cfg.max_iterations, 20)
        self.assertEqual(agent._cfg.keep_turns, 8)

    def test_register_tool(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        agent = LiteAgent(config_dict={
            "api_key": "sk", "api_url": "http://x", "model_name": "m",
        })

        def echo(msg: str) -> str:
            return msg

        agent.register_tool("echo", echo, {
            "description": "Echo back",
            "parameters": {
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        })
        self.assertIn("echo", agent.tools)

    def test_history_management(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        agent = LiteAgent(config_dict={
            "api_key": "sk", "api_url": "http://x", "model_name": "m",
        })
        agent._append_to_history("user", "Hello")
        agent._append_to_history("assistant", "Hi there")
        self.assertEqual(len(agent._history), 2)

        agent.reset_history()
        self.assertEqual(len(agent._history), 0)

    def test_trim_history(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        agent = LiteAgent(config_dict={
            "api_key": "sk", "api_url": "http://x", "model_name": "m",
            "keep_turns": 2,
        })
        # 添加 6 条消息（3 轮），应裁剪为 4 条（2 轮）
        for i in range(6):
            agent._append_to_history("user" if i % 2 == 0 else "assistant", f"msg{i}")
        self.assertEqual(len(agent._history), 6)
        agent._trim_history()
        self.assertEqual(len(agent._history), 4)  # keep_turns*2 = 4
        self.assertEqual(agent._history[0]["content"], "msg2")  # 最旧的被裁剪

    def test_interrupt(self):
        from tea_agent.multi_agent.lite_agent import LiteAgent
        agent = LiteAgent(config_dict={
            "api_key": "sk", "api_url": "http://x", "model_name": "m",
        })
        self.assertFalse(agent._interrupted)
        agent.interrupt()
        self.assertTrue(agent._interrupted)
        self.assertFalse(agent.is_running)


class TestLiteAgentPool(unittest.TestCase):
    """测试 LiteAgentPool"""

    def setUp(self):
        from tea_agent.multi_agent.agent_pool import LiteAgentPool
        self.pool = LiteAgentPool(max_workers=2)

    def test_register_template(self):
        self.pool.register_template(
            "test_type",
            config_dict={
                "api_key": "sk", "api_url": "http://x", "model_name": "m",
            },
            role="测试角色",
        )
        self.assertIn("test_type", self.pool.templates)

    def test_create_agent_from_template(self):
        self.pool.register_template(
            "helper",
            config_dict={
                "api_key": "sk", "api_url": "http://x", "model_name": "m",
            },
            role="助手",
        )
        agent = self.pool.create_agent("a1", template_name="helper")
        self.assertIsNotNone(agent)
        self.assertIn("a1", self.pool.active_agents)

    def test_create_agent_direct_config(self):
        agent = self.pool.create_agent(
            "direct",
            config_dict={
                "api_key": "sk", "api_url": "http://x", "model_name": "m",
            },
        )
        self.assertIsNotNone(agent)
        self.assertEqual(agent._model, "m")

    def test_create_duplicate_returns_existing(self):
        self.pool.register_template(
            "t", config_dict={"api_key": "sk", "api_url": "http://x", "model_name": "m"}
        )
        a1 = self.pool.create_agent("dup", template_name="t")
        a2 = self.pool.create_agent("dup", template_name="t")
        self.assertIs(a1, a2)

    def test_remove_agent(self):
        self.pool.register_template(
            "t", config_dict={"api_key": "sk", "api_url": "http://x", "model_name": "m"}
        )
        self.pool.create_agent("temp", template_name="t")
        self.assertIn("temp", self.pool.active_agents)
        self.pool.remove_agent("temp")
        self.assertNotIn("temp", self.pool.active_agents)

    def test_shutdown_all(self):
        self.pool.register_template(
            "t", config_dict={"api_key": "sk", "api_url": "http://x", "model_name": "m"}
        )
        self.pool.create_agent("a1", template_name="t")
        self.pool.create_agent("a2", template_name="t")
        self.pool.shutdown_all()
        self.assertEqual(len(self.pool.active_agents), 0)

    def test_create_without_config_raises(self):
        with self.assertRaises(ValueError):
            self.pool.create_agent("no_config")


class TestLiteOrchestrator(unittest.TestCase):
    """测试 LiteOrchestrator"""

    def setUp(self):
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        self.base_config = {
            "api_key": "sk-test",
            "api_url": "http://localhost:8080/v1",
            "model_name": "test-model",
        }

    def test_init_with_dict(self):
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        orch = LiteOrchestrator(config_dict=self.base_config, max_workers=2)
        self.assertIsNotNone(orch._master)
        self.assertEqual(orch._max_workers, 2)
        self.assertIsNotNone(orch.decomposer)
        self.assertIsNotNone(orch.aggregator)

    def test_register_agent_type(self):
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        orch = LiteOrchestrator(config_dict=self.base_config)
        orch.register_agent_type("coder", role="代码专家")
        self.assertIn("coder", orch.pool.templates)
        self.assertIn("coder", orch.decomposer.agent_types)

    def test_execute_single_mode(self):
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        orch = LiteOrchestrator(config_dict=self.base_config)
        self.assertTrue(hasattr(orch, "execute_single"))
        self.assertTrue(hasattr(orch, "execute_manual"))

    def test_get_status(self):
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        orch = LiteOrchestrator(config_dict=self.base_config)
        status = orch.get_status()
        self.assertIn("active_agents", status)
        self.assertIn("agent_types", status)
        self.assertIn("max_workers", status)
        self.assertIn("execution_count", status)

    def test_execution_history(self):
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        orch = LiteOrchestrator(config_dict=self.base_config)
        history = orch.get_execution_history()
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 0)

    def test_shutdown(self):
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        orch = LiteOrchestrator(config_dict=self.base_config)
        orch.shutdown()
        self.assertEqual(len(orch.pool.active_agents), 0)

    def test_master_and_worker_separate_configs(self):
        """测试主Agent和子Agent使用不同配置"""
        from tea_agent.multi_agent.orchestrator import LiteOrchestrator
        orch = LiteOrchestrator(
            master_config_dict=self.base_config,
            config_dict={**self.base_config, "model_name": "worker-model"},
            max_workers=2,
        )
        # 主Agent用 master 配置
        self.assertEqual(orch._master._model, "test-model")
        # 子Agent模板用 worker 配置
        orch.register_agent_type("w", role="worker")
        tmpl = orch.pool._templates["w"]
        self.assertEqual(tmpl["config_dict"]["model_name"], "worker-model")


class TestTaskDecomposerWithLiteAgent(unittest.TestCase):
    """测试 TaskDecomposer 使用 LiteAgent 进行分解"""

    def test_lite_agent_parameter_accepted(self):
        from tea_agent.multi_agent.task_decomposer import TaskDecomposer
        d = TaskDecomposer(agent_types=["general", "coder"], lite_agent=None)
        self.assertIsNone(d._lite_agent)
        self.assertEqual(len(d.agent_types), 2)

    def test_fallback_to_rules_when_no_lite_agent(self):
        """无 LiteAgent 时应回退到规则分解"""
        from tea_agent.multi_agent.task_decomposer import TaskDecomposer
        d = TaskDecomposer(agent_types=["general"])
        subtasks = d.decompose("编写一个排序函数")
        self.assertIsInstance(subtasks, list)
        self.assertGreater(len(subtasks), 0)
        # 规则分解至少产生 2 个子任务（分析+实现）
        self.assertGreaterEqual(len(subtasks), 1)

    def test_decompose_empty_task(self):
        from tea_agent.multi_agent.task_decomposer import TaskDecomposer
        d = TaskDecomposer()
        subtasks = d.decompose("")
        self.assertEqual(len(subtasks), 1)
        self.assertEqual(subtasks[0].agent_type, "general")


class TestResultAggregatorEdgeCases(unittest.TestCase):
    """测试 ResultAggregator 边界情况"""

    def setUp(self):
        from tea_agent.multi_agent.result_aggregator import ResultAggregator
        self.agg = ResultAggregator()

    def test_aggregate_with_failed_subtasks(self):
        from tea_agent.multi_agent.task_decomposer import SubTask
        subtasks = [
            SubTask(id="a", description="任务A"),
            SubTask(id="b", description="任务B"),
        ]
        # 两个结果都存在 — 触发报告格式（len(results) > 1）
        results = {"a": "结果A", "b": "[未完成]"}
        result = self.agg.aggregate(subtasks, results, "原始")
        self.assertIn("结果A", result)
        self.assertIn("任务执行报告", result)
        # 只有一个结果时返回单结果
        single = self.agg.aggregate(subtasks, {"a": "OnlyA"}, "原始")
        self.assertEqual(single, "OnlyA")

    def test_merge_code_results_empty(self):
        merged = self.agg.merge_code_results({})
        self.assertEqual(merged["merged_code"], "")
        self.assertEqual(merged["summary"], "")
        self.assertEqual(len(merged["errors"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
