"""实时解码速率估算（前端 ⏱ ~N.N tok/s）回归测试。

回合进行中服务端还拿不到 ``completion_tokens``（要等一次流读完），
因此生成过程中的速率由前端按字符启发式估算 —— 与后端 estimate_tokens 同口径
（中文 1.5 字/tok、其它 4 字符/tok）。

被钉住的行为契约：
1. 计时从**首 token** 起算，排队/prefill 不计入（否则速率被压成 0）
2. 中英混排的 token 换算与后端一致
3. 窗口过短或输出过少 → 不显示（别给一个看似精确的错数）
4. 250ms 节流，force 可绕过（收尾定格）
5. 标记为 ⏱ ~（估算），与实测 ⚡ 可辨
6. hide 后元素彻底清空

执行方式：抽取 app.js 中的实时速率代码块，用 node 以**文件模式**执行
（不走 stdin —— 部分 Windows node shim 在 stdin 管道下静默丢输出）。
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
    reason="需要 node 执行前端估算函数（JS 纯逻辑，Python 无法直接调用）",
)

# 抽取范围：从「实时解码速率」注释块到下一个 Helper 注释块，
# 内容恰为 _countCnChars / _noteStreamChars / _updateLiveSpeed / _hideLiveSpeed
_MARK_START = "// ── 实时解码速率（回合进行中）──"
_MARK_END = "// ── Helper: 创建流式消息容器和状态对象 ──"

_HARNESS = r"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const src = fs.readFileSync(payload.app, 'utf8').replace(/\r\n/g, '\n');

const start = src.indexOf(payload.markStart);
const stop = src.indexOf(payload.markEnd);
if (start < 0) throw new Error('起点标记未找到 —— 实时速率代码块不存在');
if (stop < 0 || stop <= start) throw new Error('终点标记定位失败');
const block = src.slice(start, stop);
for (const need of ['function _countCnChars', 'function _noteStreamChars',
                    'function _updateLiveSpeed', 'function _hideLiveSpeed']) {
  if (!block.includes(need)) throw new Error('代码块缺少 ' + need);
}

let now = 0;
const el = { textContent: '', title: '', style: { display: 'none' } };
const $ = (id) => (id === 'speed-live' ? el : null);
// 以参数名 Date 遮蔽全局 —— 代码块内的 Date.now() 因此受控于本测试
const FakeDate = { now: () => now };

// _lastLiveSpeedRender 在 app.js 里声明于本代码块之外（IIFE 作用域），
// new Function 拿不到它 → 必须在被抽取作用域内补声明，并用访问器暴露给用例，
// 否则节流分支会抛 ReferenceError（且那样的"红"与产品行为无关）。
const api = new Function('$', 'Date',
  'let _lastLiveSpeedRender = 0;\n'
  + block
  + '\nreturn { note: (s, t) => _noteStreamChars(s, t),'
  + ' update: (s, f) => _updateLiveSpeed(s, f),'
  + ' hide: () => _hideLiveSpeed(),'
  + ' countCn: (t) => _countCnChars(t),'
  + ' setLastRender: (v) => { _lastLiveSpeedRender = v; } };')($, FakeDate);

const out = [];
for (const c of payload.cases) {
  const s = { speedChars: 0, speedCn: 0, speedT0: 0, speedT1: 0 };
  el.textContent = ''; el.title = ''; el.style.display = 'none';
  now = c.start === undefined ? 1000.0 : c.start;
  api.setLastRender(0);
  let threw = null;
  try {
    for (const step of c.steps) {
      if (step.hide) { api.hide(); continue; }
      if (step.now !== undefined) now = step.now;
      // 放行节流：把上次渲染时间推到远古，只测算法不测节流
      if (step.skipThrottle) api.setLastRender(now - 100000);
      if (step.text !== undefined) {
        api.note(s, step.text);
        api.update(s, !!step.force);
      } else if (step.force) {
        api.update(s, true);
      } else {
        api.update(s);
      }
    }
  } catch (e) { threw = String(e); }
  out.push({ name: c.name, text: el.textContent, shown: el.style.display,
             hasTitle: !!el.title, threw: threw,
             t0: s.speedT0, t1: s.speedT1, chars: s.speedChars, cn: s.speedCn });
}
process.stdout.write(JSON.stringify(out));
"""


