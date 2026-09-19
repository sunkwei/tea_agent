"""Web 用量条「decode tokens/s」渲染回归测试。

驱动真实前端代码：从 ``server/static/app.js`` 抽取 ``updateUsage``，
用最小 DOM 桩执行，断言渲染结果 —— 钉**行为契约**而非实现细节：

1. 有实测速率 → 渲染 ``⚡N.N tok/s``，且不吞掉既有的 T/P/C 字段
2. 无数据 / 0 / 畸形值 → 只隐藏速率段，整条用量条必须存活
3. 估算口径（端点未上报 usage）→ 加 ``~`` 前缀与 ``est`` 类，与实测视觉可辨
4. tooltip 透出计算来源（tokens/秒数/TTFT/调用次数），数字可被人工核对
5. title 属性经转义，后端字段异常不得变成 XSS 面

注意：本测试用「把 harness 写成文件后 ``node file.js``」的方式执行，
**不走 stdin** —— 某些 Windows node shim（Volta）在 stdin 管道下会静默丢弃
脚本输出，导致测试误判为失败。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "server" / "static" / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="需要 node 执行前端 updateUsage（JS 纯函数，Python 无法直接调用）",
)

# 抽取 updateUsage 并注入 $ / esc 桩；用例经 payload 文件传入（避开 stdin）
_HARNESS = r"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const src = fs.readFileSync(payload.app, 'utf8').replace(/\r\n/g, '\n');
const lines = src.split('\n');

const start = lines.findIndex(l => l.startsWith('function updateUsage(usage) {'));
if (start < 0) throw new Error('app.js 中找不到 updateUsage —— 抽取锚点失效');
let end = -1;
for (let i = start + 1; i < lines.length; i++) {
  if (lines[i] === '}') { end = i; break; }
}
if (end < 0) throw new Error('updateUsage 结尾大括号定位失败');
const fnSrc = lines.slice(start, end + 1).join('\n');
if (!fnSrc.includes('usage-speed')) throw new Error('抽取到的函数体不含 usage-speed');

const esc = (t) => String(t == null ? '' : t)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const bar = { innerHTML: '', className: '', style: { display: 'none' } };
const $ = (id) => (id === 'usage-bar' ? bar : null);
const updateUsage = new Function('$', 'esc', fnSrc + '\nreturn updateUsage;')($, esc);

const out = {};
for (const [name, usage] of Object.entries(payload.cases)) {
  bar.innerHTML = '';
  bar.style.display = 'none';
  let threw = null;
  try { updateUsage(usage); } catch (e) { threw = String(e); }
  out[name] = { html: bar.innerHTML, threw: threw, shown: bar.style.display };
}
process.stdout.write(JSON.stringify(out));
"""

_SPEED = {
    "completion_tokens": 312,
    "decode_seconds": 12.0,
    "tok_per_sec": 26.0,
    "ttft_seconds": 3.0,
    "streams": 1,
    "estimated": False,
}
_BASE = {"total_tokens": 70, "prompt_tokens": 10, "completion_tokens": 60}


