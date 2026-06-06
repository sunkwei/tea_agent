"""
2026-05-18 gen by tea_agent, 验证渲染延迟修复：_render_and_show_chat 必须在 _post_chat_pipeline 之前调度

修复背景：send() 的 work() 线程中，_render_and_show_chat 原本在 _post_chat_pipeline 之后
才通过 after(0) 调度，导致 _auto_summary 的 API 调用阻塞 HTML 渲染 15s+。
修复后将 _render_and_show_chat 提前到 _post_chat_pipeline 之前调度。
"""

import os
import re
import unittest


class TestRenderTiming(unittest.TestCase):
    """验证 gui.py 中 send() 的 work() 函数调度顺序"""

    @classmethod
    def setUpClass(cls):
        """测试前置初始化。"""
        gui_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "gui.py"
        )
        with open(gui_path, "r", encoding="utf-8") as f:
            cls.source = f.read()

    def _extract_try_block(self):
        """提取 def work(): try: 块内容（到 work() 层级的 except/finally 前）"""
        work_match = re.search(r'def work\(\):', self.source)
        self.assertIsNotNone(work_match, "未找到 def work()")
        after_work = self.source[work_match.start():]

        try_match = re.search(r'\n            try:', after_work)
        self.assertIsNotNone(try_match, "未找到 try:")
        after_try = after_work[try_match.end():]

        lines = after_try.split('\n')
        result_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith(('except', 'finally')):
                indent = len(line) - len(stripped)
                if indent == 12:
                    break
            result_lines.append(line)
        return '\n'.join(result_lines)

    def _extract_work_body(self):
        """提取完整 def work(): 函数体"""
        work_match = re.search(r'def work\(\):', self.source)
        self.assertIsNotNone(work_match)
        after = self.source[work_match.start():]
        end = re.search(r'\n        (?:def |class |@)', after)
        if end:
            return after[:end.start()]
        return after

    def _non_comment_lines(self, text):
        """返回非注释行列表 (行号, 内容)"""
        lines = text.split('\n')
        result = []
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped.startswith('#'):
                result.append((i, line))
        return result

    def _first_line_with(self, text, keyword):
        """在非注释行中首次出现 keyword 的行号，-1 表示未找到"""
        for i, line in self._non_comment_lines(text):
            if keyword in line:
                return i
        return -1

    def test_render_before_pipeline(self):
        """测试: Render before pipeline"""
        body = self._extract_try_block()
        rp = self._first_line_with(body, "_render_and_show_chat")
        pp = self._first_line_with(body, "_post_chat_pipeline")
        self.assertGreater(rp, -1, "try 块中未找到 _render_and_show_chat 调用")
        self.assertGreater(pp, -1, "try 块中未找到 _post_chat_pipeline 调用")
        self.assertLess(rp, pp,
                        f"_render_and_show_chat (行 {rp}) 必须在 "
                        f"_post_chat_pipeline (行 {pp}) 之前")

    def test_show_raw_check_btn_before_pipeline(self):
        """测试: Show raw check btn before pipeline"""
        body = self._extract_try_block()
        bp = self._first_line_with(body, "_show_raw_check_btn")
        pp = self._first_line_with(body, "_post_chat_pipeline")
        self.assertGreater(bp, -1, "try 块中未找到 _show_raw_check_btn 调用")
        self.assertLess(bp, pp,
                        f"_show_raw_check_btn (行 {bp}) 必须在 "
                        f"_post_chat_pipeline (行 {pp}) 之前")

    def test_flush_before_render(self):
        """测试: Flush before render"""
        body = self._extract_try_block()
        fp = self._first_line_with(body, "_flush_stream_to_messages")
        rp = self._first_line_with(body, "_render_and_show_chat")
        self.assertGreater(fp, -1, "try 块中未找到 _flush_stream_to_messages 调用")
        self.assertLess(fp, rp,
                        f"_flush_stream_to_messages (行 {fp}) 必须在 "
                        f"_render_and_show_chat (行 {rp}) 之前")

    def test_else_branch_no_render(self):
        """测试: Else branch no render"""
        body = self._extract_try_block()
        else_match = re.search(r'\n                else:', body)
        self.assertIsNotNone(else_match, "未找到 else 分支")

        # 提取 else 到下一个同级代码块
        after_else = body[else_match.start():]
        lines = after_else.split('\n')
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue
            # 遇到下一个同级块时停止
            if stripped and len(line) - len(stripped) <= 12:
                if stripped.startswith(('except', 'finally', 'if ', 'try:')):
                    break
            self.assertNotIn(
                "self._render_and_show_chat", line.split('#')[0],
                f"else 分支中不应包含 _render_and_show_chat 调用: {line}"
            )
            self.assertNotIn(
                "self._show_raw_check_btn", line.split('#')[0],
                f"else 分支中不应包含 _show_raw_check_btn 调用: {line}"
            )

    def test_render_comment_exists(self):
        """测试: Render comment exists"""
        body = self._extract_try_block()
        self.assertIn("修复渲染延迟15s+", body,
                      "try 块中缺少渲染延迟修复注释")

    def test_except_branch_still_has_render(self):
        """测试: Except branch still has render"""
        body = self._extract_work_body()
        except_match = re.search(r'\n            except Exception as ex:', body)
        self.assertIsNotNone(except_match, "未找到外层的 except 分支")
        after_except = body[except_match.start():]
        # 只检查非注释行
        found = False
        for i, line in self._non_comment_lines(after_except):
            if "_render_and_show_chat" in line:
                found = True
                break
        self.assertTrue(found,
                        "except 分支应保留 _render_and_show_chat（异常时仍需渲染）")


if __name__ == "__main__":
    unittest.main()
