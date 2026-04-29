#!/usr/bin/env python3
# @2026-04-29 gen by deepseek-v4-pro, 重写为适配当前 tea_agent 架构的会话测试
"""Test OnlineToolSession with a mock Toolkit and Storage."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tea_agent.tlk import Toolkit
from tea_agent.onlinesession import OnlineToolSession
from tea_agent.store import Storage


def test_toolkit():
    """Test Toolkit loading."""
    print("=" * 50)
    print("Test Toolkit")
    print("=" * 50)

    toolkit = Toolkit(tempfile.mkdtemp())
    n = len(toolkit.func_map)
    print(f"✅ Tools loaded: {n}")
    assert n > 0, "Should have at least 1 tool"
    for name in sorted(toolkit.func_map.keys()):
        print(f"   - {name}")
    return toolkit


def test_online_session(toolkit, storage):
    """Test OnlineToolSession creation and basic ops."""
    print("\n" + "=" * 50)
    print("Test OnlineToolSession")
    print("=" * 50)

    sess = OnlineToolSession(
        toolkit=toolkit,
        api_key="sk-test",
        api_url="https://api.test.com",
        model="test-model",
        max_history=5,
        max_iterations=3,
        storage=storage,
    )
    print(f"✅ Created: {type(sess).__name__}")
    print(f"   model: {sess.model}")
    print(f"   max_iterations: {sess.max_iterations}")
    print(f"   extra_iterations: {sess._extra_iterations}")
    print(f"   enable_thinking: {sess.enable_thinking}")
    print(f"   tools count: {len(sess.tools)}")
    return sess


def test_reset_and_iter(sess):
    """Test session reset and iteration state."""
    print("\n" + "=" * 50)
    print("Test Reset & Iteration State")
    print("=" * 50)

    sess._extra_iterations = 3
    sess._continue_after_max = True
    sess._max_iter_wait.set()

    sess.reset_session_state()
    assert sess._extra_iterations == 0, f"Expected 0, got {sess._extra_iterations}"
    assert not sess._max_iter_wait.is_set(), "Event should be cleared"
    print(f"✅ reset_session_state clears extra_iterations + event")

    # Test effective_max computation
    effective = sess.max_iterations + sess._extra_iterations
    assert effective == sess.max_iterations, f"Expected {sess.max_iterations}, got {effective}"
    print(f"✅ effective_max = {effective}")


def test_memory_integration(sess, storage):
    """Test memory features are accessible."""
    print("\n" + "=" * 50)
    print("Test Memory Integration")
    print("=" * 50)

    assert hasattr(sess, '_setup_memory'), "Should have _setup_memory"
    assert hasattr(sess, '_pipeline_inject_memories'), "Should have memory injection"
    print("✅ Session has memory mixin methods")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("       Session Module Tests")
    print("=" * 60 + "\n")

    # Setup
    storage = Storage(":memory:")
    toolkit = test_toolkit()
    sess = test_online_session(toolkit, storage)
    test_reset_and_iter(sess)
    test_memory_integration(sess, storage)

    print("\n" + "=" * 60)
    print("       All Session Tests Passed ✅")
    print("=" * 60)
