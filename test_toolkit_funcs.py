from unittest import TestCase
import unittest
from typing import cast, Callable


class Test_toolkit_base(TestCase):
    def setUp(self) -> None:
        import os.path as osp
        curr_path = osp.dirname(osp.abspath(__file__))
        self.toolkit_path = osp.join(curr_path, "toolkit")
        test_name = "toolkit_exec"
        test_fname = osp.join(self.toolkit_path, f"{test_name}.py")
        if osp.exists(test_fname):
            import os
            os.unlink(test_fname)
        return super().setUp()

    def test_toolkit_reload(self):
        from toolkit.toolkit_reload import toolkit_reload
        result = toolkit_reload(self.toolkit_path)
        self.assertIn("valid_tool", result)
        self.assertIn("invalid_tool", result)
        self.assertIn("toolkit_get_public_ip", result["valid_tool"])

    def test_toolkit_save(self):
        from toolkit.toolkit_save import toolkit_save
        name = "toolkit_exec"
        meta = {
            "type": "function",
            "function": {
                "name": name,
                "description": "执行本地命令，如 ls, ping -c1 172.16.1.5, 返回:(进程返回值，stdout输出, stderr输出)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {
                            "type": "string",
                            "description": "应用名，如 ls, ping ",
                        },
                        "args": {
                            "type": "array",
                            "items": {
                                "type": "string",
                            },
                            "description": "应用命令行参数"
                        },
                        "required": [
                            "app"
                        ]
                    }
                }
            }
        }
        pycode = """
from typing import Tuple
def toolkit_exec(app: str, args: list=[]) -> Tuple[int, str, str]:
    import subprocess
    import sys
    args = args or []
    try:
        proc = subprocess.Popen(
            [app] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=sys.getdefaultencoding(),
            errors="replace"
        )
        out, err = proc.communicate(timeout=10)
        return (proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        return (-1, "", "timeout")
    except Exception as e:
        return (-255, "", str(e))
"""
        rc, reason = toolkit_save(name, meta, pycode)
        self.assertEqual(rc, 0)

        # 使用工具函数执行 date 命令测试
        try:
            local_vars = {}
            exec(pycode, globals(), local_vars)
            self.assertIn("toolkit_exec", local_vars)
            func = local_vars.get("toolkit_exec")
            func = cast(Callable, func)
            rc, out, err = func("date")
            print(f"rc:{rc}, out:'{out}', err:'{err}'")
        except Exception as e:
            print(f"test_toolkit_save exec err, e:{e}")

    def tearDown(self) -> None:
        return super().tearDown()


if __name__ == "__main__":
    unittest.main()