def _render(cases: dict) -> dict:
    """在 node 中执行 updateUsage，返回 {name: {html, threw, shown}}。"""
    tmp = Path(__file__).with_suffix(".harness.tmp.js")
    payload = tmp.with_suffix(".payload.tmp.json")
    try:
        tmp.write_text(_HARNESS, encoding="utf-8", newline="\n")
        payload.write_text(
            json.dumps({"app": str(APP_JS), "cases": cases}, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )
        proc = subprocess.run(
            ["node", str(tmp), str(payload)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert proc.returncode == 0, f"node 执行失败:\n{proc.stderr}"
        assert proc.stdout.strip(), "node 无任何输出（执行通路异常，非断言失败）"
        return json.loads(proc.stdout)
    finally:
        tmp.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)


def test_usage_bar_node_rendering_works():
    """前置有效性检查：node 确实返回了结构化结果（防「测试空转」）。"""
    res = _render({"probe": dict(_BASE, speed=_SPEED)})
    assert "probe" in res
    assert res["probe"]["threw"] is None
    assert "usage-speed" in res["probe"]["html"]


class TestTokPerSecRendering:
    def test_measured_rate_is_shown(self):
        html = _render({"c": dict(_BASE, speed=_SPEED)})["c"]["html"]
        assert "usage-speed" in html
        assert "26.0 tok/s" in html
        assert "est" not in html.split('class="usage-speed')[1].split('"')[0]

    def test_bar_is_made_visible(self):
        res = _render({"c": dict(_BASE, speed=_SPEED)})["c"]
        assert res["shown"] == ""  # updateUsage 会把 display 打开
        assert res["threw"] is None

    def test_does_not_displace_existing_fields(self):
        """tok/s 是新增段，不能挤掉 token 统计/模型/命中率/上下文。"""
        usage = dict(_BASE, total_tokens=1234, prompt_tokens=1000, completion_tokens=234,
                     model="deepseek-chat", cache_hit_rate="命中 80%",
                     context_used="上下文已用 40%", context_pct=40, speed=_SPEED)
        html = _render({"c": usage})["c"]["html"]
        for needle in ("T:1234", "P:1000+C:234", "deepseek-chat", "命中 80%",
                       "上下文已用 40%", "26.0 tok/s"):
            assert needle in html, f"缺失: {needle}"

    def test_rendered_after_token_counts(self):
        """顺序：token 统计 → tok/s → 模型（速率紧贴 token 读数最易对照）。"""
        html = _render({"c": dict(_BASE, model="m", speed=_SPEED)})["c"]["html"]
        assert (html.index("usage-tokens") < html.index("usage-speed")
                < html.index("usage-model"))

    def test_tooltip_excludes_ttft_when_unknown(self):
        """非流式无 TTFT 概念 → tooltip 不得写「首token 0s」这种假数据。"""
        spd = dict(_SPEED, ttft_seconds=None)
        html = _render({"c": dict(_BASE, speed=spd)})["c"]["html"]
        assert "首token" not in html

    def test_multi_stream_count_in_tooltip(self):
        html = _render({"c": dict(_BASE, speed=dict(_SPEED, streams=4))})["c"]["html"]
        assert "4 次模型调用合计" in html


class TestEstimatedProvenance:
    def test_estimated_gets_tilde_and_class(self):
        """端点未上报 usage 的估算值必须与实测视觉可辨。"""
        html = _render({"c": dict(_BASE, speed=dict(_SPEED, estimated=True))})["c"]["html"]
        assert 'usage-speed est' in html
        assert "~26.0 tok/s" in html
        assert "按文本估算" in html


class TestHiddenWhenUnavailable:
    # 注：Python 的 float('nan') 无法作为测试入参 —— 它序列化出的 `NaN` 不是合法
    # JSON 字面量，根本到不了前端。真实可达的坏值是 null 与字符串 "NaN"
    # （后者来自后端把不可格式化的数当字符串下发），故覆盖这两种。
    @pytest.mark.parametrize("speed", [None, 0, "abc", {}, {"tok_per_sec": None},
                                       {"tok_per_sec": 0}, {"tok_per_sec": "NaN"},
                                       {"tok_per_sec": ""}, {"tok_per_sec": []}])
    def test_bad_or_missing_speed_hides_only_the_badge(self, speed):
        """坏/缺速率字段只隐藏 tok/s 段 —— 整条用量条（含 P/C）必须存活。

        updateUsage 在 SSE 回调里没有 try/catch，一旦抛异常，用户会连同
        token 统计一起看不到，那是比「没有 tok/s」严重得多的退化。
        """
        usage = dict(_BASE, speed=speed)
        res = _render({"c": usage})["c"]
        assert res["threw"] is None, f"不应抛异常: {res['threw']}"
        assert "usage-speed" not in res["html"]
        assert "T:70" in res["html"]
        assert "P:10+C:60" in res["html"]

    def test_nan_string_specifically(self):
        """`Number('NaN')` 是 NaN：isFinite 必须拦住，否则渲染出 'NaN tok/s'。"""
        html = _render({"c": dict(_BASE, speed={"tok_per_sec": "NaN"})})["c"]["html"]
        assert "NaN" not in html
        assert "T:70" in html

    def test_numeric_string_is_coerced(self):
        """JSON 里速率以字符串到达时仍应渲染（Number() 兜底，不静默丢功能）。"""
        html = _render({"c": dict(_BASE, speed=dict(_SPEED, tok_per_sec="26.0"))})["c"]["html"]
        assert "26.0 tok/s" in html

    def test_usage_without_speed_unchanged_behaviour(self):
        """完全不带 speed 字段 → 与改动前一致（向后兼容旧后端）。"""
        html = _render({"c": dict(_BASE, model="m")})["c"]["html"]
        assert "tok/s" not in html
        assert "T:70" in html

    def test_null_usage_is_noop(self):
        res = _render({"c": None})["c"]
        assert res["html"] == ""
        assert res["threw"] is None


class TestTooltipEscaping:
    def test_backend_field_cannot_break_out_of_title(self):
        """tooltip 内容经转义；后端字段异常不得成为 XSS 注入面。"""
        evil = '"><img src=x onerror=alert(1)>'
        html = _render({"c": dict(_BASE, speed=dict(_SPEED, decode_seconds=evil))})["c"]["html"]
        assert "<img" not in html
        assert "onerror=alert" not in html or "&quot;" in html
        assert "&lt;&quot;&gt;" in html or "&lt;" in html


# ============================================================
# 防误读契约（本次争议的根因不是算错，是读数被当成整体速度）
# ============================================================

# 带完整账本的样本：解码 194.4s、等待合计 396s、平均首 token 22s
_FULL = {"completion_tokens": 15948, "decode_seconds": 194.4, "tok_per_sec": 82.0,
         "ttft_seconds": 22.0, "ttft_max_seconds": 22.0, "wait_seconds": 396.0,
         "request_seconds": 590.4, "streams": 18, "estimated": False}


class TestNoMisreadingContract:
    def test_badge_states_scope_in_the_label_itself(self):
        """标签必须自带「解码」二字。

        口径只写在 tooltip 里等于没有口径 —— 截图里 `⚡ 81.9 tok/s` 就是这样
        被读成"整体就这速度"的。用户不 hover 时也必须无法误读。
        """
        html = _render({"c": dict(_BASE, speed=_FULL)})["c"]["html"]
        seg = html.split('class="usage-speed')[1].split("</span>")[0]
        assert "解码" in seg, "口径必须出现在可见标签内，而非只在 title 里"
        assert "82.0 tok/s" in seg

    def test_ttft_badge_is_shown_and_labelled(self):
        """⏳ 首token 徽标：把 ⚡ 刻意排除的等待显形，且标明是"首token"而非总量。"""
        html = _render({"c": dict(_BASE, speed=_FULL)})["c"]["html"]
        assert "usage-ttft" in html
        assert "首token" in html
        assert "22.0s" in html

    def test_ttft_glyph_does_not_collide_with_live_estimate(self):
        """符号不得复用：⏱ 已表示「实时估算 tok/s」（speed-live），
        TTFT 必须用别的字形。同一条里一个符号两个意思，等于制造下一次误读。
        """
        html = _render({"c": dict(_BASE, speed=_FULL)})["c"]["html"]
        assert "⏱" not in html, "usage-bar 内不得出现 ⏱（保留给实时估算徽标）"
        assert "⏳" in html

    def test_ratio_message_present_when_wait_known(self):
        """等待合计必须换算成「比 ⚡ 慢 N 倍」——绝对秒数会和 ⏳ 被相加，
        比值才是直接纠正"体感=解码时间"这一误读的那句话。
        """
        html = _render({"c": dict(_BASE, speed=_FULL)})["c"]["html"]
        tip = html.split('title="')[1].split('"')[0]
        assert "3.0 倍" in tip
        assert "590.4" in tip

    def test_no_dangling_reference_when_ttft_absent(self):
        """没有 ttft 数据时，不得在文案里引用 ⏳（指向不存在的东西）。"""
        no_ttft = {k: v for k, v in _FULL.items()
                   if k not in ("ttft_seconds", "ttft_max_seconds")}
        html = _render({"c": dict(_BASE, speed=no_ttft)})["c"]["html"]
        assert "⏳" not in html
        tip = html.split('title="')[1].split('"')[0]
        assert "⏳" not in tip

    def test_wait_absent_for_legacy_backend(self):
        """旧后端不带 wait/request 字段 → 不得渲染出 NaN 倍之类的鬼话。"""
        legacy = {"completion_tokens": 300, "decode_seconds": 12.0, "tok_per_sec": 25.0,
                  "ttft_seconds": None, "ttft_max_seconds": None,
                  "wait_seconds": None, "request_seconds": None,
                  "streams": 1, "estimated": False}
        html = _render({"c": dict(_BASE, speed=legacy)})["c"]["html"]
        assert "NaN" not in html
        assert "倍" not in html
        assert "25.0 tok/s" in html

    def test_estimated_keeps_scope_label(self):
        """估算口径下同样要写"解码"，且 ~ 不得被空格挤掉。"""
        est = dict(_FULL, estimated=True, tok_per_sec="82.0")
        html = _render({"c": dict(_BASE, speed=est)})["c"]["html"]
        seg = html.split('class="usage-speed')[1].split("</span>")[0]
        assert "~" in seg and "解码" in seg and "82.0 tok/s" in seg