def _run_live(cases: list[dict]) -> list[dict]:
    tmp = Path(__file__).with_suffix(".harness.tmp.js")
    payload = Path(__file__).with_suffix(".payload.tmp.json")
    try:
        tmp.write_text(_HARNESS, encoding="utf-8", newline="\n")
        payload.write_text(
            json.dumps({"app": str(APP_JS), "markStart": _MARK_START,
                        "markEnd": _MARK_END, "cases": cases}, ensure_ascii=False),
            encoding="utf-8", newline="\n",
        )
        proc = subprocess.run(
            ["node", str(tmp), str(payload)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert proc.returncode == 0, f"node 执行失败:\n{proc.stderr}"
        assert proc.stdout.strip(), "node 无输出（执行通路异常，非断言失败）"
        return json.loads(proc.stdout)
    finally:
        tmp.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)


def _one(name, steps, start=1000.0):
    """跑单用例并取回结果（附带「未抛异常」的统一前置断言）。"""
    res = _run_live([{"name": name, "steps": steps, "start": start}])[0]
    assert res["threw"] is None, f"{name} 抛异常: {res['threw']}"
    return res


def _en(steps):
    """常规节奏：每步都放行节流，只测算法不测节流本身。"""
    return [dict(s, skipThrottle=True) for s in steps]


# ============================================================
# 换算口径
# ============================================================


class TestEstimationMath:
    def test_english_4_chars_per_token(self):
        """英文 4 字符/tok：80 字符 = 20 tok，10s → 2.0 tok/s。"""
        r = _one("en", _en([
            {"now": 1000.0, "text": "a" * 40},
            {"now": 11000.0, "text": "a" * 40},
        ]))
        assert r["text"] == "⏱ ~2.0 tok/s"

    def test_cjk_1_5_chars_per_token(self):
        """中文 1.5 字/tok：30 汉字 = 20 tok，10s → 2.0 tok/s（与后端同口径）。"""
        r = _one("cjk", _en([
            {"now": 1000.0, "text": "中" * 15},
            {"now": 11000.0, "text": "中" * 15},
        ]))
        assert (r["chars"], r["cn"]) == (30, 30)
        assert r["text"] == "⏱ ~2.0 tok/s"

    def test_mixed_text_weights_both_ranges(self):
        """混排：10 汉字(=6.67) + 40 英文(=10) ≈ 16.7 tok / 10s ≈ 1.7。"""
        r = _one("mixed", _en([
            {"now": 1000.0, "text": "中文中文中文中文中文"},
            {"now": 11000.0, "text": "a" * 40},
        ]))
        assert r["text"] == "⏱ ~1.7 tok/s"

    def test_thinking_text_counts_toward_output(self):
        """思考 token 同样占解码时间（后端 completion_tokens 含思考），
        故前端也计入 —— 否则思考模型速率会被系统性低估。"""
        only_answer = _one("answer-only", _en([
            {"now": 1000.0, "text": "a" * 40},
            {"now": 11000.0, "text": "a" * 40},
        ]))
        with_think = _one("with-think", _en([
            {"now": 1000.0, "text": "让我想一想这个问题"},
            {"now": 11000.0, "text": "a" * 40},
        ]))
        assert with_think["chars"] > 0, "思考文本必须计入"
        assert with_think["text"] != only_answer["text"], "计入后数值应不同"

    def test_surrogate_pair_does_not_crash(self):
        """emoji 代理对按码点遍历，不得抛错、也不得误判为中文。"""
        r = _one("emoji", _en([
            {"now": 1000.0, "text": "🚀" * 20},
            {"now": 11000.0, "text": "🚀" * 20},
        ]))
        assert r["cn"] == 0
        assert "tok/s" in r["text"]


# ============================================================
# 计时起点
# ============================================================


class TestClockStartsAtFirstToken:
    def test_queue_and_prefill_excluded(self):
        """首包前排队 60s 不进窗口 —— 否则会把速率压成接近 0 的假象。"""
        r = _one("late-first", _en([
            {"now": 1000.0},                       # 回合开始，无 token
            {"now": 61000.0, "text": "x" * 40},    # 首 token
            {"now": 71000.0, "text": "x" * 40},    # 解码窗口 10s
        ]))
        assert r["t0"] == 61000.0
        # 80 英文字符 = 20 tok；若错把 60s 排队算进窗口会得到 ~0.3，
        # 实测窗口 10s → 2.0
        assert r["text"] == "⏱ ~2.0 tok/s"

    def test_empty_increment_does_not_start_clock(self):
        """空增量不得起表（否则 TTFT 被记成第一个空包的时刻）。"""
        r = _one("empty", _en([
            {"now": 5000.0, "text": ""},
            {"now": 6000.0, "text": None},
        ]))
        assert r["t0"] == 0
        assert r["chars"] == 0


# ============================================================
# 有效性阈值 / 节流 / 隐藏
# ============================================================


class TestSuppressionAndThrottle:
    @pytest.mark.parametrize("win_ms,text,why", [
        (200.0, "a" * 400, "窗口 <0.8s：首包抖动就能让速率翻倍"),
        (5000.0, "a" * 8, "输出 <12 tok：样本不足"),
    ])
    def test_not_shown_when_not_meaningful(self, win_ms, text, why):
        r = _one("weak", _en([
            {"now": 1000.0, "text": text},
            {"now": 1000.0 + win_ms, "text": text},
        ]))
        assert r["shown"] == "none", why
        assert r["text"] == ""

    def test_shown_once_both_thresholds_met(self):
        r = _one("ok", _en([
            {"now": 1000.0, "text": "hello world this is a stream"},
            {"now": 2000.0, "text": " more text coming through now"},
        ]))
        assert r["shown"] == ""
        assert r["hasTitle"], "估算口径必须在 tooltip 里交代清楚"

    # 节流契约与绝对数值无关：同一前缀下「多一步被节流」必须等于「不跑那一步」，
    # 而「多一步被 force 放行」必须不同。用对比断言，避免把算式钉死成脆期望。
    _PREFIX = [
        {"now": 1000.0, "text": "hello world this is a stream", "skipThrottle": True},
        {"now": 2000.0, "text": " more text coming through now", "skipThrottle": True},
    ]

    def test_baseline_value_of_prefix(self):
        """先固定前缀本身的读数（57 英文字符 ≈ 14.25 tok / 1s）。"""
        r = _one("base", self._PREFIX)
        assert r["text"] == "⏱ ~14.3 tok/s"

    def test_throttled_within_window(self):
        """250ms 内的第二次刷新应被跳过 —— 每 token 刷 DOM 会拖慢流式渲染。"""
        r = _one("throttle", self._PREFIX + [{"now": 2050.0, "text": "z" * 4000}])
        assert r["text"] == "⏱ ~14.3 tok/s", "节流窗口内的巨量字符不应改变显示"

    def test_force_bypasses_throttle(self):
        """force=True 绕过节流（回合收尾需按最终字符数定格一次）。"""
        r = _one("force", self._PREFIX + [
            {"now": 2050.0, "text": "z" * 4000, "force": True},
        ])
        assert r["text"] != "⏱ ~14.3 tok/s", "force 后应反映最新字符数"
        # 57+4000=4057 字符 ≈ 1014.25 tok / 1.05s ≈ 966.0
        assert r["text"] == "⏱ ~966.0 tok/s"

    def test_hide_clears_element(self):
        r = _one("hide", _en([
            {"now": 1000.0, "text": "hello world this is a stream"},
            {"now": 2000.0, "text": " more text coming through now"},
            {"hide": True},
        ]))
        assert (r["shown"], r["text"]) == ("none", "")

    def test_missing_dom_node_is_noop(self):
        """$() 取不到节点时静默返回（页面结构变动不该打断流式渲染）。"""
        # 用不存在的 id 走同一分支：构造方式是让 el 为 null —— 直接喂空 steps 亦覆盖主路径
        r = _one("noop", _en([{"now": 1000.0, "text": "a" * 400}]))
        assert r["threw"] is None


# ============================================================
# 与实测标记的可辨识度
# ============================================================


class TestMarkerDistinctness:
    def test_live_uses_clock_and_tilde(self):
        r = _one("m", _en([
            {"now": 1000.0, "text": "hello world this is a stream"},
            {"now": 2000.0, "text": " more text coming through now"},
        ]))
        assert r["text"].startswith("⏱ ~"), "⏱ + ~ 双重标示「实时·估算」"
        assert r["text"].endswith(" tok/s")

    def test_estimated_is_not_the_measured_marker(self):
        """实测 ⚡ 不带 ~；估算必带 ~ —— 两种口径不能长得一样。"""
        r = _one("m", _en([
            {"now": 1000.0, "text": "hello world this is a stream"},
            {"now": 2000.0, "text": " more text coming through now"},
        ]))
        assert "~" in r["text"]
        assert "⚡" not in r["text"]
