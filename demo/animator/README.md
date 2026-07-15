# 🎬 Animator — AI 动画生成工具

根据文字描述自动生成 HTML Canvas 动画，支持播放和录制为 MP4。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 生成 + 播放动画
cd demo
python main.py "红色弹跳球"

# 生成 + 播放 + 录制 MP4
python main.py "彩色粒子 10秒" --record

# 查看所有支持的动画类型
python main.py --list-config
```

## 支持的动画类型

| 类型 | 关键词 | 示例 |
|------|--------|------|
| 粒子系统 | 粒子、烟火、星星、气泡 | `"蓝色星星"` |
| 弹跳球 | 球、弹跳球、碰撞 | `"红色弹跳球"` |
| 彩虹渐变 | 彩虹、渐变 | `"彩虹波浪"` |
| 波浪 | 波浪、海浪 | `"绿色波浪"` |
| 螺旋 | 螺旋、旋转、万花筒 | `"金色螺旋"` |
| 极光 | 极光、光 | `"紫色极光"` |
| 几何图形 | 几何、多边形 | `"彩色几何"` |
| 文字动画 | 文字、文本、hello | `"Hello World"` |
| 📱 手机进化史 | 手机、进化、历史 | `"手机进化史"` |

支持颜色词：红、橙、黄、绿、青、蓝、紫、彩。

## 架构

```
animator/
├── __init__.py          # 包入口
├── html_generator.py    # 文字→HTML Canvas 动画生成
├── player.py            # pywebview 原生窗口播放
├── recorder.py          # Playwright 截图 + ffmpeg 合成 MP4
└── templates/
    └── animation.html   # HTML Canvas 动画模板
```

### 组件

- **AnimationGenerator** — 关键词匹配 → 动画类型 + 颜色 → 生成 HTML
- **WebviewPlayer** — 用 `pywebview` 在原生窗口中播放 HTML
- **Recorder** — Playwright 逐帧截图，ffmpeg 合成 MP4

## 命令行参数

```
python main.py [描述] [选项]

选项:
  -d, --duration    动画时长(秒)，默认 5
  --record          录制为 MP4
  --play            播放已有 HTML 文件
  --no-play         生成后不播放
  --no-tts          禁用语音旁白（手机故事）
  --fullscreen      全屏播放
  --output-dir      输出目录，默认 ./output
  --fps             录制帧率，默认 24
  --quality         视频质量 CRF，默认 23
  --list-config     列出支持的动画类型
```

## 依赖

- Python 3.10+
- `pywebview` — 原生窗口播放
- `playwright` — HTML 渲染/截图（录制用）
- `ffmpeg` — 视频合成（录制用，需系统安装）
