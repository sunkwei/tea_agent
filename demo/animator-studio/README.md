# 📱 Animator Studio

基于 [animator](../animator) 动画引擎的 **Web 动画工作室**，
提供 REST API + Web UI，让用户通过自然语言创建、预览、录制动画。

## 愿景

> 从「文字描述」到「动画视频」—— 零代码、零门槛

## 架构

```
┌─────────────────┐     ┌──────────────┐     ┌───────────┐
│   Web UI/API    │ ──▶ │  Studio Core │ ──▶ │  Animator │
│  (Flask/FastAPI)│ ◀── │  (编排调度)  │ ◀── │  (引擎)   │
└─────────────────┘     └──────────────┘     └───────────┘
```

| 层 | 职责 |
|----|------|
| **Web UI** | 文本输入、动画预览、下载管理 |
| **API** | RESTful 接口（生成/录制/列表） |
| **Studio Core** | 编排生成→录制→输出流程 |
| **Animator** | 底层动画引擎（HTML 生成 + MP4 录制） |

## 快速开始

```bash
cd demo/animator-studio

# 安装依赖
pip install -r requirements.txt

# 启动 Web 服务
python -m src.app

# 或 CLI 模式
python -m src.cli "彩色粒子" --record
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/generate` | 根据文字生成动画 HTML |
| POST | `/api/record` | 录制动画为 MP4 |
| GET  | `/api/animations` | 列出已有动画 |
| GET  | `/api/videos` | 列出已录制视频 |
| GET  | `/player/<id>` | 播放动画 |

## 扩展点

- `src/core/generator.py` — 自定义生成策略
- `src/core/recorder.py` — 自定义录制逻辑
- `src/api/routes.py` — 新增 API 端点
- `src/web/templates/` — 自定义 UI 页面
