"""SQL 安全助手 — 统一校验标识符与片段的构造入口。

背景：SQL 的表名 / 列名 / 占位符数量**无法用 `?` 参数化**，必须拼进语句字符串；
真正可注入的是「值」（必须参数化）与「未校验的标识符」。本模块把校验收敛到
一处，替代散落各处的 `assert` 与 "SAFETY:" 注释，使防护显式、可测试、可静态识别。

统一的静态可识别约定：SQL f-string 中的插值只允许为
    · 字面量常量
    · 全大写常量（模块/类常量约定）
    · 本模块助手的调用（或由其赋值而来的局部变量）
"""

from __future__ import annotations

import re

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FRAGMENT_RE = re.compile(r"^[A-Za-z0-9_\s,()*=?!<>]+$")
_DDL_RE = re.compile(r"^[A-Za-z0-9_\s,()*=\[\]'.+-]+$")
_QUALIFIED = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?"
_UNSAFE_SQL_RE = re.compile(r";|--|/\*|\*/")
# WHERE 片段：`列 运算符 值`，值可为 ?（参数化）/ 数字 / 引号字面量 / NULL / 括号组
_WHERE_OP = r"(?:=|!=|<>|>=|<=|>|<|LIKE|GLOB|NOT\s+LIKE|NOT\s+GLOB)"
_WHERE_VAL = (r"(?:\?|-?\d+(?:\.\d+)?|NULL|CURRENT_TIMESTAMP|"
              r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\([^()]*\))")
_WHERE_FRAG_RE = re.compile(
    rf"^{_QUALIFIED}\s*{_WHERE_OP}\s*{_WHERE_VAL}$", re.IGNORECASE
)
_WHERE_NULL_RE = re.compile(
    rf"^{_QUALIFIED}\s+IS\s+(?:NOT\s+)?NULL$", re.IGNORECASE
)
_WHERE_IN_RE = re.compile(
    rf"^{_QUALIFIED}\s+(?:NOT\s+)?IN\s*\([^();]*\)$", re.IGNORECASE
)


def safe_ident(name, allowed=None) -> str:
    """校验 SQL 标识符（表名 / 列名）。

    Args:
        name: 待校验标识符
        allowed: 可选白名单集合；给出时要求 name 必须在内

    Returns:
        校验通过的标识符字符串

    Raises:
        ValueError: 格式非法或不在白名单内
    """
    s = str(name)
    if not _IDENT_RE.match(s):
        raise ValueError(f"非法 SQL 标识符: {name!r}")
    if allowed is not None and s not in set(allowed):
        raise ValueError(f"标识符不在白名单: {name!r}")
    return s


def safe_ddl(fragment) -> str:
    """校验 DDL 列定义片段（如 `TEXT DEFAULT ''`）。

    与 safe_sql_fragment 的区别：允许引号包夹的默认值字面量（DDL 必需），
    但同样阻断语句分隔符与注释符。

    Args:
        fragment: 列定义片段

    Returns:
        校验通过的片段

    Raises:
        ValueError: 含不安全字符或注释符
    """
    s = str(fragment)
    if not _DDL_RE.match(s) or "--" in s or "/*" in s or ";" in s:
        raise ValueError(f"DDL 片段含不安全内容: {fragment!r}")
    return s


def safe_placeholders(count) -> str:
    """生成 count 个 `?` 占位符（逗号分隔），用于 IN (...) 等场景。

    命名带 safe_ 前缀以避免与调用点的同名局部变量冲突。

    Args:
        count: 占位符个数（整数或可转 int 的值）

    Returns:
        形如 `?,?,?` 的字符串
    """
    n = int(count)
    if n < 0:
        raise ValueError(f"占位符数量非法: {count!r}")
    return ",".join("?" * n)


def safe_set_clause(columns, allowed=None, raw=None) -> str:
    """生成 UPDATE 的 SET 子句，列名逐个校验。

    Args:
        columns: 列名可迭代对象
        allowed: 可选列名白名单
        raw: 可选 {列名: 字面量右值}，命中时以字面量写入（如 CURRENT_TIMESTAMP）

    Returns:
        形如 `content = ?, updated_at = CURRENT_TIMESTAMP` 的字符串

    Raises:
        ValueError: 出现非法或非白名单列名
    """
    raw = raw or {}
    parts = []
    for c in columns:
        col = safe_ident(c, allowed)
        parts.append(f"{col}={raw[col]}" if col in raw else f"{col} = ?")
    return ", ".join(parts)


def safe_where_clause(fragments, joiner=" AND ", wrap=False) -> str:
    """校验并拼接 WHERE 片段（仅允许「标识符 运算符 ?」或「标识符 IS NULL」）。

    值一律以 `?` 占位，故拼接结果不含用户数据。

    Args:
        fragments: 条件片段可迭代对象（空则返回 `1=1`，保证语句合法）
        joiner: 连接符（如 ` AND ` / ` OR `）
        wrap: 是否给每个片段加括号（多条件混用 AND/OR 时防止优先级歧义）

    Returns:
        以 joiner 连接的 WHERE 子句（不含 WHERE 关键字）
    """
    parts = []
    for f in fragments:
        s = str(f).strip()
        if (_UNSAFE_SQL_RE.search(s)
                or not (_WHERE_FRAG_RE.match(s) or _WHERE_NULL_RE.match(s)
                        or _WHERE_IN_RE.match(s))):
            raise ValueError(
                f"非法 WHERE 片段: {f!r}（仅允许『列 运算符 值』，值须为 ? 或字面量）"
            )
        parts.append(f"({s})" if wrap else s)
    return joiner.join(parts) if parts else "1=1"


def safe_sql_fragment(fragment) -> str:
    """校验 SQL 片段仅含标识符 / 空白 / 逗号 / 括号 / 星号等安全字符。

    用于迁移等场景中「由 schema 推导出的」列清单（可能含 CAST(...) AS col），
    阻断分号、引号、注释符等可用于注入的字符。

    Args:
        fragment: 待校验片段

    Returns:
        校验通过的片段

    Raises:
        ValueError: 含不安全字符
    """
    s = str(fragment)
    if not _FRAGMENT_RE.match(s):
        raise ValueError(f"SQL 片段含不安全字符: {fragment!r}")
    return s
