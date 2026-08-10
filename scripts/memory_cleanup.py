# -*- coding: utf-8 -*-
"""记忆库清理：软删重复/过时 + 提权关键项（一次性脚本）"""
import sqlite3, sys, os

DB = os.path.expanduser("~/.tea_agent/ds_flash.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ── 1. 软删清单（重复/过时/琐碎，保留 canonical） ──
SOFT_DELETE = [
    # OS 信息注入 — 已被 #2b50bf04 重构取代
    "ddb4f924-0175-4adb-9c80-6ebd417052f3",  # pipeline position 15（旧方案）
    "bfab4e65-7ec4-42d0-b3c7-4a7bf4dca7bd",  # pipeline 注入（旧方案）
    "b56dd852-a078-41c2-8f90-71a4fa07c584",  # _build_api_message 冗余待改（已完成）
    "a922fa0a-0349-4cec-ae7f-1f659609e109",  # 冗余分析结论（与上矛盾）
    # 过时工具数量/列表
    "eb683fb4-f77c-4c84-b614-5762553e386a",  # 只有4个基础工具（过时）
    "707ed41d-531f-4419-8f20-89603835860f",  # 核心工具列表（与#2618492c重复）
    "9c3e200a-367c-4058-9b90-cbff82a8a74b",  # 55个工具统计（过时）
    "a7a15f25-e052-42d0-805e-1d36d074e3a3",  # toolkit_save/reload（与#ea0fea84重复）
    # 重复条目
    "94e9ea20-fe65-4ba5-aea7-4a027f4f424c",  # LSP偏好（与#e1e522cc重复）
    "91c5052a-60c0-457b-8b32-6ffc7f16b2b5",  # watchdog删除（与#55ee70fa重复）
    "50246521-dc79-4bdd-9344-a80e68aae59c",  # TUI 500ms（与#832ac636重复）
    "a775dbe5-e09f-4f1b-be2a-0d891566a282",  # TUI实时显示reminder（已完成）
    "3e975d6e-ab55-46b2-9020-03a194dcc360",  # 先读文件（与#b5d8905b重复）
    "39985370-8b4d-45aa-9786-09c43375182d",  # 工具名检查（与#74a9cc4c重复）
    "74a9cc4c-37e8-46b5-b97c-246e7807c6de",  # 工具调用失败原因（重复）
    "22ad0789-ec80-460e-afcf-7f74f2e1cb28",  # 文件存在检查（与#71ff07cf重复）
    "71ff07cf-0847-487e-81a5-507695b4ca84",  # 命令前检查文件（重复）
    # 一次性事件/过时状态
    "e166a2ea-4a99-4143-b6b9-568f057d2ee9",  # 提交dfa0be1记录
    "bbcc0ccc-bf95-4d20-8f6a-417b9aeb4ef3",  # Git状态快照（已变化）
    "1b2a4871-8f05-43b6-bf47-8b79caeb9e9b",  # 时间矛盾记录（无价值）
    "de11db0a-9a70-46cc-8d02-6b0b8b23b33f",  # toolkit_mgrt感兴趣（错误工具名）
    "40366838-f084-4890-82e1-66bbb42489bd",  # KV Cache排查（一次性）
    "883c0eb8-569a-466d-8577-613f1aec2c22",  # 行号偏移损坏（一次性）
    "047015b9-1171-4fe0-831b-433daf59f904",  # 搜索新闻失败（一次性）
    "0eeacbe5-14f9-47c9-844e-8e386e1d5598",  # 7次调用完成（一次性）
    "e17b82a3-27aa-4f92-9d38-74ef921d2d22",  # session pipeline搜索（一次性）
    "dba912ed-1861-4791-ad63-6bb996eb2472",  # write_b64失败（过时）
    # 泛泛/系统提示已覆盖
    "058a629b-1b7f-48f0-8237-ef572bc6665e",  # 多次调用暂停（系统提示已有）
    "0f84331d-1082-4293-8701-6c5ae1ca5f6e",  # 工具可用性验证（系统提示已有）
    "87592c06-1809-4c58-a4d8-723433406c06",  # 修改需明确范围（泛泛）
    "b8f3bb38-6872-4d1d-989a-64accca2ff1a",  # exec核心工具（泛泛）
    "198abdbc-bce6-4f23-80f8-f0ee9f6f78b0",  # exec耗时监控（泛泛）
    "c4c18243-095b-4ffb-afd1-ae5e26aa8163",  # TUI前端渲染（泛泛）
    # exec/git参数问题 — 合并到 #14fca4b1 canonical
    "38a9e8e7-351f-4e6c-ac4c-63dc1976bc57",  # Windows PATH git
    "8971053f-18a3-4778-976e-222e97381529",  # Windows 路径失败
    "92018d44-b7e6-4433-b43c-b9dabde87e5c",  # git参数引号
]

# ── 2. 提权清单： (id, 目标priority) ──
PROMOTE = [
    ("56b09d18-496a-4a5f-98e4-240a50b9bdac", 1),  # git commit author → HIGH
    ("c95d0bb1-9a48-4b38-b910-290b70de78fe", 1),  # DeepSeek V4 Pro 配置 → HIGH
    ("ea0fea84-c434-47e7-bc16-382bf9e5ee42", 1),  # 创建新工具流程 → HIGH
    ("9791158b-1cc7-4340-98a9-a090a8fe08a6", 1),  # 修改后立即回复 → HIGH
    ("70f73392-940c-451c-815e-41b0b4446726", 1),  # .bak备份+测试验证 → HIGH
    ("a0ce2ee0-a95e-4c4f-98a1-727e3ab3e7e6", 1),  # 指令准确性敏感 → HIGH
    ("c38e11ca-2060-46d4-b411-8350110fe5e3", 1),  # 立即修改不空谈 → HIGH
    ("2b50bf04-618c-4487-9da4-48186e99fa24", 1),  # OS注入重构 → HIGH
    ("b5d8905b-4278-4f55-8016-a623c15ae1e1", 2),  # 先读文件分析 → MEDIUM
    ("72711093-747d-4b8d-9ce2-db3245c2a917", 2),  # 不同OS不同工具 → MEDIUM
    ("6c1d1c8e-f17a-4896-85bf-05fcb071d8b2", 2),  # TUI max_iterations → MEDIUM
    ("832ac636-c69f-455a-b17b-bee4972ef418", 2),  # TUI 500ms → MEDIUM
    ("4ec9ae29-9a10-4aa2-97d5-5ba8901ecc16", 2),  # 远程仓库 → MEDIUM
    ("0130bf2c-35f0-49a8-b702-643f84866e0c", 2),  # git push all → MEDIUM
    ("d669ebff-2c11-4277-b976-c8ce48551215", 2),  # TUI THINK修复 → MEDIUM
    ("9b3f61a6-b553-4482-a6ca-bcb4ecedb0c2", 2),  # 工具执行提示语 → MEDIUM
    ("e1e522cc-0dc7-47f5-bc11-2989606a3c85", 2),  # LSP参与验证 → MEDIUM
    ("a2d3690a-c10a-4422-b298-dae821407697", 2),  # 续命对话框轮数 → MEDIUM
    ("55ee70fa-eba9-4270-8f37-cbc5896867c4", 2),  # watchdog删除决策 → MEDIUM
    ("1115156b-b738-4343-97f6-b289070bac57", 2),  # Skills移除决策 → MEDIUM
    ("ff27b9e6-3947-49a0-a4aa-6dfb1e2655de", 2),  # 公网IP工具 → MEDIUM
    ("b28613ef-0cc8-42fb-8b2a-905b5f7c6d2d", 2),  # master→my分支 → MEDIUM
]

# ── 执行 ──
deleted = 0
for mid in SOFT_DELETE:
    cur = c.execute("UPDATE memories SET is_active=0, updated_at=datetime('now','localtime') WHERE id=?", (mid,))
    deleted += cur.rowcount

promoted = 0
for mid, prio in PROMOTE:
    cur = c.execute("UPDATE memories SET priority=?, updated_at=datetime('now','localtime') WHERE id=?", (prio, mid))
    promoted += cur.rowcount

conn.commit()

# ── 统计 ──
c.execute("SELECT COUNT(*) FROM memories WHERE is_active=1")
total = c.fetchone()[0]
c.execute("SELECT priority, COUNT(*) FROM memories WHERE is_active=1 GROUP BY priority")
by_prio = {r[0]: r[1] for r in c.fetchall()}
c.execute("SELECT category, COUNT(*) FROM memories WHERE is_active=1 GROUP BY category")
by_cat = {r[0]: r[1] for r in c.fetchall()}
c.close(); conn.close()

print(f"软删: {deleted} 条 | 提权: {promoted} 条")
print(f"剩余活跃: {total} 条")
print(f"按优先级: {by_prio}")
print(f"按分类: {by_cat}")
