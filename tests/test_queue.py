"""
排队机制逻辑验证脚本
模拟 TkGUI 的队列行为，验证核心逻辑
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 模拟队列行为（不依赖 Tkinter）──
class MockGUI:
    """模拟 TkGUI 的排队相关逻辑"""
    def __init__(self):
        self._generating = False
        self._generating_lock = type('Lock', (), {
            '__enter__': lambda s: s,
            '__exit__': lambda s, *a: None
        })()
        self._message_queue = []
        self._last_sent = None
        self._interrupt_called = False

    # 模拟 property
    @property
    def generating(self):
        return self._generating
    
    @generating.setter
    def generating(self, value):
        self._generating = value

    def send(self, msg, images=None):
        """模拟 send 逻辑"""
        if images is None:
            images = []
        
        with self._generating_lock:
            if not msg and not images:
                return "break"
            if self._generating:
                if msg or images:
                    self._message_queue.append({"text": msg, "images": images})
                    return "break"
                return "break"
            self._generating = True
        
        self._last_sent = (msg, images)
        return "started"

    def _process_queue(self):
        """模拟 _process_queue"""
        if not self._message_queue:
            return

        with self._generating_lock:
            if self._generating:
                return
            self._generating = True

        item = self._message_queue.pop(0)
        msg = item.get("text", "")
        images = item.get("images", [])

        if not msg and not images:
            self.generating = False
            self._process_queue()
            return

        self._last_sent = (msg, images)

    def _on_generation_done(self):
        """模拟 _on_generation_done"""
        self.generating = False
        self._process_queue()

    def interrupt(self):
        """模拟 interrupt"""
        with self._generating_lock:
            if not self._generating:
                return
            self._generating = False

        qlen = len(self._message_queue)
        self._message_queue.clear()
        self._interrupt_called = True
        return qlen


# ── 测试场景 ──
passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}  {detail}")
        failed += 1

print("=" * 50)
print("排队机制逻辑验证")
print("=" * 50)

# 场景1: 生成中发消息 → 应排队
print("\n--- 场景1: 生成中发消息 → 排队 ---")
g = MockGUI()
g.generating = True
r1 = g.send("消息1")
test("生成中 send 返回 break", r1 == "break")
test("消息入队", len(g._message_queue) == 1)
test("队列内容正确", g._message_queue[0]["text"] == "消息1")

r2 = g.send("消息2")
test("第二条也入队", len(g._message_queue) == 2)
test("last_sent 为 None（未实际发送）", g._last_sent is None)

# 场景2: 生成完毕 → 队列自动处理
print("\n--- 场景2: 生成完成 → 自动发排队消息 ---")
g._on_generation_done()
# _process_queue 立即开始处理下一条，generating=True
test("generating 为 True（正在处理排队消息）", g.generating)
test("队列中第一条已发出", g._last_sent == ("消息1", []))
test("队列长度减1", len(g._message_queue) == 1)

# 模拟第一条排队消息处理完毕 → 触发下一条
g._on_generation_done()
test("第二条也发出", g._last_sent == ("消息2", []))
test("队列已清空", len(g._message_queue) == 0)
# 第二条正在处理中
test("generating 为 True（正在处理第二条）", g.generating)

# 模拟第二条处理完毕 → 队列空了，才恢复 False
g._on_generation_done()
test("队列空了，generating 恢复 False", not g.generating)

# 场景3: 打断时清空队列
print("\n--- 场景3: 打断 → 清空队列 ---")
g = MockGUI()
g.generating = True
g.send("排队消息A")
g.send("排队消息B")
test("队列有2条", len(g._message_queue) == 2)
qlen = g.interrupt()
test("打断清空队列", qlen == 2)
test("队列已空", len(g._message_queue) == 0)
test("interrupt 被调用", g._interrupt_called)

# 场景4: 正常发送（未生成中）
print("\n--- 场景4: 正常发送（未生成中）---")
g = MockGUI()
r = g.send("直接发送")
test("直接发送成功", r == "started")
test("generating 已设置", g.generating)
test("last_sent 正确", g._last_sent == ("直接发送", []))
test("队列为空", len(g._message_queue) == 0)

# 场景5: 空消息+空图片
print("\n--- 场景5: 空消息处理 ---")
g = MockGUI()
r = g.send("")
test("空消息返回 break", r == "break")
test("generating 未设置", not g.generating)

# 场景6: 多级排队
print("\n--- 场景6: 三级排队 ---")
g = MockGUI()
g.generating = True
g.send("A")
g.send("B")
g.send("C")
test("3条排队", len(g._message_queue) == 3)
g._on_generation_done()
test("发出A", g._last_sent == ("A", []))
g._on_generation_done()
test("发出B", g._last_sent == ("B", []))
g._on_generation_done()
test("发出C", g._last_sent == ("C", []))
test("队列空", len(g._message_queue) == 0)

# 场景7: 排队消息含图片
print("\n--- 场景7: 带图片的排队 ---")
g = MockGUI()
g.generating = True
g.send("看这个", ["img1.jpg"])
test("图片消息入队", len(g._message_queue) == 1)
test("图片内容正确", g._message_queue[0]["images"] == ["img1.jpg"])

print(f"\n{'=' * 50}")
print(f"结果: ✅ {passed} 通过 | ❌ {failed} 失败 | 共 {passed+failed} 项")
print(f"{'=' * 50}")

sys.exit(0 if failed == 0 else 1)
