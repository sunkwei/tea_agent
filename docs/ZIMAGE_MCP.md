# Z-Image-Turbo 文生图 MCP Server

把本地 **Z-Image-Turbo**（阿里通义，6B 单流 DiT，Apache-2.0）封装为 MCP 服务，tea_agent 经 `toolkit_mcp` 调用。

## 1. 模型

| 项 | 值 |
|---|---|
| 权重 | `Tongyi-MAI/Z-Image-Turbo`（HF 官方 bf16 全量） |
| 路径 | `C:\Users\Hetin\models\Z-Image-Turbo`（30.6 GiB / 39 文件） |
| 结构 | DiT 11.7G + Qwen3-4B 文本编码器 7.7G + 16ch VAE 0.16G |
| 推理 | Turbo 蒸馏版：`steps=9`（=8 次 DiT 前向）、`guidance_scale=0.0`（无 CFG） |
| 许可证 | Apache-2.0 |

## 2. 环境（本机实测）

- GPU：RTX 4060 Laptop **8 GiB** → 必须量化 + CPU offload
- 解释器：`%LOCALAPPDATA%\Programs\Python\Python311\python.exe`（torch 2.11.0+cu128 / diffusers 0.40.0 / transformers 5.13.0 / torchao 0.18.0）

> ⚠️ 本机另有 `venv_work` 环境（无 ZImagePipeline/torchao）。**必须**用上面的解释器，故提供启动器 `scripts/zimage_mcp.cmd` 锁定路径。

## 3. 显存策略（实测对比，512×512）

| 配置 | 峰值显存 | 单张耗时 |
|---|---|---|
| int8(DiT+TE) + **无** offload | 10.7 GiB ❌ 超限走共享内存 | **280 s** |
| int8(DiT+TE) + offload | 5.96 GiB ✅ | **13 s** |
| int8(DiT) + bf16(TE) + offload | 7.75 GiB ✅ | 23 s |

结论：**量化不能替代 offload**；8 GiB 卡上「int8 量 DiT+文本编码器 + 逐层 offload」最优。`auto` 已内置该判定。

## 4. 使用

```python
# 连接（启动器已锁定解释器）
toolkit_mcp(action='connect', server_name='z-image',
            command=r'C:\Users\Hetin\work\git\tea_agent\scripts\zimage_mcp.cmd')

# 自检：权重完整性 / 显存 / 依赖 / 当前策略
toolkit_mcp(action='call_tool', server_name='z-image', tool_name='zimage_info')

# 出图（管线常驻，首张含加载 ~26s）
toolkit_mcp(action='call_tool', server_name='z-image', tool_name='zimage_generate',
            tool_args={'prompt': '水墨江南清晨，白墙黛瓦，薄雾小桥',
                       'width': 1024, 'height': 1024, 'seed': 42})

# 让出显存
toolkit_mcp(action='call_tool', server_name='z-image', tool_name='zimage_unload')
```

MCP 工具：`zimage_generate` / `zimage_info` / `zimage_unload`

## 5. 实测性能（RTX 4060 Laptop 8 GiB）

| 场景 | 耗时 |
|---|---|
| 冷启动加载（int8 + offload） | 26–30 s |
| 出图 512×512 | **12–13 s** |
| 出图 1024×1024 | **30 s** |
| MCP 通道开销 | ≈ 0 s（`zimage_info` 0.0 s） |

## 6. 两个已知坑（已修复，勿回退）

1. **Windows 上首次重型导入落在工作线程会挂死**（零 CPU/GPU 消耗卡满 900 s 超时）。
   FastMCP 把同步工具丢进线程执行，此时主线程阻塞在 stdin；必须在 `mcp.run()` 前于主线程预热。
   且必须解析**懒加载属性**（`diffusers.ZImagePipeline` 走 `__getattr__`，只 `import diffusers` 不触发）。
2. **量化配置 API**：diffusers 与 transformers 的量化配置签名不一致，必须用
   `PipelineQuantizationConfig(quant_mapping={...})` 逐组件指定；且构造要放在 `try` 内，否则回退路径形同虚设。

## 7. 未采用：第三方 int8 权重

`Winnougan/Z-Image-Base-Turbo-INT8-Convrot` 为 **ComfyUI 专用格式**（`comfy_quant` + `weight_scale` 自定义键，793 键，含 ConvRot Hadamard 旋转），**diffusers 无法加载**（GGUF 亦不支持该架构）。故改用 diffusers + torchao 在线量化，效果等同且零下载。

## 8. 局限

- 中文字渲染非 100% 准确：实测招牌「造相」渲染为形近伪文字，长文本更明显。
- Turbo 无 CFG → `negative_prompt` 基本无效。
- 建议提示词写具体画面要素，避免依赖模型精确绘字。
