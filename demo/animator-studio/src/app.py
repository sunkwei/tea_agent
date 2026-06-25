"""
Animator Studio — Web 入口

启动:
    python -m src.app
    # 或
    uvicorn src.app:app --reload --port 8080
"""
import os
import sys
from pathlib import Path

# 确保可以找到 animator
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

from src.config import config
from src.api.routes import router as api_router

# 创建应用
app = FastAPI(
    title="Animator Studio",
    description="文字描述 → 动画视频",
    version="0.1.0",
)

# 挂载 API
app.include_router(api_router)

# 静态文件
static_dir = Path(__file__).resolve().parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 模板目录
templates_dir = Path(__file__).resolve().parent / "web" / "templates"


@app.get("/")
async def index():
    """首页"""
    index_path = templates_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return {"message": "Animator Studio API", "docs": "/docs"}


@app.get("/player/{anim_id}")
async def player(anim_id: str):
    """播放动画"""
    from src.core.generator import generator
    record = generator.get(anim_id)
    if not record:
        return HTMLResponse("<h2>动画不存在</h2>", status_code=404)
    player_tpl = templates_dir / "player.html"
    if player_tpl.exists():
        html = player_tpl.read_text(encoding="utf-8")
        html = html.replace("{{HTML_PATH}}", f"file:///{record['html_path'].replace(os.sep, '/')}")
        return HTMLResponse(html)
    # 回退：直接重定向到文件
    return FileResponse(record["html_path"])


@app.get("/studio")
async def studio():
    """动画工作室页面"""
    studio_path = templates_dir / "studio.html"
    if studio_path.exists():
        return HTMLResponse(studio_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>Studio 页面待构建</h2>")


def main():
    """命令行启动"""
    config.ensure_dirs()
    print(f"🎬 Animator Studio")
    print(f"   ├─ 地址: http://{config.host}:{config.port}")
    print(f"   ├─ API docs: http://{config.host}:{config.port}/docs")
    print(f"   └─ Studio: http://{config.host}:{config.port}/studio")
    uvicorn.run(
        "src.app:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
    )


if __name__ == "__main__":
    main()
