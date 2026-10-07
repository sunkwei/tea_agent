"""toolkit_blender 回归测试。

分两层：
1. 纯函数/入口校验层 —— 不需要安装 Blender，任何环境都跑（CI 友好）
2. 真实 Blender 层 —— 本机检测到 Blender 才跑（skipif），验证内嵌脚本端到端可用

回归钉住的行为契约（历史上真实踩过的坑）：
- 内嵌 bpy 脚本必须是合法 Python（曾把带 SyntaxError 的脚本喂给 Blender 反复冷启动）
- 命令组装顺序：extra(-o/-F/-f) 在 -P 之前、script_args 在 '--' 之后
- marker 解析取最后一条、坏 JSON 行跳过不炸
- Windows 多版本目录自然排序（Blender 10.0 > Blender 5.2，字符串排序会错）
- 输入预检错误不得启动子进程（省 1~2s 冷启动、错误信息更明确）
"""

import os.path as osp

import pytest

from tea_agent.toolkit import toolkit_blender as tb
from tea_agent.toolkit.toolkit_blender import toolkit_blender

# ══════════════════════ 1. 纯函数层（无需 Blender） ══════════════════════


class TestExtractResult:
    def test_parses_marker_json(self):
        out = 'noise line\nTEA_BLENDER_RESULT {"a": 1, "b": [2, 3]}\ntail'
        assert tb._extract_result(out) == {"a": 1, "b": [2, 3]}

    def test_no_marker_returns_none(self):
        assert tb._extract_result("Blender quit\n") is None
        assert tb._extract_result("") is None

    def test_takes_last_of_multiple(self):
        out = 'TEA_BLENDER_RESULT {"v": 1}\nTEA_BLENDER_RESULT {"v": 2}'
        assert tb._extract_result(out)["v"] == 2

    def test_bad_json_line_skipped_not_crash(self):
        out = 'TEA_BLENDER_RESULT {broken\nTEA_BLENDER_RESULT {"ok": true}'
        assert tb._extract_result(out) == {"ok": True}

    def test_non_dict_payload_ignored(self):
        assert tb._extract_result("TEA_BLENDER_RESULT [1,2]") is None


class TestVersionKey:
    def test_natural_sort_beats_string_sort(self):
        # 字符串排序会把 "Blender 10.0" 排在 "Blender 5.2" 前（'1'<'5'），必须按数字
        assert tb._version_key(r"C:\Program Files\Blender Foundation\Blender 10.0\blender.exe") > tb._version_key(
            r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
        )

    def test_no_digits_fallback(self):
        assert tb._version_key("/opt/blender") == (0,)


class TestBuildCmd:
    def test_full_order(self):
        cmd = tb._build_cmd(
            "/b/blender",
            factory=True,
            script="/s/x.py",
            blend="/m/f.blend",
            extra=["-o", "out_", "-f", "1"],
            script_args=["a", 2],
        )
        assert cmd[0] == "/b/blender"
        assert cmd[1] == "-b"
        assert "--factory-startup" in cmd
        # blend 在 extra 之前、extra 在 -P 之前、'--' 收尾透传
        assert cmd.index("/m/f.blend") < cmd.index("-o")
        assert cmd.index("-f") < cmd.index("-P")
        assert cmd[-3:] == ["--", "a", "2"]

    def test_minimal(self):
        assert tb._build_cmd("/b/blender", factory=False) == ["/b/blender", "-b"]

    def test_factory_flag_toggle(self):
        assert "--factory-startup" not in tb._build_cmd("/b", factory=False, script="s.py")


class TestFindBlender:
    def test_explicit_path_wins(self, tmp_path):
        fake = tmp_path / "blender.exe"
        fake.write_text("x")
        assert tb._find_blender(str(fake)) == str(fake)

    def test_env_override(self, tmp_path, monkeypatch):
        fake = tmp_path / "myblender"
        fake.write_text("x")
        monkeypatch.setenv("BLENDER_PATH", str(fake))
        assert tb._find_blender() == str(fake)

    def test_env_points_to_missing_falls_through(self, monkeypatch):
        monkeypatch.setenv("BLENDER_PATH", "/definitely/not/here/blender")
        monkeypatch.setenv("BLENDER", "")
        monkeypatch.setattr(tb.shutil, "which", lambda _: None)
        monkeypatch.setattr(tb, "_candidate_paths", lambda: [])
        assert tb._find_blender() is None

    def test_candidates_sorted_by_version_desc(self, monkeypatch):
        # win32 分支：两个版本目录，应取 5.2 而非 4.2（哪怕 listdir 顺序相反）
        import glob as _glob

        real_glob = _glob.glob

        def fake_glob(pattern):
            if "Blender Foundation" in pattern:
                base = pattern.split("Blender*")[0]
                return [base + r"Blender 4.2\blender.exe", base + r"Blender 5.2\blender.exe"]
            return real_glob(pattern)

        monkeypatch.setattr(tb, "glob", type("G", (), {"glob": staticmethod(fake_glob)})())
        monkeypatch.setattr(tb.sys, "platform", "win32")
        monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
        cands = tb._candidate_paths()
        assert cands and "5.2" in cands[0]


