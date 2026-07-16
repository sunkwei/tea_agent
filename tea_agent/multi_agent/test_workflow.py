"""
WorkflowEngine 综合回归测试 (Phase 5 + Phase 6)
"""
import logging
import sys

logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, '.')
from tea_agent.multi_agent import *  # noqa: E402


def test_empty_dag():
    wf = WorkflowExec(WorkflowDAG()).run()
    assert wf.state == WorkflowState.COMPLETED
    print('  ✅ 空DAG')


def test_single_task():
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode('t1', NodeType.TASK, fn=lambda ctx: {'v': 1}))
    wf = WorkflowExec(dag).run()
    assert wf.state == WorkflowState.COMPLETED
    assert wf.results['t1'].state == NodeState.COMPLETED
    assert wf.results['t1'].output.get('v') == 1
    print('  ✅ 单任务')


def test_sequence():
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode('a', NodeType.TASK, fn=lambda ctx: {'v': ctx.get('v',0)+1}))
    dag.add_node(WorkflowNode('b', NodeType.TASK, fn=lambda ctx: {'v': ctx.get('v',0)*2}))
    dag.add_edge('a', 'b')
    wf = WorkflowExec(dag, context={'v': 5}).run()
    assert wf.state == WorkflowState.COMPLETED
    assert wf.results['b'].output.get('v') in (10, 12)  # depends on execution
    print('  ✅ 顺序链')


def test_condition():
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode('s', NodeType.TASK, fn=lambda ctx: {'x': 3}))
    dag.add_node(WorkflowNode('c', NodeType.CONDITION, fn=lambda ctx: {'condition': ctx.get('x',0) > 5}))
    dag.add_node(WorkflowNode('high', NodeType.TASK, fn=lambda ctx: {'branch': 'high'}))
    dag.add_node(WorkflowNode('low', NodeType.TASK, fn=lambda ctx: {'branch': 'low'}))
    dag.add_edge('s', 'c')
    dag.add_edge('c', 'high', condition_key='true')
    dag.add_edge('c', 'low', condition_key='false')
    wf = WorkflowExec(dag).run()
    assert wf.results['high'].state == NodeState.SKIPPED
    assert wf.results['low'].state == NodeState.COMPLETED
    print('  ✅ 条件分支')


def test_parallel():
    dag = WorkflowDAG()
    children = [WorkflowNode(f'c{i}', NodeType.TASK, fn=lambda ctx, i=i: {'id': i}) for i in range(5)]
    dag.add_node(WorkflowNode('p', NodeType.PARALLEL, fn=None,
        config={'children': children, 'parallel_timeout': 10}))
    wf = WorkflowExec(dag).run()
    out = wf.results['p'].output or {}
    assert out.get('_parallel_count') == 5, f'count={out.get("_parallel_count")}'
    print('  ✅ 并行扇出')


def test_wait():
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode('w', NodeType.WAIT, config={'delay_seconds': 0.1}))
    wf = WorkflowExec(dag).run()
    waited = wf.results['w'].output.get('_waited', 0)
    assert 0.05 <= waited <= 0.3, f'waited={waited}'
    print('  ✅ 等待')


def test_loop():
    iters = {'n': 0}
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode('loop', NodeType.LOOP, fn=lambda ctx: (
        iters.__setitem__('n', iters['n']+1),
        {'continue': iters['n'] <= 2}
    )[1], config={'max_iterations': 5}))
    wf = WorkflowExec(dag).run()
    assert iters['n'] >= 2, f'iters={iters["n"]}'
    print('  ✅ LOOP循环')


def test_error_handling():
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode('fail', NodeType.TASK, fn=lambda ctx: 1/0))
    wf = WorkflowExec(dag).run()
    assert wf.state == WorkflowState.FAILED
    assert 'division' in (wf.results['fail'].error or '')
    print('  ✅ 错误处理')


def test_serialization():
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode('a', NodeType.TASK, fn=lambda ctx: {'v': 1}))
    dag.add_node(WorkflowNode('b', NodeType.TASK, fn=lambda ctx: {'v': 2}))
    dag.add_edge('a', 'b')
    d = dag.to_dict()
    dag2 = WorkflowDAG.from_dict(d)
    assert dag2.workflow_id == dag.workflow_id
    assert len(dag2.nodes) == 2
    print('  ✅ 序列化')


def test_execution_pool():
    pool = get_execution_pool(pool_name='test')
    f = pool.submit(lambda x: x*2, 21, name='verify', timeout=5)
    assert f.result(timeout=3) == 42
    # 验证 timeout 参数不会被传入 fn
    f2 = pool.submit(lambda x, y: x+y, 10, 20, name='add', timeout=5)
    assert f2.result() == 30
    print('  ✅ ExecutionPool')


if __name__ == '__main__':
    tests = [
        test_empty_dag, test_single_task, test_sequence,
        test_condition, test_parallel, test_wait, test_loop,
        test_error_handling, test_serialization, test_execution_pool,
    ]
    total = len(tests)
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f'  ❌ {t.__name__}: {e}')
            import traceback
            traceback.print_exc()
            failed += 1
    print(f'\n{"="*40}')
    print(f'📊 {passed}/{total} 通过' + (f', {failed} 失败' if failed else ''))
    sys.exit(1 if failed else 0)
