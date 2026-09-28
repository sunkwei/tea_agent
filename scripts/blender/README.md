# scripts/blender — Blender 无头建模/动画脚本

通过 `toolkit_blender`（`blender.exe --background --python`）驱动，产物输出到 `output/huilan_ge/`（gitignore，不入库）。

| 脚本 | 作用 | 产物 |
|---|---|---|
| `huilan_ge_model.py` | 回澜阁参数化建模（双层八角亭+石台+栏杆+宝顶+瓦面+栈桥） | `huilan_ge.blend` / `.obj` / `.glb` + 5 张静帧 |
| `drone_orbit.py` | 无人机环绕镜头动画（20s @24fps=480帧，EEVEE PNG 序列） | 480 帧 PNG + 4 张关键帧预览 |

## 用法

```bash
# 1. 建模（需先跑一次，生成 .blend）
toolkit_blender(action='run', script_path='scripts/blender/huilan_ge_model.py')

# 2. 动画 — 先 dry-run 抽查相机路径（秒级，不渲染）
toolkit_blender(action='run', blend_file='output/huilan_ge/huilan_ge.blend',
                script_path='scripts/blender/drone_orbit.py', script_args=['dry'])

# 3. 动画 — 完整渲染（RTX 4060 上约 10min）
toolkit_blender(action='run', blend_file='output/huilan_ge/huilan_ge.blend',
                script_path='scripts/blender/drone_orbit.py')

# 4. PNG 序列 → MP4（Blender 5.x 直出 FFMPEG 有坑，见下）
ffmpeg -y -framerate 24 -start_number 1 -i output/huilan_ge/drone_orbit.mp4%04d.png \
       -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -movflags +faststart \
       output/huilan_ge/drone_orbit.mp4
```

命令行等价写法：`blender -b <blend> -P scripts/blender/drone_orbit.py -- dry`（`--` 之后为 script_args）。

## Blender 5.2 API 变更（踩坑记录，勿回退到旧写法）

1. **`Action.fcurves` 已移除**（Slotted Actions 重构）→ 走 `action.fcurves_compat`，
   或遍历 `action.layers[].strips[].channelbags[].fcurves`（见 `_iter_fcurves()`）
2. **`BLENDER_EEVEE_NEXT` 改名回 `BLENDER_EEVEE`**
3. **视频不能直出**：blend 若保存过 `STEREO_3D` 视图，`file_format` 运行时枚举不含 `FFMPEG`
   （即使 `bl_rna` 静态枚举里有）；须先 `render.use_multiview = False`，否则报错。
   注意 `views_format` 没有 `MONO` 选项（仅 `STEREO_3D` / `MULTIVIEW`）。
   当前脚本已改为 PNG 序列 + 外部 ffmpeg 合成，规避此问题。
