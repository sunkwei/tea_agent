"""Quick smoke test: ACP protocol core handlers work correctly."""
import json
import os
import sys
import threading
import time

PROJECT_ROOT = "C:/Users/Hetin/work/git/tea_agent"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import logging
logging.basicConfig(level=logging.WARNING)

from tea_agent.protocol.acp_agent import AcpAgent
from tea_agent.protocol.acp_jsonrpc import JsonRpcTransport, JsonRpcMessage, JsonRpcError


def test_session_list_and_delete():
    """Test session/list, session/delete, session/cancel, session/set_mode (fast handlers)."""
    print("Testing session management handlers...")

    input_sim = _InputSim()
    output_cap = _OutputCap()

    agent = AcpAgent(agent_name="test-agent")
    agent._transport = JsonRpcTransport(reader=input_sim, writer=output_cap)
    agent._register_handlers()
    agent.client._transport = agent._transport

    t = threading.Thread(target=agent.run, daemon=True)
    t.start()
    time.sleep(0.1)

    # Step 1: initialize
    input_sim.add({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}})
    time.sleep(0.15)
    r = _find(output_cap, 1)
    assert r and "result" in r, f"initialize failed: {r}"
    print("  ✓ initialize")

    # Step 2: session/new
    input_sim.add({"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"/test","mode":"develop"}})
    time.sleep(0.15)
    r = _find(output_cap, 2)
    assert r and "result" in r, f"session/new failed: {r}"
    sid = r["result"]["sessionId"]
    print(f"  ✓ session/new: {sid[:12]}...")

    # Step 3: session/list
    input_sim.add({"jsonrpc":"2.0","id":3,"method":"session/list","params":{}})
    time.sleep(0.15)
    r = _find(output_cap, 3)
    assert r and "result" in r, f"session/list failed: {r}"
    assert r["result"]["total"] >= 1
    print(f"  ✓ session/list: {r['result']['total']} session(s)")

    # Step 4: session/set_mode
    input_sim.add({"jsonrpc":"2.0","id":4,"method":"session/set_mode","params":{"sessionId":sid,"mode":"test"}})
    time.sleep(0.15)
    r = _find(output_cap, 4)
    assert r and "result" in r and r["result"].get("mode") == "test"
    print("  ✓ session/set_mode")

    # Step 5: session/set_config_option
    input_sim.add({"jsonrpc":"2.0","id":5,"method":"session/set_config_option","params":{"sessionId":sid,"option":"temperature","value":0.5}})
    time.sleep(0.15)
    r = _find(output_cap, 5)
    assert r and "result" in r
    print("  ✓ session/set_config_option")

    # Step 6: session/cancel (no active turn = cancellation not happening)
    input_sim.add({"jsonrpc":"2.0","id":6,"method":"session/cancel","params":{"sessionId":sid}})
    time.sleep(0.15)
    r = _find(output_cap, 6)
    assert r and "result" in r
    print("  ✓ session/cancel")

    # Step 7: authenticate
    input_sim.add({"jsonrpc":"2.0","id":7,"method":"authenticate","params":{}})
    time.sleep(0.15)
    r = _find(output_cap, 7)
    assert r and "result" in r
    print("  ✓ authenticate")

    # Step 8: logout
    input_sim.add({"jsonrpc":"2.0","id":8,"method":"logout","params":{}})
    time.sleep(0.15)
    r = _find(output_cap, 8)
    assert r and "result" in r
    print("  ✓ logout")

    # Step 9: session/fork (before delete, we need the source session)
    input_sim.add({"jsonrpc":"2.0","id":9,"method":"session/fork","params":{"sessionId":sid}})
    time.sleep(0.15)
    r = _find(output_cap, 9)
    assert r and "result" in r and "forkedFrom" in r["result"]
    fork_id = r["result"]["sessionId"]
    print(f"  ✓ session/fork: {fork_id[:12]}...")

    # Step 10: session/resume (forked session)
    input_sim.add({"jsonrpc":"2.0","id":10,"method":"session/resume","params":{"sessionId":fork_id}})
    time.sleep(0.15)
    r = _find(output_cap, 10)
    assert r and "result" in r and r["result"].get("sessionId") == fork_id
    print("  ✓ session/resume")

    # Step 11: session/close (fork)
    input_sim.add({"jsonrpc":"2.0","id":11,"method":"session/close","params":{"sessionId":fork_id}})
    time.sleep(0.15)
    r = _find(output_cap, 11)
    assert r and "result" in r and r["result"].get("success") is True
    print("  ✓ session/close")

    # Step 12: session/delete (original session)
    input_sim.add({"jsonrpc":"2.0","id":12,"method":"session/delete","params":{"sessionId":sid}})
    time.sleep(0.15)
    r = _find(output_cap, 12)
    assert r and "result" in r
    print("  ✓ session/delete")

    # Step 13: providers/set
    input_sim.add({"jsonrpc":"2.0","id":13,"method":"providers/set","params":{"provider_id":"test","model":"fast"}})
    time.sleep(0.15)
    r = _find(output_cap, 13)
    assert r and "result" in r
    print("  ✓ providers/set")

    # Step 14: providers/disable
    input_sim.add({"jsonrpc":"2.0","id":14,"method":"providers/disable","params":{"provider_id":"test"}})
    time.sleep(0.15)
    r = _find(output_cap, 14)
    assert r and "result" in r
    print("  ✓ providers/disable")

    # Step 15: Unknown method
    input_sim.add({"jsonrpc":"2.0","id":15,"method":"unknown_method","params":{}})
    time.sleep(0.15)
    r = _find(output_cap, 15)
    assert r and "error" in r and r["error"]["code"] == -32601
    print("  ✓ unknown_method → -32601")

    # Cleanup
    input_sim.end()
    time.sleep(0.3)
    agent.stop()

    print("  ✅ All session management tests passed!")
    return True


def test_nes_and_ext():
    """Test NES (inline edit) and ext (extension point) handlers."""
    print("\nTesting NES and ext handlers...")

    input_sim = _InputSim()
    output_cap = _OutputCap()

    agent = AcpAgent(agent_name="test-agent")
    agent._transport = JsonRpcTransport(reader=input_sim, writer=output_cap)
    agent._register_handlers()
    agent.client._transport = agent._transport

    t = threading.Thread(target=agent.run, daemon=True)
    t.start()
    time.sleep(0.1)

    # initialize + session/new first
    input_sim.add({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}})
    time.sleep(0.15)
    r = _find(output_cap, 1)
    assert r and "result" in r

    input_sim.add({"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"/test"}})
    time.sleep(0.15)
    r = _find(output_cap, 2)
    assert r and "result" in r

    # NES: start
    input_sim.add({"jsonrpc":"2.0","id":10,"method":"nes/start","params":{"sessionId":"s1","filePath":"/test/a.py","selection":"def foo"}})
    time.sleep(0.15)
    r = _find(output_cap, 10)
    assert r and "result" in r and "nesId" in r["result"]
    nes_id = r["result"]["nesId"]
    print(f"  ✓ nes/start: {nes_id}")

    # NES: suggest
    input_sim.add({"jsonrpc":"2.0","id":11,"method":"nes/suggest","params":{"nesId":nes_id,"filePath":"/test/a.py","prompt":"Add type hints"}})
    time.sleep(0.15)
    r = _find(output_cap, 11)
    assert r and "result" in r
    print(f"  ✓ nes/suggest: status={r['result'].get('status')}")

    # NES: accept
    sug_id = r["result"].get("suggestions", [{}])[0].get("id", "sug_1")
    input_sim.add({"jsonrpc":"2.0","id":12,"method":"nes/accept","params":{"nesId":nes_id,"suggestionId":sug_id}})
    time.sleep(0.15)
    r = _find(output_cap, 12)
    assert r and "result" in r and r["result"]["status"] == "accepted"
    print("  ✓ nes/accept")

    # NES: close
    input_sim.add({"jsonrpc":"2.0","id":13,"method":"nes/close","params":{"nesId":nes_id}})
    time.sleep(0.15)
    r = _find(output_cap, 13)
    assert r and "result" in r and r["result"]["status"] == "closed"
    print("  ✓ nes/close")

    # ext/request: toolkit/list
    input_sim.add({"jsonrpc":"2.0","id":20,"method":"ext/request","params":{"method":"toolkit/list","params":{}}})
    time.sleep(4.0)  # Agent init takes ~2s (80 toolkit functions to load) + processing
    r = _find(output_cap, 20)
    assert r and "result" in r
    print(f"  ✓ ext/request toolkit/list: {r['result'].get('total', 'N/A')} tools")

    # ext/request: config/get
    input_sim.add({"jsonrpc":"2.0","id":21,"method":"ext/request","params":{"method":"config/get","params":{"key":"model"}}})
    time.sleep(0.15)
    r = _find(output_cap, 21)
    assert r and "result" in r
    print(f"  ✓ ext/request config/get")

    # ext/request: unknown method
    input_sim.add({"jsonrpc":"2.0","id":22,"method":"ext/request","params":{"method":"nonexistent","params":{}}})
    time.sleep(0.15)
    r = _find(output_cap, 22)
    assert r and "result" in r and "error" in r["result"]
    print("  ✓ ext/request unknown → error")

    # Cleanup
    input_sim.end()
    time.sleep(0.3)
    agent.stop()

    print("  ✅ All NES and ext tests passed!")
    return True
def test_transport_notifications():
    """Test notifications (no response expected)."""
    print("\nTesting notifications...")

    input_sim = _InputSim()
    output_cap = _OutputCap()

    transport = JsonRpcTransport(reader=input_sim, writer=output_cap)

    t = threading.Thread(target=transport.start, daemon=True)
    t.start()
    time.sleep(0.1)

    # Send a notification (no id)
    input_sim.add({"jsonrpc":"2.0","method":"document/didOpen","params":{"path":"/test/file.py","content":"print('hello')"}})
    time.sleep(0.15)

    # Also send a request to verify transport is still working
    transport.on_request("test_ping", lambda p, id: {"pong": True})
    input_sim.add({"jsonrpc":"2.0","id":100,"method":"test_ping","params":{}})
    time.sleep(0.15)

    r = _find(output_cap, 100)
    assert r and "result" in r, f"test_ping failed: {r}"
    assert r["result"] == {"pong": True}

    input_sim.end()
    time.sleep(0.3)
    transport.stop()

    # Verify no response was sent for the notification
    notif_responses = [l for l in output_cap.get_lines() if l.strip() and json.loads(l.strip()).get("method") == "document/didOpen"]
    assert len(notif_responses) == 0, "Notification should NOT produce a response"

    print("  ✅ Notification test passed!")
    return True


class _InputSim:
    def __init__(self):
        self._lines = []
        self._idx = 0
        self._lock = threading.Lock()
        self._ended = False

    def add(self, msg: dict):
        with self._lock:
            self._lines.append(json.dumps(msg))

    def end(self):
        with self._lock:
            self._ended = True

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            with self._lock:
                if self._idx < len(self._lines):
                    line = self._lines[self._idx]
                    self._idx += 1
                    return line + "\n"
                elif self._ended:
                    raise StopIteration
            time.sleep(0.02)


class _OutputCap:
    def __init__(self):
        self.lines = []
        self._lock = threading.Lock()

    def write(self, data: str):
        with self._lock:
            self.lines.append(data)

    def flush(self):
        pass

    def get_lines(self):
        with self._lock:
            return list(self.lines)


def _find(cap, msg_id):
    for line in cap.get_lines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if parsed.get("id") == msg_id:
                return parsed
        except json.JSONDecodeError:
            continue
    return None


if __name__ == "__main__":
    passed = 0
    failed = 0

    try:
        test_session_list_and_delete()
        passed += 1
    except Exception as e:
        print(f"  ❌ session test: {e}")
        import traceback
        traceback.print_exc()
        failed += 1

    try:
        test_nes_and_ext()
        passed += 1
    except Exception as e:
        print(f"  ❌ NES/ext test: {e}")
        import traceback
        traceback.print_exc()
        failed += 1

    try:
        test_transport_notifications()
        passed += 1
    except Exception as e:
        print(f"  ❌ notification test: {e}")
        failed += 1

    print(f"\n{'='*40}")
    print(f"  ✅ {passed} passed, ❌ {failed} failed")
    print(f"{'='*40}")
    sys.exit(0 if failed == 0 else 1)
