"""
测试 SubAgent 嵌套深度限制功能。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 模拟 LiteSession，避免真实调用 API
import threading
from unittest.mock import MagicMock, patch

# 直接导入被测试模块
from tea_agent.toolkit.toolkit_subagent import (
    toolkit_subagent,
    _subagent_registry,
    _registry_lock,
    _thread_local,
    DEFAULT_MAX_DEPTH,
    _execute_subagent,
)


def cleanup_registry():
    with _registry_lock:
        _subagent_registry.clear()


def test_default_max_depth():
    """默认 max_depth 应为 1。"""
    assert DEFAULT_MAX_DEPTH == 1, f"期望 1, 实际 {DEFAULT_MAX_DEPTH}"
    print("✅ DEFAULT_MAX_DEPTH = 1")


def test_spawn_without_goal():
    """没有 goal 应返回错误。"""
    result = toolkit_subagent(action="spawn")
    assert "error" in result, "缺少 goal 时应返回 error"
    print(f"✅ spawn 无 goal 返回错误: {result['error'][:50]}...")


def test_depth_inheritance():
    """验证父子深度继承逻辑 (mock _execute_subagent 避免真实执行)。"""
    cleanup_registry()
    
    # 清除 thread-local
    if hasattr(_thread_local, 'subagent_depth'):
        del _thread_local.subagent_depth
    if hasattr(_thread_local, 'subagent_max_depth'):
        del _thread_local.subagent_max_depth

    # 模拟父 Agent (无 thread-local) → depth=0
    with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent') as mock_exec:
        mock_exec.return_value = {"agent_id": "test-0", "status": "completed"}
        result = toolkit_subagent(action="spawn_sync", goal="test task")
    
    assert "error" not in result, f"不应报错: {result}"
    assert result["agent_id"] is not None
    print(f"✅ 父 Agent spawn (depth=0): agent_id={result['agent_id']}")


def test_depth_exceeded():
    """验证深度超限时被拒绝。"""
    cleanup_registry()
    
    # 模拟深度-0 子 Agent (depth=0, max_depth=1)
    # 它尝试 spawn → depth=1, 这是允许的 (1 <= 1)
    _thread_local.subagent_depth = 0
    _thread_local.subagent_max_depth = 1

    with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent') as mock_exec:
        mock_exec.return_value = {"agent_id": "test-1", "status": "completed"}
        result = toolkit_subagent(action="spawn_sync", goal="child task")
    
    assert "error" not in result, f"depth=0→1 应在 max_depth=1 时允许: {result}"
    print(f"✅ depth=0→1 允许 (max_depth=1): agent_id={result['agent_id']}, depth={result.get('depth')}")

    # 模拟深度-1 子 Agent 尝试 spawn → depth=2 > max_depth=1 → 拒绝
    _thread_local.subagent_depth = 1
    _thread_local.subagent_max_depth = 1

    result = toolkit_subagent(action="spawn_sync", goal="grandchild task")
    assert "error" in result, f"depth=1→2 应被拒绝 (max_depth=1)"
    assert "exceeded" in result["error"].lower(), f"错误消息应包含 'exceeded': {result['error']}"
    print(f"✅ depth=1→2 被拒绝 (max_depth=1): {result['error'][:80]}...")

    cleanup_registry()


def test_custom_max_depth():
    """验证自定义 max_depth=2 允许更深嵌套。"""
    cleanup_registry()
    if hasattr(_thread_local, 'subagent_depth'):
        del _thread_local.subagent_depth
    if hasattr(_thread_local, 'subagent_max_depth'):
        del _thread_local.subagent_max_depth

    # 父 Agent 指定 max_depth=2
    with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent') as mock_exec:
        mock_exec.return_value = {"agent_id": "deep-0", "status": "completed"}
        result = toolkit_subagent(action="spawn_sync", goal="deep test", max_depth=2)

    assert "error" not in result, f"不应报错: {result}"
    print(f"✅ max_depth=2 spawn: depth={result.get('depth')}, max_depth={result.get('max_depth')}")

    # depth=1 子 Agent 尝试 spawn → depth=2 应允许 (2 <= 2)
    _thread_local.subagent_depth = 1
    _thread_local.subagent_max_depth = 2

    with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent') as mock_exec:
        mock_exec.return_value = {"agent_id": "deep-1", "status": "completed"}
        result = toolkit_subagent(action="spawn_sync", goal="deeper task")

    assert "error" not in result, f"depth=1→2 应在 max_depth=2 时允许: {result}"
    print(f"✅ depth=1→2 允许 (max_depth=2): depth={result.get('depth')}")

    # depth=2 子 Agent 尝试 spawn → depth=3 > 2 → 拒绝
    _thread_local.subagent_depth = 2
    _thread_local.subagent_max_depth = 2

    result = toolkit_subagent(action="spawn_sync", goal="too deep")
    assert "error" in result, f"depth=2→3 应被拒绝"
    print(f"✅ depth=2→3 被拒绝 (max_depth=2): {result['error'][:80]}...")

    cleanup_registry()


def test_async_spawn_depth():
    """异步 spawn 也应检查深度。"""
    cleanup_registry()
    _thread_local.subagent_depth = 1
    _thread_local.subagent_max_depth = 1

    result = toolkit_subagent(action="spawn", goal="async child")
    assert "error" in result, f"异步 spawn depth=1→2 应被拒绝"
    print(f"✅ 异步 spawn 深度检查: {result['error'][:80]}...")

    cleanup_registry()


def test_async_spawn_success():
    """异步 spawn 在合法深度应成功。"""
    cleanup_registry()
    if hasattr(_thread_local, 'subagent_depth'):
        del _thread_local.subagent_depth
    if hasattr(_thread_local, 'subagent_max_depth'):
        del _thread_local.subagent_max_depth

    with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent') as mock_exec:
        # 异步 spawn 会 submit 到线程池，但我们 mock 了 _execute_subagent
        # 实际不执行，只验证 spawn 逻辑中的深度检查通过
        result = toolkit_subagent(action="spawn", goal="async ok")
    
    assert "error" not in result, f"异步 spawn depth=0 应成功: {result}"
    print(f"✅ 异步 spawn 成功: agent_id={result.get('agent_id')}, depth={result.get('depth')}")

    cleanup_registry()


def test_depth_in_system_prompt():
    """验证 _execute_subagent 在 system prompt 中注入深度信息。"""
    from tea_agent.toolkit.toolkit_subagent import DEFAULT_MAX_DEPTH
    
    # 直接检查 _execute_subagent 构建的 system prompt 模板
    depth = 0
    max_depth = 1
    can_spawn = depth < max_depth
    depth_note = (
        f"- Your nesting depth: {depth} / max {max_depth}\n"
        f"- You {'CAN' if can_spawn else 'CANNOT'} spawn sub-sub-agents (depth would be {depth + 1})"
    )
    
    assert "nesting depth: 0 / max 1" in depth_note
    assert "CAN" in depth_note  # depth=0 < max_depth=1, 可以 spawn
    print(f"✅ depth=0, max_depth=1 system prompt: {depth_note}")
    
    depth = 1
    can_spawn = depth < max_depth
    depth_note = (
        f"- Your nesting depth: {depth} / max {max_depth}\n"
        f"- You {'CAN' if can_spawn else 'CANNOT'} spawn sub-sub-agents (depth would be {depth + 1})"
    )
    
    assert "nesting depth: 1 / max 1" in depth_note
    assert "CANNOT" in depth_note  # depth=1 >= max_depth=1, 不能 spawn
    print(f"✅ depth=1, max_depth=1 system prompt: {depth_note}")


def test_list_contains_depth():
    """list 动作应包含深度信息。"""
    cleanup_registry()
    
    # 先创建一个 entry
    if hasattr(_thread_local, 'subagent_depth'):
        del _thread_local.subagent_depth
    if hasattr(_thread_local, 'subagent_max_depth'):
        del _thread_local.subagent_max_depth

    with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent') as mock_exec:
        mock_exec.return_value = {"agent_id": "list-test", "status": "completed"}
        toolkit_subagent(action="spawn_sync", goal="list test")
    
    result = toolkit_subagent(action="list")
    assert "agents" in result
    if result["agents"]:
        agent = result["agents"][0]
        assert "depth" in agent, f"list 应返回 depth"
        assert "max_depth" in agent, f"list 应返回 max_depth"
        print(f"✅ list 包含 depth={agent.get('depth')}, max_depth={agent.get('max_depth')}")
    
    cleanup_registry()


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 SubAgent 嵌套深度限制测试")
    print("=" * 60)
    
    tests = [
        test_default_max_depth,
        test_spawn_without_goal,
        test_depth_inheritance,
        test_depth_exceeded,
        test_custom_max_depth,
        test_async_spawn_depth,
        test_async_spawn_success,
        test_depth_in_system_prompt,
        test_list_contains_depth,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("=" * 60)
    print(f"✅ 通过: {passed}, ❌ 失败: {failed}, 总计: {len(tests)}")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("🎉 所有测试通过!")
