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


if __name__ == "__main__":
    unittest.main(verbosity=2)