class TestTail:
    def test_short_untouched(self):
        assert tb._tail("abc", 10) == "abc"

    def test_long_keeps_tail(self):
        s = "x" * 100 + "ERR_AT_END"
        out = tb._tail(s, 20)
        assert out.endswith("ERR_AT_END")
        assert "truncated" in out


class TestEmbeddedScriptsCompile:
    """内嵌 bpy 脚本必须是合法 Python（曾发生 SyntaxError 反复冷启动 Blender）。"""

    @pytest.mark.parametrize("name", ["PROBE_PY", "SCENE_PY", "EXPORT_PY"])
    def test_compiles(self, name):
        src = getattr(tb, name)
        compile(src, f"<{name}>", "exec")

    @pytest.mark.parametrize("name", ["PROBE_PY", "SCENE_PY", "EXPORT_PY"])
    def test_marker_embedded(self, name):
        assert tb.RESULT_MARKER in getattr(tb, name)

    def test_export_py_percent_escapes_resolved(self):
        # EXPORT_PY 经 % 格式化嵌入 marker，内部 %%r/%%s 必须已还原为 %r/%s
        assert "%%" not in tb.EXPORT_PY
        assert "%r" in tb.EXPORT_PY


# ══════════════════════ 2. 入口校验层（不启动子进程） ══════════════════════


class TestEntrypointValidation:
    def test_unknown_action(self):
        r = toolkit_blender(action="explode")
        assert not r["ok"] and "unknown action" in r["error"]

    def test_run_requires_code_or_script(self, monkeypatch):
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": "/fake/blender")
        r = toolkit_blender(action="run")
        assert not r["ok"] and "code" in r["error"]

    def test_run_missing_script_file_no_spawn(self, monkeypatch):
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": "/fake/blender")

        def boom(*a, **k):
            raise AssertionError("must not spawn for missing script")

        monkeypatch.setattr(tb, "_spawn", boom)
        r = toolkit_blender(action="run", script_path="/no/such/script.py")
        assert not r["ok"] and "not found" in r["error"]

    @pytest.mark.parametrize("action", ["render", "scene", "export"])
    def test_blend_required_actions_validate_before_spawn(self, action, monkeypatch):
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": "/fake/blender")

        def boom(*a, **k):
            raise AssertionError("must not spawn when blend missing")

        monkeypatch.setattr(tb, "_spawn", boom)
        r1 = toolkit_blender(action=action)
        assert not r1["ok"] and "blend_file" in r1["error"]
        r2 = toolkit_blender(action=action, blend_file="/no/such.blend")
        assert not r2["ok"] and "not found" in r2["error"]

    def test_export_rejects_unknown_fmt_before_spawn(self, tmp_path, monkeypatch):
        blend = tmp_path / "f.blend"
        blend.write_bytes(b"x")
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": "/fake/blender")

        def boom(*a, **k):
            raise AssertionError("must not spawn for bad fmt")

        monkeypatch.setattr(tb, "_spawn", boom)
        r = toolkit_blender(action="export", blend_file=str(blend), fmt="dwg")
        assert not r["ok"] and "unsupported format" in r["error"]

    def test_render_rejects_unknown_fmt(self, tmp_path, monkeypatch):
        blend = tmp_path / "f.blend"
        blend.write_bytes(b"x")
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": "/fake/blender")
        r = toolkit_blender(action="render", blend_file=str(blend), fmt="TIFF")
        assert not r["ok"] and "unsupported render format" in r["error"]

    def test_blender_not_found_hint(self, monkeypatch):
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": None)
        r = toolkit_blender(action="probe")
        assert not r["ok"] and r["error"] == "Blender not found"
        assert "BLENDER_PATH" in r["hint"]
        assert "searched" in r


