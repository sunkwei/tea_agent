#!/usr/bin/env python
# version: 1.0.0
"""Z-Image-Turbo 文生图 MCP Server（stdio）。

把本地 Z-Image-Turbo（通义 6B 单流 DiT，Apache-2.0）封装为标准 MCP 工具：

    toolkit_mcp(action='connect', server_name='z-image', command='python',
                args=[r'...\\zimage_server.py'])
    toolkit_mcp(action='call_tool', server_name='z-image',
                tool_name='zimage_generate', tool_args={'prompt': '一只柴犬'})

设计要点
    * 管线常驻：加载（含 int8 量化）约 25s，仅进程内做一次，后续出图 13s 起。
    * 显存自适应：<12GiB 用 torchao int8 量化 DiT+文本编码器，<24GiB 启用
      enable_model_cpu_offload；实测 8GiB 卡峰值 5.96GiB。
    * stdout 属于 MCP 协议，日志/进度一律走 stderr（tqdm 默认即 stderr）。

环境变量
    ZIMAGE_MODEL_DIR / ZIMAGE_OUTPUT_DIR / ZIMAGE_QUANT / ZIMAGE_OFFLOAD
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[z-image] %(message)s")
log = logging.getLogger("zimage")

HF_REPO = "Tongyi-MAI/Z-Image-Turbo"
TURBO_STEPS = 9  # 8 次 DiT 前向
TURBO_GUIDANCE = 0.0  # Turbo 无 CFG
DEFAULT_DIRS = (Path.home() / "models" / "Z-Image-Turbo",)

_pipe = None  # 常驻管线
_strategy: dict = {}
_lock = threading.Lock()


# ────────────────────────────── 模型 / 策略 ──────────────────────────────
def _resolve_model(model_dir: str | None = None) -> tuple[str, bool]:
    """返回 (模型目录或 HF repo id, 是否本地可用)。"""
    for cand in filter(None, [model_dir, os.environ.get("ZIMAGE_MODEL_DIR"), *DEFAULT_DIRS]):
        p = Path(cand).expanduser()
        if (p / "model_index.json").exists():
            return str(p), True
    return HF_REPO, False


def _vram_gb() -> float:
    try:
        import torch

        if not torch.cuda.is_available():
            return 0.0
        return round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2)
    except Exception:
        return 0.0


def _plan(quantization: str, offload: str, vram: float) -> dict:
    """显存自适应策略。

    实测（RTX 4060 Laptop 8GiB, 512x512, 9 步）：
        int8(DiT+TE) + 无 offload → 峰值 10.7GiB > 8GiB，落进共享内存抖动，280s
        int8(DiT+TE) + offload    → 峰值 5.96GiB，13.3s
        int8(DiT) + bf16(TE) + offload → 峰值 7.75GiB，23.3s
    结论：显存不足时「量化」不能替代「offload」，两者要一起上；只有量化后确实装得下
    （>=12GiB）才值得关掉逐层换入换出换取速度。
    """
    if vram <= 0:
        return {"device": "cpu", "quantization": "none", "offload": False, "vram_gb": 0.0}
    quant = ("int8" if vram < 12 else "none") if quantization in (None, "", "auto") else quantization
    if str(offload).lower() in ("auto", "", "none"):
        do_offload = vram < 24
        if quant != "none" and vram >= 12:  # 量化后单块 ~3GiB，常驻更快
            do_offload = False
    else:
        do_offload = str(offload).lower() in ("1", "true", "yes")
    if quant == "none":
        do_offload = True  # 全精度 11.7GiB DiT ＋ 7.7GiB 文本编码器，消费级卡必开
    return {"device": "cuda", "quantization": quant, "offload": do_offload, "vram_gb": vram}


def _quant_config(quant: str):
    """DiT + 文本编码器一起量化（省约 1.8GiB；只量化 DiT 在 8GiB 卡上余量不足）。"""
    from diffusers import PipelineQuantizationConfig
    from diffusers import TorchAoConfig as DiffAo
    from torchao.quantization import Int8WeightOnlyConfig
    from transformers import TorchAoConfig as TransAo

    return PipelineQuantizationConfig(
        quant_mapping={"transformer": DiffAo(Int8WeightOnlyConfig()), "text_encoder": TransAo(Int8WeightOnlyConfig())}
    )


def get_pipe(model_dir: str | None = None, quantization: str = "auto", offload: str = "auto"):
    """加载（或复用）管线；量化失败自动回退全精度 + offload。"""
    global _pipe, _strategy
    model_path, local = _resolve_model(model_dir)
    strategy = _plan(quantization, offload, _vram_gb())

    with _lock:
        if _pipe is not None and _strategy.get("model_path") == model_path:
            return _pipe, _strategy, ""

        import torch
        from diffusers import ZImagePipeline

        src = model_path if local else HF_REPO
        warn = ""
        for quant in [strategy["quantization"]] + (["none"] if strategy["quantization"] != "none" else []):
            t0 = time.time()
            try:
                kwargs: dict = {"dtype": torch.bfloat16}
                if quant != "none":
                    kwargs["quantization_config"] = _quant_config(quant)
                log.info("加载管线 model=%s quant=%s offload=%s", src, quant, strategy["offload"])
                pipe = ZImagePipeline.from_pretrained(src, **kwargs)
            except Exception as e:  # 量化后端缺失/不兼容 → 回退
                warn = f"quantization={quant} 失败已回退: {type(e).__name__}: {e}"
                log.warning(warn)
                strategy["quantization"], strategy["offload"] = "none", True
                continue
            if strategy["device"] == "cuda":
                pipe.enable_model_cpu_offload() if strategy["offload"] else pipe.to("cuda")
            try:
                pipe.vae.enable_slicing()  # VAE 解码是 8GiB 卡的显存峰值来源
            except Exception:
                pass
            try:
                pipe.set_progress_bar_config(disable=True)
            except Exception:
                pass
            _pipe = pipe
            _strategy = {**strategy, "quantization": quant, "model_path": model_path, "local": local}
            log.info("就绪，用时 %.1fs", time.time() - t0)
            return _pipe, _strategy, warn
        raise RuntimeError("模型加载失败（量化与全精度均失败，详见 stderr 日志）")


def _free() -> None:
    """卸载管线并释放显存。"""
    global _pipe, _strategy
    with _lock:
        _pipe, _strategy = None, {}
    try:
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# ────────────────────────────── 进度钩子 ──────────────────────────────
_progress = None  # 可选的 (done, total, text) 回调，供 GUI 使用


def set_progress_hook(fn) -> None:
    """注册进度回调 fn(done: int, total: int, text: str)；传 None 取消。

    做成模块级钩子而不是 zimage_generate 的入参：函数签名会被 MCP 暴露给模型，
    而进度回调是进程内 GUI 的需求，不该出现在工具 schema 里。
    """
    global _progress
    _progress = fn


def _report(done: int, total: int, text: str = "") -> None:
    """上报进度；回调异常不得打断生成主流程。"""
    if _progress is None:
        return
    try:
        _progress(int(done), int(total), text)
    except Exception:
        log.debug("进度回调异常已忽略", exc_info=True)


def _fmt(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)


# ────────────────────────────── MCP 工具 ──────────────────────────────
def zimage_generate(
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    num_inference_steps: int = TURBO_STEPS,
    guidance_scale: float = TURBO_GUIDANCE,
    seed: int = -1,
    num_images: int = 1,
    output_dir: str = "",
    model_dir: str = "",
    quantization: str = "auto",
    offload: str = "auto",
    max_sequence_length: int = 512,
) -> str:
    """用本地 Z-Image-Turbo 生成图片（文生图）。

    Args:
        prompt: 提示词，支持中英文（中英文字渲染是该模型强项），描述越具体越好。
        negative_prompt: 负面提示词；Turbo 走 guidance_scale=0 无 CFG，基本不生效。
        width: 宽，16 的倍数，默认 1024。
        height: 高，16 的倍数，默认 1024。
        num_inference_steps: 采样步数，Turbo 默认 9（=8 次 DiT 前向），加步收益很小。
        guidance_scale: CFG 强度，Turbo 必须 0.0。
        seed: 随机种子，-1 表示随机。
        num_images: 生成张数 1-4。
        output_dir: 输出目录，默认 <项目>/output/zimage。
        model_dir: 模型目录，默认自动探测。
        quantization: auto|int8|none，默认 auto（<12GiB 显存自动 int8）。
        offload: auto|true|false 逐层 CPU offload，默认 auto。
        max_sequence_length: 文本 token 上限，默认 512。

    Returns:
        JSON 字符串：{'ok': True, 'images': [绝对路径...], 'seed': int, 'elapsed_sec': float, ...}
    """
    if not prompt or not prompt.strip():
        return _fmt({"ok": False, "error": "prompt 不能为空"})
    width, height = max(64, width // 16 * 16), max(64, height // 16 * 16)
    n = max(1, min(int(num_images), 4))
    seed = -1 if seed is None else int(seed)

    try:
        pipe, strategy, warn = get_pipe(model_dir or None, quantization, offload)
    except Exception as e:
        return _fmt({"ok": False, "error": f"模型加载失败: {type(e).__name__}: {e}"})

    import torch

    if seed < 0:
        seed = int(torch.randint(0, 2**31 - 1, (1,)).item())
    out_dir = Path(output_dir or os.environ.get("ZIMAGE_OUTPUT_DIR") or (Path.cwd() / "output" / "zimage"))
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    paths: list[str] = []
    steps = max(1, int(num_inference_steps))
    total_units = n * steps

    def _step_cb(_pipe, step, _timestep, cb_kwargs, _base=0, _idx=0):
        """每个去噪步结束时的进度上报（返回值需原样带回给调度器）。"""
        _report(_base + step + 1, total_units, f"第 {_idx + 1}/{n} 张 · 步骤 {step + 1}/{steps}")
        return cb_kwargs

    try:
        for i in range(n):
            base = i * steps
            kwargs: dict = dict(
                prompt=prompt,
                height=height,
                width=width,
                num_inference_steps=steps,
                guidance_scale=float(guidance_scale),
                generator=torch.Generator("cuda").manual_seed(seed + i),
                max_sequence_length=int(max_sequence_length),
                callback_on_step_end=lambda p, s, t, kw, _b=base, _i=i: _step_cb(p, s, t, kw, _b, _i),
            )
            if negative_prompt:
                kwargs["negative_prompt"] = negative_prompt
            image = pipe(**kwargs).images[0]
            target = out_dir / f"zimage_{time.strftime('%Y%m%d_%H%M%S')}_{seed + i}.png"
            image.save(target)
            paths.append(str(target.resolve()))
    except Exception as e:
        _free()  # 显存状态可能已损坏，下次重新加载
        return _fmt({"ok": False, "error": f"生成失败: {type(e).__name__}: {e}", "strategy": strategy})

    elapsed = round(time.time() - t0, 2)
    log.info("出图完成 %dx%d seed=%s %.1fs", width, height, seed, elapsed)
    return _fmt(
        {
            "ok": True,
            "images": paths,
            "seed": seed,
            "size": f"{width}x{height}",
            "elapsed_sec": elapsed,
            "per_image_sec": round(elapsed / n, 2),
            "model": HF_REPO,
            "quantization": strategy.get("quantization"),
            "offload": strategy.get("offload"),
            "vram_gb": strategy.get("vram_gb"),
            "warn": warn or None,
        }
    )


def zimage_info() -> str:
    """自检：本地权重完整性、显卡显存、依赖版本、当前策略与管线是否已驻留。

    Returns:
        JSON 字符串，含 ready / missing / hardware / planned_strategy / loaded。
    """
    import importlib

    pkg = {}
    for name in ("torch", "diffusers", "transformers", "accelerate", "torchao", "PIL"):
        try:
            pkg[name] = getattr(importlib.import_module(name), "__version__", "?")
        except Exception:
            pkg[name] = "MISSING"

    model_path, local = _resolve_model()
    missing: list[str] = []
    if local:
        root = Path(model_path)
        for index_rel, wdir in (
            ("transformer/diffusion_pytorch_model.safetensors.index.json", "transformer"),
            ("text_encoder/model.safetensors.index.json", "text_encoder"),
        ):
            idx = root / index_rel
            if not idx.exists():
                missing.append(index_rel)
                continue
            try:
                wm = json.loads(idx.read_text(encoding="utf-8")).get("weight_map", {})
            except Exception:
                missing.append(f"{index_rel}(解析失败)")
                continue
            missing += [f"{wdir}/{s}" for s in sorted(set(wm.values())) if not (root / wdir / s).exists()]
        for rel in ("vae/diffusion_pytorch_model.safetensors", "tokenizer/tokenizer.json", "scheduler/scheduler_config.json"):
            if not (root / rel).exists():
                missing.append(rel)

    vram = _vram_gb()
    return _fmt(
        {
            "ok": True,
            "ready": bool(local and not missing),
            "model_path": model_path,
            "local": local,
            "missing": missing,
            "hardware": {"vram_gb": vram, "cuda": vram > 0},
            "packages": pkg,
            "planned_strategy": _plan("auto", "auto", vram),
            "loaded": _pipe is not None,
            "current_strategy": _strategy or None,
        }
    )


def zimage_unload() -> str:
    """卸载常驻管线并释放显存（下次生成会重新加载，约 25s）。"""
    was = _pipe is not None
    _free()
    return _fmt({"ok": True, "unloaded": was})


def _warmup() -> None:
    """在主线程预热重型导入与 CUDA 上下文。

    必须在 mcp.run() 之前调用。FastMCP 把同步工具函数丢进工作线程执行，而「首次」重型导入
    若发生在工作线程（此时主线程正阻塞在 stdin 读取上），在 Windows 上会无限期挂死
    （实测：零 CPU/GPU 消耗地卡满 900s 超时，之后同样的调用却只要 0.1s）。

    ⚠️ 必须解析**懒加载属性**，而不只是 import 包本身：`diffusers.ZImagePipeline` 走
    模块 __getattr__ 懒导入，只写 `import diffusers` 不会触发，真正的重导入仍会落在线程里。
    因此这里逐个显式落地工具路径上会用到的名字。
    """
    t0 = time.time()
    import torch

    torch.cuda.is_available()
    if torch.cuda.is_available():
        torch.zeros(1, device="cuda")  # 真正建立 CUDA 上下文

    def _try(desc: str, fn) -> None:
        try:
            fn()
        except Exception as e:  # 可选依赖缺失不应阻止服务启动
            log.warning("预热 %s 失败: %s", desc, e)

    _try("diffusers", lambda: __import__("diffusers"))
    _try("transformers", lambda: __import__("transformers"))
    _try("PIL.Image", lambda: __import__("PIL.Image"))
    # 懒加载属性：必须显式取一次，否则首次访问仍在线程里
    _try("diffusers.ZImagePipeline", lambda: __import__("diffusers", fromlist=["ZImagePipeline"]).ZImagePipeline)
    _try("diffusers.PipelineQuantizationConfig", lambda: __import__("diffusers", fromlist=["PipelineQuantizationConfig"]).PipelineQuantizationConfig)
    _try("diffusers.TorchAoConfig", lambda: __import__("diffusers", fromlist=["TorchAoConfig"]).TorchAoConfig)
    _try("transformers.TorchAoConfig", lambda: __import__("transformers", fromlist=["TorchAoConfig"]).TorchAoConfig)
    _try("torchao.quantization.Int8WeightOnlyConfig", lambda: __import__("torchao.quantization", fromlist=["Int8WeightOnlyConfig"]).Int8WeightOnlyConfig)
    log.info("预热完成 %.1fs（torch=%s cuda=%s）", time.time() - t0, torch.__version__, torch.cuda.is_available())


def main() -> None:
    """启动 stdio MCP Server。"""
    from mcp.server.fastmcp import FastMCP

    _warmup()
    mcp = FastMCP("z-image")
    mcp.tool()(zimage_generate)
    mcp.tool()(zimage_info)
    mcp.tool()(zimage_unload)
    log.info("Z-Image MCP server 启动（stdio）model=%s", _resolve_model()[0])
    mcp.run()


if __name__ == "__main__":
    main()
