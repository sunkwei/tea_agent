"""会话图片的统一编解码工具（唯一事实源）。

两个关注点合并在本模块，避免调用方各自实现出偏差：

1. **引用编码** —— 图片二进制只存 ``images`` 表（BLOB），
   ``conversations.user_msg["images"]`` 只保存 ``img:<id>`` 轻量引用。
   原因：``get_conversations`` 每次历史加载都会 SELECT ``user_msg``，
   若把 base64 内联进去，每轮历史都要搬运数 MB；引用形态让历史查询保持轻量。
2. **data URL 编解码** —— Web/API 上传路径以 ``data:image/...;base64,`` 传入，
   入库前解码为 BLOB。

引用形态对旧数据向后兼容：解析失败返回 ``None``，调用方原样保留
（旧库里可能存有文件路径或 data URL）。
"""

from __future__ import annotations

import base64

#: 图片引用前缀。格式固定 ``img:<images.id>``，可 grep、无歧义。
IMAGE_REF_PREFIX = "img:"

#: 扩展名 → MIME（文件路径入参的兼容映射）
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

#: MIME → 扩展名（导出/下载时用）
EXT_BY_MIME = {v: k for k, v in MIME_BY_EXT.items()}

__all__ = [
    "EXT_BY_MIME",
    "IMAGE_REF_PREFIX",
    "MIME_BY_EXT",
    "build_data_url",
    "is_image_ref",
    "make_image_ref",
    "parse_data_url",
    "parse_image_ref",
]


# ── 引用 ──────────────────────────────────────────────────────


def make_image_ref(image_id: int) -> str:
    """把 ``images.id`` 编码为引用字符串。

    Args:
        image_id: ``images`` 表主键。

    Returns:
        形如 ``img:12`` 的引用。
    """
    return f"{IMAGE_REF_PREFIX}{image_id}"


def parse_image_ref(value) -> int | None:
    """解析图片引用为 ``images.id``。

    接受 ``img:<id>`` 字符串或正整数。其他任何形态（文件路径、``data:``
    URL、外链、空值）一律返回 ``None``，由调用方按旧格式处理。

    Args:
        value: 待解析的值。

    Returns:
        图片主键；非引用返回 ``None``。
    """
    if isinstance(value, bool):
        # bool 是 int 的子类，但语义上不是 id
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        if not value.startswith(IMAGE_REF_PREFIX):
            return None
        tail = value[len(IMAGE_REF_PREFIX):].strip()
        if tail.isdigit() and int(tail) > 0:
            return int(tail)
    return None


def is_image_ref(value) -> bool:
    """判断值是否为合法图片引用。"""
    return parse_image_ref(value) is not None


# ── data URL ──────────────────────────────────────────────────


def parse_data_url(value: str) -> tuple[str, bytes | None]:
    """解析 ``data:<mime>;base64,<payload>``。

    Args:
        value: 待解析字符串。

    Returns:
        ``(mime, blob)``。非 data URL 或 payload 非法时 blob 为 ``None``，
        mime 回落 ``image/png``。
    """
    if not isinstance(value, str) or not value.startswith("data:"):
        return "image/png", None
    try:
        header, _, payload = value.partition(",")
        if not payload:
            return "image/png", None
        mime = header[len("data:"):].split(";")[0].strip() or "image/png"
        if "base64" not in header:
            # 非 base64（如 URL 编码）形态本项目不产出，按解析失败处理
            return mime, None
        return mime, base64.b64decode(payload, validate=False)
    except Exception:
        return "image/png", None


def build_data_url(blob: bytes, mime: str = "image/png") -> str:
    """把二进制编码为 data URL（前端 <img src> 直接可用）。

    Args:
        blob: 图片二进制。
        mime: MIME 类型。

    Returns:
        ``data:<mime>;base64,<payload>``。
    """
    if not blob:
        return ""
    return f"data:{mime or 'image/png'};base64,{base64.b64encode(blob).decode('ascii')}"
