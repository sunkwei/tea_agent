"""
会话树 + 分支系统 — 借鉴 Pi Agent Harness 的 session tree 设计

功能：
  - 树结构会话存储（每个节点有 id + parentId）
  - 在当前位置创建分支（不复制历史）
  - 分支切换（tree navigation）
  - 分支摘要（离开分支时自动摘要）
  - JSONL 持久化存储

设计：
  - 每条消息是一个 Node，包含 id, parent_id, content, metadata
  - 无分叉的线性会话退化为单链（兼容旧数据）
  - 分支时自动记录分支原因和摘要

用法：
    from session.session_tree import SessionTree, SessionNode

    tree = SessionTree()
    tree.append("user", "Hello")
    tree.append("assistant", "Hi!")
    tree.branch("user", "Let's try approach B instead")
    tree.switch_to("node_abc123")  # 切换到另一分支
    tree.branch_summary("node_xyz")  # 获取分支摘要
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("session.session_tree")


@dataclass
class SessionNode:
    """会话树中的一个节点（一条消息）。"""
    id: str
    parent_id: str | None          # 父节点 ID（None = 根节点）
    role: str                      # user / assistant / system / tool
    content: str | list | None     # 消息内容
    created_at: str = ""           # ISO 时间戳
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionNode":
        return cls(
            id=d["id"],
            parent_id=d.get("parent_id"),
            role=d["role"],
            content=d.get("content"),
            created_at=d.get("created_at", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class BranchInfo:
    """分支信息。"""
    node_id: str                   # 分支起始节点 ID
    label: str                     # 分支标签（如 "approach A"）
    summary: str = ""              # 分支摘要
    created_at: str = ""           # 创建时间
    message_count: int = 0         # 分支中的消息数

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "summary": self.summary,
            "created_at": self.created_at,
            "message_count": self.message_count,
        }


class SessionTree:
    """会话树 — 树结构 + 分支 + 导航。

    属性：
        nodes: 所有节点字典 {node_id: SessionNode}
        root_id: 根节点 ID
        current_id: 当前节点 ID
        branches: 分支信息字典 {node_id: BranchInfo}
        head_id: 当前分支的末端节点 ID
    """

    def __init__(self, tree_id: str | None = None):
        self.tree_id = tree_id or str(uuid.uuid4())[:8]
        self.nodes: dict[str, SessionNode] = {}
        self.root_id: str | None = None
        self.current_id: str | None = None  # 当前浏览的节点
        self.head_id: str | None = None     # 当前分支的尾部
        self.branches: dict[str, BranchInfo] = {}  # node_id -> BranchInfo

    # ── 节点操作 ──────────────────────────────────────────

    def append(self, role: str, content: str | list | None = None, **metadata) -> SessionNode:
        """追加一条消息到当前分支末端。

        Args:
            role: user/assistant/system/tool
            content: 消息内容
            metadata: 附加元数据

        Returns:
            新创建的节点
        """
        node_id = str(uuid.uuid4())
        node = SessionNode(
            id=node_id,
            parent_id=self.head_id,
            role=role,
            content=content,
            metadata=metadata,
        )

        self.nodes[node_id] = node

        if self.root_id is None:
            self.root_id = node_id

        self.head_id = node_id
        self.current_id = node_id

        logger.debug(f"📝 追加节点 [{node_id[:8]}] role={role} parent={node.parent_id[:8] if node.parent_id else 'None'}")
        return node

    def branch(self, role: str, content: str | list | None = None, label: str = "", **metadata) -> SessionNode:
        """从当前位置创建一个分支。

        分支 = 创建一个新节点作为当前节点的子节点，
        后续 append 在该分支上继续。

        Args:
            role: user/assistant
            content: 消息内容（通常是用户的新输入）
            label: 分支标签（如 "方法A"、"修复方案"）
            metadata: 附加元数据

        Returns:
            新分支的节点
        """
        if self.current_id is None:
            return self.append(role, content, **metadata)

        parent_id = self.current_id
        node_id = str(uuid.uuid4())

        node = SessionNode(
            id=node_id,
            parent_id=parent_id,
            role=role,
            content=content,
            metadata={"branch_label": label, **metadata},
        )

        self.nodes[node_id] = node
        self.head_id = node_id
        self.current_id = node_id

        # 注册分支信息
        self.branches[node_id] = BranchInfo(
            node_id=node_id,
            label=label or f"分支 @ {datetime.now().strftime('%H:%M')}",
            message_count=1,
        )

        logger.info(f"🌿 创建分支 [{node_id[:8]}] 父节点=[{parent_id[:8]}] label={label}")
        return node

    def switch_to(self, node_id: str) -> bool:
        """切换到指定节点（浏览模式）。

        将 current_id 设为指定节点，后续 append 在该位置继续。

        Args:
            node_id: 目标节点 ID

        Returns:
            是否成功
        """
        if node_id not in self.nodes:
            logger.warning(f"切换失败: 节点 [{node_id[:8]}] 不存在")
            return False

        self.current_id = node_id
        self.head_id = node_id  # 切换后从此处继续 append
        logger.info(f"🔀 切换到节点 [{node_id[:8]}]")
        return True

    def fork(self, node_id: str) -> "SessionTree":
        """从指定节点分叉出一个新树。

        新树包含从根到指定节点的所有祖先节点和该节点本身。

        Args:
            node_id: 分叉起始节点

        Returns:
            新的 SessionTree 实例
        """
        if node_id not in self.nodes:
            raise ValueError(f"节点 [{node_id[:8]}] 不存在")

        new_tree = SessionTree(tree_id=f"{self.tree_id}_fork")
        ancestors = self._get_path_to_root(node_id)

        for n in ancestors:
            new_tree.nodes[n.id] = SessionNode(
                id=n.id,
                parent_id=n.parent_id,
                role=n.role,
                content=n.content,
                metadata=n.metadata,
            )

        new_tree.root_id = self.root_id
        new_tree.current_id = node_id
        new_tree.head_id = node_id

        logger.info(f"🍴 分叉新树 [{new_tree.tree_id}] 从节点 [{node_id[:8]}] ({len(ancestors)} 个节点)")
        return new_tree

    # ── 查询 ──────────────────────────────────────────────

    def get_path_to_root(self, node_id: str | None = None) -> list[SessionNode]:
        """获取从指定节点到根节点的路径。

        Args:
            node_id: 起始节点 ID（默认 current_id）

        Returns:
            从根到指定节点的节点列表
        """
        return self._get_path_to_root(node_id or self.current_id)

    def _get_path_to_root(self, node_id: str | None) -> list[SessionNode]:
        """内部：获取从根到节点的路径"""
        if node_id is None:
            return []

        path: list[SessionNode] = []
        current = node_id
        while current:
            node = self.nodes.get(current)
            if not node:
                break
            path.append(node)
            current = node.parent_id

        path.reverse()
        return path

    def get_children(self, node_id: str) -> list[SessionNode]:
        """获取指定节点的所有子节点。"""
        return [n for n in self.nodes.values() if n.parent_id == node_id]

    def get_branch_nodes(self, node_id: str) -> list[SessionNode]:
        """获取从指定节点到分支末端的所有节点。"""
        nodes = []
        current = node_id
        visited = set()
        while current and current not in visited:
            visited.add(current)
            node = self.nodes.get(current)
            if not node:
                break
            nodes.append(node)
            # 找子节点（如果有多子，选第一个？这里取 head 方向）
            children = self.get_children(current)
            if not children:
                break
            current = children[0].id
        return nodes

    def get_linear_messages(self, node_id: str | None = None) -> list[dict]:
        """获取线性消息列表（从根到指定节点），用于 API 调用。

        Args:
            node_id: 末端节点（默认 current_id）

        Returns:
            消息字典列表 [{role, content}, ...]
        """
        path = self._get_path_to_root(node_id or self.current_id)
        return [
            {"role": n.role, "content": n.content}
            for n in path if n.role in ("user", "assistant", "system")
        ]

    def get_current_depth(self) -> int:
        """获取当前节点深度。"""
        return len(self._get_path_to_root(self.current_id))

    def get_tree_stats(self) -> dict:
        """获取树统计信息。"""
        return {
            "total_nodes": len(self.nodes),
            "branch_count": len(self.branches),
            "current_depth": self.get_current_depth(),
            "root_id": self.root_id[:8] if self.root_id else None,
            "current_id": self.current_id[:8] if self.current_id else None,
            "head_id": self.head_id[:8] if self.head_id else None,
            "branches": [
                {"node_id": b.node_id[:8], "label": b.label, "count": b.message_count}
                for b in self.branches.values()
            ],
        }

    # ── 分支摘要 ─────────────────────────────────────────

    def set_branch_summary(self, node_id: str, summary: str):
        """设置分支摘要。

        Args:
            node_id: 分支节点 ID
            summary: 摘要文本
        """
        if node_id in self.branches:
            self.branches[node_id].summary = summary
            logger.info(f"📄 分支摘要已更新 [{node_id[:8]}]")
        else:
            logger.warning(f"设置摘要失败: 分支 [{node_id[:8]}] 不存在")

    def get_branch_summary(self, node_id: str) -> str:
        """获取分支摘要。"""
        info = self.branches.get(node_id)
        return info.summary if info else ""

    def generate_branch_summary_text(self, node_id: str, max_length: int = 500) -> str:
        """生成本地分支摘要文本（非 LLM 版本）。

        提取关键用户消息和助理响应。

        Args:
            node_id: 分支节点 ID
            max_length: 最大长度

        Returns:
            摘要文本
        """
        nodes = self.get_branch_nodes(node_id)
        if not nodes:
            return ""

        parts = []
        for n in nodes:
            if n.role == "user" and isinstance(n.content, str):
                parts.append(f"用户: {n.content[:200]}")
            elif n.role == "assistant" and isinstance(n.content, str):
                parts.append(f"助理: {n.content[:150]}")

        text = "\n".join(parts)
        if len(text) > max_length:
            text = text[:max_length] + "..."

        return text

    # ── 序列化 / 反序列化 ─────────────────────────────────

    def to_dict(self) -> dict:
        """导出为字典。"""
        return {
            "tree_id": self.tree_id,
            "root_id": self.root_id,
            "current_id": self.current_id,
            "head_id": self.head_id,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "branches": {bid: b.to_dict() for bid, b in self.branches.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionTree":
        tree = cls(tree_id=d.get("tree_id", str(uuid.uuid4())[:8]))
        tree.root_id = d.get("root_id")
        tree.current_id = d.get("current_id")
        tree.head_id = d.get("head_id")
        tree.nodes = {
            nid: SessionNode.from_dict(nd)
            for nid, nd in d.get("nodes", {}).items()
        }
        tree.branches = {
            bid: BranchInfo(**bd)
            for bid, bd in d.get("branches", {}).items()
        }
        return tree

    # ── JSONL 持久化 ─────────────────────────────────────

    def save_jsonl(self, path: str | Path):
        """保存为 JSONL 文件（每行一个节点）。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        header = {
            "type": "session_tree",
            "tree_id": self.tree_id,
            "root_id": self.root_id,
            "current_id": self.current_id,
            "head_id": self.head_id,
            "created_at": datetime.now().isoformat(),
        }

        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(header, ensure_ascii=False) + "\n")
            for node in self._get_path_to_root(self.head_id):
                f.write(json.dumps(node.to_dict(), ensure_ascii=False) + "\n")

        logger.info(f"💾 会话树已保存: {path} ({len(self.nodes)} 节点)")

    @classmethod
    def load_jsonl(cls, path: str | Path) -> "SessionTree":
        """从 JSONL 文件加载会话树。"""
        path = Path(path)
        tree = cls()

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            return tree

        # 第一行是 header
        header = json.loads(lines[0])
        tree.tree_id = header.get("tree_id", tree.tree_id)
        tree.root_id = header.get("root_id")
        tree.current_id = header.get("current_id")
        tree.head_id = header.get("head_id")

        # 其余行是节点
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                node = SessionNode.from_dict(data)
                tree.nodes[node.id] = node
            except json.JSONDecodeError as e:
                logger.warning(f"跳过无效行: {e}")

        logger.info(f"📂 会话树已加载: {path} ({len(tree.nodes)} 节点)")
        return tree

    # ── 兼容旧数据 ───────────────────────────────────────

    def import_linear_messages(self, messages: list[dict]) -> SessionNode:
        """从线性消息列表导入（兼容旧数据）。

        Args:
            messages: [{role, content}, ...]

        Returns:
            最后一个节点
        """
        last_node = None
        for msg in messages:
            node = self.append(
                role=msg.get("role", "user"),
                content=msg.get("content"),
            )
            last_node = node
        return last_node


# ═══ 快捷工具函数 ═══════════════════════════════════════

def session_tree_to_messages(tree: SessionTree, node_id: str | None = None) -> list[dict]:
    """将会话树转换为 API 消息列表。

    Args:
        tree: 会话树
        node_id: 末端节点 ID（默认 current_id）

    Returns:
        [{role, content}, ...]
    """
    return tree.get_linear_messages(node_id)


def messages_to_session_tree(messages: list[dict]) -> SessionTree:
    """将线性消息列表转换为会话树。"""
    tree = SessionTree()
    tree.import_linear_messages(messages)
    return tree
