"""
RESTful API — 动画生成/录制/查询接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from src.core.generator import generator, llm_generate
from src.core.recorder import recorder

router = APIRouter(prefix="/api", tags=["animation"])


# ── 数据模型 ──

class GenerateRequest(BaseModel):
    text: str = Field(..., description="动画描述文字")
    duration: Optional[float] = Field(None, description="时长(秒)")
    tts: bool = Field(True, description="是否启用语音")
    story: Optional[bool] = Field(None, description="强制故事/非故事模式")


class LLMGenerateRequest(BaseModel):
    text: str = Field(..., description="动画描述文字")
    duration: float = Field(8.0, description="目标时长(秒)")
    tts: bool = Field(True, description="是否启用语音旁白")


class RecordRequest(BaseModel):
    html_path: str = Field(..., description="动画 HTML 路径")
    duration: float = Field(5.0, description="录制时长")
    width: int = Field(1280, description="视频宽度")
    height: int = Field(720, description="视频高度")
    fps: int = Field(24, description="帧率")


# ── API 端点 ──

@router.post("/generate")
async def api_generate(req: GenerateRequest):
    """根据文字描述生成动画 HTML"""
    try:
        result = generator.generate(
            text=req.text,
            duration=req.duration,
            tts=req.tts,
            story=req.story,
        )
        return {"ok": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/llm-generate")
async def api_llm_generate(req: LLMGenerateRequest):
    """使用 LLM 生成动画脚本 → 渲染 HTML"""
    try:
        result = llm_generate(
            text=req.text,
            duration=req.duration,
            tts=req.tts,
        )
        return {"ok": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/record")
async def api_record(req: RecordRequest):
    """录制动画为 MP4"""
    try:
        result = recorder.record(
            html_path=req.html_path,
            duration=req.duration,
            width=req.width,
            height=req.height,
            fps=req.fps,
        )
        return {"ok": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/animations")
async def api_list_animations():
    """列出所有生成的动画"""
    return {"ok": True, "data": generator.list_animations()}


@router.get("/videos")
async def api_list_videos():
    """列出所有录制的视频"""
    return {"ok": True, "data": recorder.list_jobs()}


@router.get("/animations/{anim_id}")
async def api_get_animation(anim_id: str):
    """获取单个动画详情"""
    result = generator.get(anim_id)
    if not result:
        raise HTTPException(status_code=404, detail="动画不存在")
    return {"ok": True, "data": result}
