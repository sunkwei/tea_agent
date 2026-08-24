# version: 1.0.0
"""发布文档为可下载链接。

用户明确要求"创建xx文档"（接口文档、README、md 等）时，
保存文档后调用本工具，将文件发布到 ~/.tea_agent/exports/ 目录，
返回 /v1/download/{filename} 下载链接（Web 前端可直接点击下载）。
"""

import os
import re
import shutil

_EXPORTS_DIR = os.path.join(os.path.expanduser("~"), ".tea_agent", "exports")
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _clean_filename(name: str) -> str:
    """清理文件名为安全文件名（去除非法字符与路径分隔符）。"""
    name = _ILLEGAL.sub("_", name or "").strip().strip(".")
    return name or "document"


def toolkit_publish_doc(source_path: str = "", title: str = "") -> dict:
    """将已保存的文档发布到可下载目录，返回下载链接。

    典型流程（创建文档类任务）：
        1. toolkit_file 保存文档到项目内路径（action='write'）
        2. toolkit_publish_doc 发布 → 拿到 /v1/download/xxx.md 链接
        3. final msg 输出 Markdown 下载链接：[📄 下载文档](/v1/download/xxx.md)

    Args:
        source_path: 已保存的文档文件路径（必填）
        title: 下载显示的文件名（不含路径；默认取源文件名；自动补 .md 等扩展名）

    Returns:
        {"ok": True, "url": "/v1/download/xxx.md", "filename": "xxx.md",
         "local_path": "...", "size": 123} 或错误 dict
    """
    try:
        if not source_path:
            return {"ok": False, "error": "source_path 必填（已保存的文档路径）"}
        src = os.path.abspath(os.path.expanduser(source_path))
        if not os.path.isfile(src):
            return {"ok": False, "error": f"源文件不存在: {source_path}"}

        # 目标文件名：title 优先，否则源文件名
        if title:
            filename = _clean_filename(os.path.basename(title))
            # 保留源文件扩展名（title 未带扩展名时）
            src_ext = os.path.splitext(src)[1]
            if src_ext and not os.path.splitext(filename)[1]:
                filename += src_ext
        else:
            filename = _clean_filename(os.path.basename(src))

        os.makedirs(_EXPORTS_DIR, exist_ok=True)
        dst = os.path.join(_EXPORTS_DIR, filename)

        # 幂等：同名覆盖（URL 稳定，重复发布不产生垃圾文件）
        shutil.copy2(src, dst)

        size = os.path.getsize(dst)
        url = "/v1/download/" + filename
        return {
            "ok": True,
            "url": url,
            "filename": filename,
            "local_path": dst,
            "size": size,
            "hint": f"在 final msg 中输出下载链接: [📄 下载文档]({url})",
        }
    except Exception as e:
        return {"ok": False, "error": f"发布失败: {e}"}


def meta_toolkit_publish_doc() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_publish_doc",
            "description": (
                "发布文档到可下载目录并返回下载链接。"
                "当用户明确要求创建文档（接口文档、README、md 等）并已用 "
                "toolkit_file 保存后，调用此工具发布，"
                "然后在最终回复中输出 Markdown 下载链接 [📄 下载xxx](/v1/download/文件名)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "已保存的文档文件路径（必填）",
                    },
                    "title": {
                        "type": "string",
                        "description": "下载显示的文件名（可选，默认取源文件名；自动保留扩展名）",
                    },
                },
                "required": ["source_path"],
            },
        },
    }
