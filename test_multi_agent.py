"""
# @2026-05-27 gen by Tea Agent, 多Agent系统单元测试
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """测试所有模块可以正常导入"""
    print("=" * 60)
    print("测试1: 模块导入")
    
    from tea_agent.multi_agent.sub_agent import SubAgentWrapper, SubAgentConfig
    print("  ✅ sub_agent 导入成功")
    
    from tea_agent.multi_agent.agent_pool import AgentPool
    print("  ✅ agent_pool 导入成功")
    
    from tea_agent.multi_agent.task_decomposer import TaskDecomposer, SubTask
    print("  ✅ task_decomposer 导入成功")
    
    from tea_agent.multi_agent.result_aggregator import ResultAggregator
    print("  ✅ result_aggregator 导入成功")
    
    from tea_agent.multi_agent.orchestrator import MultiAgentOrchestrator
    print("  ✅ orchestrator 导入成功")
    
    from tea_agent.multi_agent import (
        SubAgentWrapper, SubAgentConfig,
        AgentPool, TaskDecomposer, SubTask,
        ResultAggregator, MultiAgentOrchestrator,
    )
    print("  ✅ __init__ 导入成功")
    
    print()

def test_sub_agent_config():
    """测试 SubAgentConfig"""
    print("=" * 60)
    print("测试2: SubAgentConfig")
    
    from tea_agent.multi_agent.sub_agent import SubAgentConfig
    
    config = SubAgentConfig(
        name="test_agent",
        role="测试Agent",
        max_iterations=10,
    )
    assert config.name == "test_agent"
    assert config.role == "测试Agent"
    assert config.max_iterations == 10
    assert config.api_key is None  # 默认None，继承父Agent
    print("  ✅ 配置创建和字段验证通过")
    
    # 测试默认值
    config2 = SubAgentConfig(name="default")
    assert config2.max_history == 5
    assert config2.shared_tools == True
    assert config2.tool_whitelist is None
    print("  ✅ 默认值验证通过")
    print()

def test_subtask():
    """测试 SubTask"""
    print("=" * 60)
    print("测试3: SubTask")
    
    from tea_agent.multi_agent.task_decomposer import SubTask
    
    task = SubTask(
        id="task_1",
        description="审查代码",
        agent_type="reviewer",
        dependencies=["task_0"],
        priority=1,
    )
    assert task.id == "task_1"
    assert task.dependencies == ["task_0"]
    
    d = task.to_dict()
    assert d["id"] == "task_1"
    
    task2 = SubTask.from_dict(d)
    assert task2.description == task.description
    print("  ✅ SubTask 创建/序列化/反序列化通过")
    print()

def test_task_decomposer_rules():
    """测试规则分解"""
    print("=" * 60)
    print("测试4: TaskDecomposer 规则分解")
    
    from tea_agent.multi_agent.task_decomposer import TaskDecomposer
    
    decomposer = TaskDecomposer(agent_types=["coder", "reviewer", "general"])
    
    # 代码任务
    subtasks = decomposer._decompose_with_rules("编写一个Python函数实现快速排序")
    assert len(subtasks) > 0
    assert any("分析" in t.description for t in subtasks)
    assert any("编写" in t.description for t in subtasks)
    print(f"  ✅ 代码任务分解: {len(subtasks)} 个子任务")
    
    # 搜索任务
    subtasks2 = decomposer._decompose_with_rules("搜索项目中所有使用OpenAI的代码")
    assert len(subtasks2) == 1
    assert "搜索" in subtasks2[0].description
    print(f"  ✅ 搜索任务分解: {len(subtasks2)} 个子任务")
    
    # 通用任务
    subtasks3 = decomposer._decompose_with_rules("帮我看看天气")
    assert len(subtasks3) == 1
    print(f"  ✅ 通用任务分解: {len(subtasks3)} 个子任务")
    print()

def test_execution_order():
    """测试执行顺序"""
    print("=" * 60)
    print("测试5: 执行顺序排序")
    
    from tea_agent.multi_agent.task_decomposer import TaskDecomposer, SubTask
    
    decomposer = TaskDecomposer()
    
    t1 = SubTask(id="t1", description="任务1")
    t2 = SubTask(id="t2", description="任务2", dependencies=["t1"])
    t3 = SubTask(id="t3", description="任务3", dependencies=["t1"])
    t4 = SubTask(id="t4", description="任务4", dependencies=["t2", "t3"])
    
    batches = decomposer.get_execution_order([t1, t2, t3, t4])
    
    assert t1 in batches[0], f"t1 should be in first batch, got {batches[0]}"
    assert t4 in batches[-1], f"t4 should be in last batch, got {batches[-1]}"
    print(f"  ✅ 拓扑排序: {len(batches)} 批")
    print()

def test_result_aggregator():
    """测试结果合并器"""
    print("=" * 60)
    print("测试6: ResultAggregator")
    
    from tea_agent.multi_agent.task_decomposer import SubTask
    from tea_agent.multi_agent.result_aggregator import ResultAggregator
    
    aggregator = ResultAggregator()
    
    # 多结果合并
    subtasks = [
        SubTask(id="t1", description="任务1", agent_role="分析"),
        SubTask(id="t2", description="任务2", agent_role="执行"),
    ]
    results = {"t1": "分析完成，发现3个问题", "t2": "执行完成，修改了2个文件"}
    
    merged = aggregator._aggregate_simple(subtasks, results, "原始任务")
    assert "任务执行报告" in merged
    assert "分析完成" in merged
    assert "执行完成" in merged
    assert "2/2" in merged
    print("  ✅ 多结果合并通过")
    
    # 单结果（直接返回）
    single_result = aggregator.aggregate(
        [SubTask(id="t1", description="唯一任务")],
        {"t1": "唯一结果"},
    )
    assert single_result == "唯一结果"
    print("  ✅ 单结果直通通过")
    
    # 摘要
    long_text = "A" * 500
    summary = aggregator.summarize_result(long_text, max_chars=200)
    assert len(summary) <= 200
    print("  ✅ 文本摘要通过")
    print()

def test_agent_pool():
    """测试Agent池"""
    print("=" * 60)
    print("测试7: AgentPool")
    
    from tea_agent.multi_agent.agent_pool import AgentPool
    
    pool = AgentPool(max_workers=2)
    
    pool.register_agent_type("helper", role="助手", max_iterations=5)
    assert "helper" in pool._agent_types
    print("  ✅ Agent类型注册通过")
    
    agent = pool.create_agent("my_helper", type_name="helper")
    assert "my_helper" in pool.active_agents
    assert agent is not None
    print("  ✅ Agent创建通过")
    
    # 重复创建返回现有实例
    agent2 = pool.create_agent("my_helper", type_name="helper")
    assert agent is agent2
    print("  ✅ 重复创建去重通过")
    
    pool.remove_agent("my_helper")
    assert "my_helper" not in pool.active_agents
    print("  ✅ Agent移除通过")
    
    pool.shutdown_all()
    print()

def test_orchestrator():
    """测试编排器"""
    print("=" * 60)
    print("测试8: MultiAgentOrchestrator")
    
    from tea_agent.multi_agent.orchestrator import MultiAgentOrchestrator
    
    orch = MultiAgentOrchestrator(max_workers=2)
    
    assert orch.pool is not None
    assert orch.decomposer is not None
    assert orch.aggregator is not None
    print("  ✅ 编排器创建通过")
    
    # 验证默认类型
    assert "general" in orch.pool._agent_types
    assert "coder" in orch.pool._agent_types
    assert "reviewer" in orch.pool._agent_types
    print(f"  ✅ 默认类型: {list(orch.pool._agent_types.keys())}")
    
    # 注册自定义类型
    orch.register_agent_type("security", role="安全专家", max_iterations=10)
    assert "security" in orch.pool._agent_types
    print("  ✅ 自定义类型注册通过")
    
    # 状态查询
    status = orch.get_status()
    assert status["max_workers"] == 2
    print(f"  ✅ 状态查询: max_workers={status['max_workers']}, types={status['agent_types']}")
    
    orch.shutdown()
    print()

def test_config_integration():
    """测试配置集成"""
    print("=" * 60)
    print("测试9: 配置集成")
    
    from tea_agent.config import MultiAgentConfig, SubAgentDef, AgentConfig
    
    # MultiAgentConfig 默认值
    ma = MultiAgentConfig()
    assert ma.enabled == False
    assert ma.max_workers == 4
    assert ma.auto_decompose == True
    print("  ✅ MultiAgentConfig 默认值通过")
    
    # SubAgentDef
    sa = SubAgentDef(name="test", agent_type="coder", role="测试")
    assert sa.name == "test"
    assert sa.agent_type == "coder"
    print("  ✅ SubAgentDef 创建通过")
    
    # AgentConfig 包含 multi_agent
    ac = AgentConfig()
    assert ac.multi_agent is not None
    assert isinstance(ac.multi_agent, MultiAgentConfig)
    print("  ✅ AgentConfig.multi_agent 集成通过")
    print()

def test_toolkit_delegate():
    """测试委派工具"""
    print("=" * 60)
    print("测试10: toolkit_delegate 工具")
    
    from tea_agent.toolkit.toolkit_delegate import (
        toolkit_delegate, meta_toolkit_delegate,
        set_orchestrator, get_orchestrator,
    )
    
    # 元数据验证
    meta = meta_toolkit_delegate()
    assert meta["type"] == "function"
    assert meta["function"]["name"] == "toolkit_delegate"
    print("  ✅ 委派工具元数据通过")
    
    # 无编排器时调用
    result = toolkit_delegate(task="测试任务")
    assert "未初始化" in result
    print("  ✅ 无编排器时的错误处理通过")
    
    print()

def test_toolkit_sub_agent():
    """测试子Agent汇报工具"""
    print("=" * 60)
    print("测试11: toolkit_sub_agent 工具")
    
    from tea_agent.toolkit.toolkit_sub_agent import (
        toolkit_sub_agent_report,
        toolkit_sub_agent_status,
        clear_sub_agent_reports,
    )
    
    # 清除旧数据
    clear_sub_agent_reports()
    
    # 汇报
    r1 = toolkit_sub_agent_report(
        agent_name="test_agent", report_type="progress", message="正在处理"
    )
    assert "已记录" in r1
    print("  ✅ 子Agent汇报通过")
    
    # 查询状态
    status = toolkit_sub_agent_status(agent_name="test_agent")
    assert "test_agent" in status
    print(f"  ✅ 状态查询: {status[:60]}...")
    
    # 全部查询
    all_status = toolkit_sub_agent_status()
    assert "test_agent" in all_status
    print("  ✅ 全部状态查询通过")
    
    clear_sub_agent_reports()
    print()

if __name__ == "__main__":
    tests = [
        test_imports,
        test_sub_agent_config,
        test_subtask,
        test_task_decomposer_rules,
        test_execution_order,
        test_result_aggregator,
        test_agent_pool,
        test_orchestrator,
        test_config_integration,
        test_toolkit_delegate,
        test_toolkit_sub_agent,
    ]
    
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("=" * 60)
    if failed == 0:
        print(f"🎉 全部 {len(tests)} 个测试通过!")
    else:
        print(f"⚠️ {failed}/{len(tests)} 个测试失败")