class TestFinishPipeline:
    """marker 抽取/截断/元信息收口链路（fake spawn，无需 Blender）。"""

    def test_run_extracts_result_and_meta(self, monkeypatch):
        captured = {}

        def fake_spawn(cmd, timeout):
            captured["cmd"] = cmd
            return {
                "ok": True,
                "returncode": 0,
                "timed_out": False,
                "secs": 0.2,
                "stdout": 'Read prefs\nTEA_BLENDER_RESULT {"objs": 3}\n',
                "stderr": "TBBmalloc: harmless noise\n",
            }

        monkeypatch.setattr(tb, "_spawn", fake_spawn)
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": "/fake/blender")
        r = toolkit_blender(action="run", code="print(1)", script_args=["--x"])
        assert r["ok"] and r["action"] == "run" and r["blender"] == "/fake/blender"
        assert r["result"] == {"objs": 3}
        assert "-P" in captured["cmd"] and captured["cmd"][-2:] == ["--", "--x"]

    def test_timeout_result_shape(self, monkeypatch):
        monkeypatch.setattr(tb, "_find_blender", lambda explicit="": "/fake/blender")
        monkeypatch.setattr(
            tb,
            "_spawn",
            lambda cmd, timeout: {
                "ok": False,
                "timed_out": True,
                "secs": timeout,
                "stdout": "",
                "stderr": "",
                "error": "timeout",
            },
        )
        r = toolkit_blender(action="probe", timeout=7)
        assert not r["ok"] and r["timed_out"] and r["result"] is None


# ══════════════════════ 3. 真实 Blender 层（本机有则跑） ══════════════════════

_BLENDER = tb._find_blender()
needs_blender = pytest.mark.skipif(_BLENDER is None, reason="Blender not installed on this machine")


@needs_blender
class TestRealBlender:
    def test_probe(self):
        r = toolkit_blender(action="probe", timeout=180)
        assert r["ok"], r.get("stderr", "")[-500:]
        res = r["result"]
        assert res and "version" in res and "engines" in res
        assert isinstance(res["export_formats"], list)

    def test_run_inline_code_roundtrip(self):
        code = (
            "import bpy, json\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))\n"
            "print('TEA_BLENDER_RESULT ' + json.dumps({'objects': [o.name for o in bpy.data.objects]}))\n"
        )
        r = toolkit_blender(action="run", code=code, timeout=180)
        assert r["ok"], r.get("stderr", "")[-500:]
        assert r["result"] and "Cube" in r["result"]["objects"]

    def test_scene_then_export_glb(self, tmp_path):
        blend = str(tmp_path / "cube.blend")
        glb = str(tmp_path / "cube.glb")
        code = (
            "import bpy\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0))\n"
            f"bpy.ops.wm.save_as_mainfile(filepath={blend!r})\n"
        )
        r = toolkit_blender(action="run", code=code, timeout=240)
        assert r["ok"] and osp.isfile(blend), r.get("stderr", "")[-500:]

        rs = toolkit_blender(action="scene", blend_file=blend, timeout=180)
        assert rs["ok"], rs.get("stderr", "")[-500:]
        assert rs["result"]["object_count"] >= 1
        assert rs["result"]["total_verts"] > 0

        re_ = toolkit_blender(action="export", blend_file=blend, output_path=glb, fmt="glb", timeout=240)
        assert re_["ok"], re_.get("stderr", "")[-500:]
        assert osp.isfile(glb) and osp.getsize(glb) > 1000
        assert re_["artifact"] == glb and re_["artifact_size"] > 1000

    def test_render_default_cube(self, tmp_path):
        """用 Blender 出厂默认场景渲染一帧（EEVEE/Cycles 取决于安装，低采样快渲）。"""
        outdir = str(tmp_path / "render")
        # 造一个含相机与灯的默认场景 blend
        blend = str(tmp_path / "scene.blend")
        code = (
            "import bpy\n"
            "bpy.ops.wm.read_factory_settings(use_empty=False)\n"
            "sc = bpy.context.scene\n"
            "sc.render.resolution_x = 160\n"
            "sc.render.resolution_y = 120\n"
            "sc.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in "
            "[e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] "
            "else sc.render.engine\n"
            f"bpy.ops.wm.save_as_mainfile(filepath={blend!r})\n"
        )
        r = toolkit_blender(action="run", code=code, timeout=240)
        assert r["ok"], r.get("stderr", "")[-500:]
        rr = toolkit_blender(action="render", blend_file=blend, output_dir=outdir, frame=1, timeout=300)
        assert rr["ok"], rr.get("stderr", "")[-500:]
        pngs = [a for a in rr["artifacts"] if a["path"].lower().endswith(".png")]
        assert pngs and all(a["size"] > 1000 for a in pngs)
