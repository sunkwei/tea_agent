"""
向后兼容导出：from tea_agent.store import Storage, get_storage 保持不变。
"""
from ._core import Storage

__all__ = ["Storage"]

# ── 模块级单例 ──

_storage_instance = None

def get_storage(db_path: str = "") -> Storage:
    """获取或创建 Storage 单例（供工具函数使用）。

    首次调用时锁定数据库路径，后续配置切换不影响已建立的数据库连接。
    这样在 Web 界面切换配置时，正在进行的主题仍写入同一个数据库，
    用户可临时切换到支持多模态输入的模型配置，而数据库不切换。
    """
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance
    if not db_path:
        try:
            from tea_agent.config import get_config
            db_path = get_config().paths.db_path_abs
        except Exception:
            db_path = "chat_history.db"
    _storage_instance = Storage(db_path)
    return _storage_instance
