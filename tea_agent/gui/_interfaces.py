"""
@2026-05-15 gen by tea_agent, GUI 显示接口抽象层
用于解耦 ChatRenderer / StreamManager 等组件与 tkinter 具体实现，
方便单元测试和未来替换渲染引擎（如 Qt）。
"""

from abc import ABC, abstractmethod
from typing import Optional


class HtmlDisplay(ABC):
    """HTML 富文本渲染目标接口"""

    @abstractmethod
    def show_html(self, html: str) -> None:
        """加载并显示 HTML 内容"""
        ...

    @abstractmethod
    def clear(self) -> None:
        """清空显示"""
        ...


class TextDisplay(ABC):
    """纯文本输出接口（控制台/流式）"""

    @abstractmethod
    def append(self, text: str, tag: str = "") -> None:
        """追加文本，可选 tag 用于样式"""
        ...

    @abstractmethod
    def append_tagged(self, text: str, tag: str) -> None:
        """追加带样式标签的文本"""
        ...

    @abstractmethod
    def scroll_to_end(self) -> None:
        """滚动到末尾"""
        ...

    @abstractmethod
    def set_state(self, state: str) -> None:
        """设置控件状态 (normal/disabled)"""
        ...

    @abstractmethod
    def get_all_text(self) -> str:
        """获取全部文本内容"""
        ...


class StatusDisplay(ABC):
    """状态栏显示接口"""

    @abstractmethod
    def show(self, text: str) -> None:
        """更新状态栏文字"""
        ...


class ImagePicker(ABC):
    """图片选择接口"""

    @abstractmethod
    def pick_images(self) -> list:
        """打开文件对话框选择图片，返回路径列表"""
        ...

    @abstractmethod
    def show_popup(self, image_data: bytes) -> None:
        """显示图片放大弹窗"""
        ...
