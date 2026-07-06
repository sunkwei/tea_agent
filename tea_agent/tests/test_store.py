"""
Storage 测试套件 — 覆盖所有核心 CRUD 操作。

测试范围:
- 表结构初始化（_init_tables / _migrate）
- Topic CRUD (create / list / get / update_title / delete)
- Message CRUD (save_msg / update_msg_rounds / get_conversations)
- Memory CRUD (add / search / forget / CRITICAL FIFO)
- 周轮转保护
- 数据库备份与 .chat_history_protected
- close() / __del__
"""

import os
import time

# ============================================================
# 1. 数据库初始化
# ============================================================

class TestStorageInit:
    """数据库初始化测试"""

    def test_init_creates_db_file(self, tmp_db_path):
        """初始化应创建数据库文件"""
        from tea_agent.store import Storage

        assert not os.path.exists(tmp_db_path)
        s = Storage(db_path=tmp_db_path)
        assert os.path.exists(tmp_db_path)
        s.close()

    def test_init_creates_all_tables(self, storage):
        """初始化应创建全部表"""
        c = storage.conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in c.fetchall()}
        c.close()

        expected = {
            "_meta", "topics", "conversations", "agent_rounds",
            "topic_token_stats", "t_conv_summary", "memories",
            "system_prompts", "reflections", "config_history",
            "msg_vectors",
        }
        missing = expected - tables
        assert not missing, f"缺少表: {missing}"

    def test_init_enables_wal_mode(self, storage):
        """WAL 模式应启用"""
        c = storage.conn.execute("PRAGMA journal_mode")
        mode = c.fetchone()[0]
        assert mode.upper() == "WAL"

    def test_init_writes_week_key(self, storage):
        """应写入本周 ISO 周标识到 _meta 表"""
        c = storage.conn.execute("SELECT value FROM _meta WHERE key='week_key'")
        row = c.fetchone()
        assert row is not None
        assert row[0].startswith("20")  # ISO 周如 "2026-W18"

    def test_init_creates_protected_marker(self, storage):
        """应在数据库同目录创建 .chat_history_protected 标记文件"""
        db_dir = os.path.dirname(os.path.abspath(storage.db_path))
        marker = os.path.join(db_dir, ".chat_history_protected")
        assert os.path.exists(marker), f"保护标记文件不存在: {marker}"

    def test_reopen_same_db_no_error(self, tmp_db_path):
        """重复打开同一数据库应无错误"""
        from tea_agent.store import Storage

        s1 = Storage(db_path=tmp_db_path)
        s1.close()
        s2 = Storage(db_path=tmp_db_path)
        s2.close()


# ============================================================
# 2. Topic CRUD
# ============================================================

class TestTopicCRUD:
    """主题 CRUD 测试"""

    def test_create_topic(self, storage):
        """创建主题返回递增 ID"""
        tid1 = storage.create_topic("主题1")
        tid2 = storage.create_topic("主题2")
        assert isinstance(tid1, str) and len(tid1) > 0
        assert isinstance(tid2, str) and tid2 != tid1

    def test_get_topic(self, storage):
        """获取主题返回完整信息"""
        tid = storage.create_topic("测试主题")
        topic = storage.get_topic(tid)
        assert topic is not None
        assert topic["title"] == "测试主题"
        assert topic["topic_id"] == tid
        assert "create_stamp" in topic

    def test_get_nonexistent_topic(self, storage):
        """不存在的主题返回 None"""
        assert storage.get_topic(999) is None

    def test_list_topics(self, storage):
        """列出所有主题，按更新时间倒序"""
        storage.create_topic("A")
        storage.create_topic("B")
        storage.create_topic("C")

        topics = storage.list_topics()
        assert len(topics) == 3

    def test_update_topic_title(self, storage):
        """更新主题标题"""
        tid = storage.create_topic("旧标题")
        storage.update_topic_title(tid, "新标题")
        topic = storage.get_topic(tid)
        assert topic["title"] == "新标题"

    def test_update_topic_title_chat_room_protected(self, storage):
        """chat_room_ 前缀主题标题不可修改"""
        import uuid
        c = storage.conn.cursor()
        tid = str(uuid.uuid4())
        c.execute("INSERT INTO topics (topic_id, title) VALUES (?, 'chat_room_test')", (tid,))
        storage.conn.commit()
        c.close()

        storage.update_topic_title(tid, "修改后的标题")
        topic = storage.get_topic(tid)
        assert topic["title"] == "chat_room_test"  # 标题未被修改

    def test_delete_topic_cascade(self, storage):
        """硬删除主题应级联删除关联数据"""
        tid = storage.create_topic("待删除")
        cid = storage.save_msg(tid, "用户消息", "AI回复", False)
        storage.update_msg_rounds(cid, "最终回复", False, [{"role": "assistant", "content": "test"}])

        storage.delete_topic(tid)

        # 主题已不存在
        assert storage.get_topic(tid) is None
        # 关联的 conversation 也已删除
        convs = storage.get_conversations(tid)
        assert len(convs) == 0

    def test_update_topic_active(self, storage):
        """更新主题活跃时间"""
        tid = storage.create_topic("活跃测试")
        old_stamp = storage.get_topic(tid)["last_update_stamp"]
        time.sleep(1.1)  # SQLite CURRENT_TIMESTAMP 秒级精度，需 >=1 秒
        storage.update_topic_active(tid)
        new_stamp = storage.get_topic(tid)["last_update_stamp"]
        assert new_stamp != old_stamp


# ============================================================
# 3. Message CRUD
# ============================================================

class TestMessageCRUD:
    """消息 CRUD 测试"""

    def test_save_msg(self, storage):
        """保存消息返回递增 ID"""
        tid = storage.create_topic("消息测试")
        cid = storage.save_msg(tid, "你好", "", False)
        assert isinstance(cid, str) and len(cid) > 0

        cid2 = storage.save_msg(tid, "再见", "拜拜", True)
        assert isinstance(cid2, str) and cid2 != cid

    def test_save_msg_updates_topic_active(self, storage):
        """保存消息应自动更新主题活跃时间"""
        tid = storage.create_topic("活跃测试")
        old = storage.get_topic(tid)["last_update_stamp"]
        time.sleep(1.1)  # SQLite CURRENT_TIMESTAMP 秒级精度
        storage.save_msg(tid, "新消息", "", False)
        new = storage.get_topic(tid)["last_update_stamp"]
        assert new != old

    def test_update_msg_rounds(self, storage):
        """更新消息轮次"""
        tid = storage.create_topic("轮次测试")
        cid = storage.save_msg(tid, "问题", "", False)

        rounds = [
            {"role": "assistant", "content": "思考中", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}]},
            {"role": "tool", "content": "搜索结果...", "tool_call_id": "call_1"},
            {"role": "assistant", "content": "最终答案"},
        ]
        storage.update_msg_rounds(cid, "最终答案", True, rounds)

        convs = storage.get_conversations(tid)
        assert len(convs) == 1
        conv = convs[0]
        assert conv["is_func_calling"] == 1
        assert conv["ai_msg"] == "最终答案"
        assert conv["rounds_json_parsed"] is not None
        assert len(conv["rounds_json_parsed"]) == 3

    def test_get_conversations_default_params(self, storage):
        """get_conversations 默认参数：limit=5, include_rounds=True"""
        tid = storage.create_topic("默认参数测试")
        for i in range(10):
            cid = storage.save_msg(tid, f"msg{i}", f"reply{i}", False)
            storage.update_msg_rounds(cid, f"reply{i}", False, [{"role": "assistant", "content": f"test{i}"}])

        # 不传 limit / include_rounds → 应返回最近 5 条，含 rounds_json_parsed
        convs = storage.get_conversations(tid)
        assert len(convs) == 5
        assert convs[0]["user_msg"] == "msg5"
        assert convs[-1]["user_msg"] == "msg9"
        for c in convs:
            assert "rounds_json_parsed" in c

    def test_get_conversations_limit(self, storage):
        """get_conversations 限制返回条数"""
        tid = storage.create_topic("限制测试")
        for i in range(10):
            cid = storage.save_msg(tid, f"msg{i}", f"reply{i}", False)
            storage.update_msg_rounds(cid, f"reply{i}", False)

        # limit=3 只返回最近 3 条
        convs = storage.get_conversations(tid, limit=3)
        assert len(convs) == 3
        assert convs[-1]["user_msg"] == "msg9"

    def test_get_conversations_limit_negative(self, storage):
        """get_conversations limit=-1 返回全部对话"""
        tid = storage.create_topic("全量测试")
        for i in range(7):
            cid = storage.save_msg(tid, f"msg{i}", f"reply{i}", False)
            storage.update_msg_rounds(cid, f"reply{i}", False)

        convs = storage.get_conversations(tid, limit=-1)
        assert len(convs) == 7

    def test_get_conversations_limit_zero(self, storage):
        """get_conversations limit=0 返回全部（不限制）"""
        tid = storage.create_topic("无限测试")
        cid = storage.save_msg(tid, "msg", "reply", False)
        storage.update_msg_rounds(cid, "reply", False)

        convs = storage.get_conversations(tid, limit=0)
        assert len(convs) == 1  # limit=0 表示不限制，返回全部
    def test_get_conversations_limit_exceeds_total(self, storage):
        """get_conversations limit 大于总数时返回全部"""
        tid = storage.create_topic("超限测试")
        for i in range(3):
            cid = storage.save_msg(tid, f"msg{i}", f"reply{i}", False)
            storage.update_msg_rounds(cid, f"reply{i}", False)

        convs = storage.get_conversations(tid, limit=100)
        assert len(convs) == 3

    def test_get_conversations_lightweight(self, storage):
        """轻量模式不加载 rounds_json"""
        tid = storage.create_topic("轻量测试")
        cid = storage.save_msg(tid, "msg", "reply", False)
        storage.update_msg_rounds(cid, "reply", True, [{"role": "assistant", "content": "test"}])

        convs = storage.get_conversations(tid, include_rounds=False)
        assert len(convs) == 1
        assert "rounds_json_parsed" not in convs[0]

    def test_get_conversations_include_rounds_true(self, storage):
        """include_rounds=True 应返回 rounds_json_parsed"""
        tid = storage.create_topic("含轮次测试")
        cid = storage.save_msg(tid, "问题", "回答", True)
        rounds = [
            {"role": "assistant", "content": "思考"},
            {"role": "tool", "content": "工具结果"},
            {"role": "assistant", "content": "最终回答"},
        ]
        storage.update_msg_rounds(cid, "最终回答", True, rounds)

        convs = storage.get_conversations(tid, include_rounds=True)
        assert len(convs) == 1
        assert convs[0]["rounds_json_parsed"] is not None
        assert len(convs[0]["rounds_json_parsed"]) == 3

    def test_get_conversations_empty_topic(self, storage):
        """空主题返回空列表"""
        tid = storage.create_topic("空主题")
        convs = storage.get_conversations(tid)
        assert convs == []

    def test_get_conversations_signature_compatibility(self, storage):
        """签名兼容性：关键字参数和位置参数都能正常工作"""
        import inspect
        sig = inspect.signature(storage.get_conversations)
        params = list(sig.parameters.keys())
        # 必须有 topic_id, limit, include_rounds 三个参数
        assert "topic_id" in params
        assert "limit" in params
        assert "include_rounds" in params

        tid = storage.create_topic("签名测试")
        storage.save_msg(tid, "msg", "reply", False)

        # 位置参数
        convs1 = storage.get_conversations(tid, 1, False)
        assert len(convs1) == 1
        # 关键字参数
        convs2 = storage.get_conversations(tid, limit=1, include_rounds=False)
        assert len(convs2) == 1
        # 混合
        convs3 = storage.get_conversations(tid, limit=1, include_rounds=True)
        assert len(convs3) == 1
        assert "rounds_json_parsed" in convs3[0]

    def test_get_recent_conversations(self, storage):
        """获取最近 N 轮对话（正序）"""
        tid = storage.create_topic("最近测试")
        for i in range(5):
            cid = storage.save_msg(tid, f"msg{i}", f"reply{i}", False)
            storage.update_msg_rounds(cid, f"reply{i}", False)
            time.sleep(1.1)  # 确保每条消息时间戳不同

        recent = storage.get_recent_conversations(tid, limit=3)
        assert len(recent) == 3
        # 应为 msg2, msg3, msg4（正序）
        assert recent[0]["user_msg"] == "msg2"
        assert recent[-1]["user_msg"] == "msg4"

    def test_save_agent_round(self, storage):
        """保存 Agent 循环记录"""
        tid = storage.create_topic("round测试")
        cid = storage.save_msg(tid, "问题", "", False)

        storage.save_agent_round(cid, 1, "assistant", "思考...",
                                  tool_calls=[{"id": "t1", "type": "function", "function": {"name": "test", "arguments": "{}"}}])
        storage.save_agent_round(cid, 1, "tool", "结果", tool_call_id="t1")

        rounds = storage.get_agent_rounds(cid)
        assert len(rounds) == 2
        assert rounds[0]["role"] == "assistant"
        assert rounds[0]["tool_calls"] is not None
        assert rounds[1]["role"] == "tool"
        assert rounds[1]["tool_call_id"] == "t1"


# ============================================================
# 4. Memory CRUD
# ============================================================

class TestMemoryCRUD:
    """长期记忆 CRUD 测试"""

    def test_add_memory(self, storage):
        """添加记忆返回递增 ID"""
        mid = storage.add_memory("测试记忆内容", category="fact", importance=3)
        assert isinstance(mid, str) and len(mid) > 0

    def test_add_critical_memory(self, storage):
        """添加 CRITICAL 记忆"""
        mid = storage.add_memory("重要规则", category="instruction", priority=0, importance=5)
        assert isinstance(mid, str) and len(mid) > 0

        memories = storage.get_active_memories()
        assert len(memories) == 1
        assert memories[0]["priority"] == 0

    def test_get_active_memories_sorted(self, storage):
        """记忆按优先级排序（CRITICAL 优先）"""
        storage.add_memory("普通", priority=2)
        storage.add_memory("重要", priority=0, category="instruction")
        storage.add_memory("中等", priority=1)

        memories = storage.get_active_memories()
        assert memories[0]["priority"] == 0
        assert memories[1]["priority"] == 1
        assert memories[2]["priority"] == 2

    def test_search_memories(self, storage):
        """搜索记忆关键词"""
        storage.add_memory("Python 编码规范", tags="python,coding")
        storage.add_memory("Git 提交格式", tags="git")
        storage.add_memory("内存无关", tags="misc")

        results = storage.search_memories(query="Python")
        assert len(results) == 1
        assert "Python" in results[0]["content"]

        results = storage.search_memories(tags=["python"])
        assert len(results) == 1
        assert "Python" in results[0]["content"]

    def test_forget_memory(self, storage):
        """软删除记忆"""
        mid = storage.add_memory("待遗忘")
        storage.deactivate_memory(mid)

        memories = storage.get_active_memories()
        assert not any(m["id"] == mid for m in memories)

    def test_hard_delete_memory(self, storage):
        """硬删除记忆"""
        mid = storage.add_memory("永久删除")
        storage.delete_memory(mid)

        # 硬删除后无法再找到
        all_memories = storage.search_memories(query="永久删除")
        assert all(m["id"] != mid for m in all_memories)

    def test_critical_fifo_limit(self, storage):
        """CRITICAL 记忆超过 15 条时 FIFO 淘汰"""
        # 插入 16 条 CRITICAL 记忆
        for i in range(16):
            storage.add_memory(f"规则{i}", category="instruction", priority=0)

        active = storage.get_active_memories()
        critical = [m for m in active if m["priority"] == 0]
        # 不应超过 15 条
        assert len(critical) <= 15

    def test_expired_memory_cleanup(self, storage):
        """过期记忆自动清理"""
        storage.add_memory("过期记忆", expires_at="2000-01-01T00:00:00")

        active = storage.get_active_memories()
        assert not any("过期记忆" in (m.get("content") or "") for m in active)

    def test_get_instructions(self, storage):
        """获取指令级记忆"""
        storage.add_memory("指令1", category="instruction", priority=0)
        storage.add_memory("普通记忆", priority=2)

        instructions = storage.get_instructions()
        assert len(instructions) == 1
        assert instructions[0]["priority"] == 0

    def test_memory_stats(self, storage):
        """记忆统计"""
        storage.add_memory("A", category="fact")
        storage.add_memory("B", category="instruction", priority=0)
        storage.add_memory("C", category="preference")

        stats = storage.get_memory_stats()
        assert stats["total"] == 3
        assert stats["by_category"]["fact"] == 1
        assert stats["by_category"]["instruction"] == 1
        assert stats["by_category"]["preference"] == 1
        assert stats["by_priority"][2] == 2  # fact + preference
        assert stats["by_priority"][0] == 1  # instruction


# ============================================================
# 5. Token 统计
# ============================================================

class TestTokenStats:
    """Token 统计测试"""

    def test_add_topic_tokens(self, storage):
        """累加 topic token"""
        tid = storage.create_topic("Token 统计")

        storage.add_topic_tokens(tid, total_tokens=100, prompt_tokens=60, completion_tokens=40)
        stats = storage.get_topic_tokens(tid)
        assert stats["total_tokens"] == 100
        assert stats["total_prompt_tokens"] == 60
        assert stats["total_completion_tokens"] == 40

    def test_add_topic_tokens_accumulate(self, storage):
        """累加 token 多次应正确汇总"""
        tid = storage.create_topic("累加测试")

        storage.add_topic_tokens(tid, total_tokens=50)
        storage.add_topic_tokens(tid, total_tokens=30)
        storage.add_topic_tokens(tid, total_tokens=20)

        stats = storage.get_topic_tokens(tid)
        assert stats["total_tokens"] == 100

    def test_add_topic_tokens_with_cheap_model(self, storage):
        """便宜模型 token 统计"""
        tid = storage.create_topic("便宜模型")

        storage.add_topic_tokens(tid, cheap_tokens=200, cheap_prompt_tokens=100, cheap_completion_tokens=100)
        stats = storage.get_topic_tokens(tid)
        assert stats["total_cheap_tokens"] == 200

    def test_get_topic_tokens_default(self, storage):
        """不存在的 topic 返回默认零值"""
        stats = storage.get_topic_tokens(999)
        assert stats["total_tokens"] == 0
        assert stats["conversation_count"] == 0


# ============================================================
# 6. 摘要 CRUD
# ============================================================

class TestSummary:
    """摘要 CRUD 测试"""

    def test_update_and_get_summary(self, storage):
        """更新并获取摘要"""
        tid = storage.create_topic("摘要测试")
        storage.update_topic_summary(tid, "这是一个对话摘要", last_summarized_id=5)

        summary = storage.get_topic_summary(tid)
        assert summary == "这是一个对话摘要"

    def test_get_summary_none(self, storage):
        """无摘要返回 None"""
        tid = storage.create_topic("无摘要")
        assert storage.get_topic_summary(tid) is None

    def test_mark_as_summarized(self, storage):
        """标记对话为已摘要"""
        tid = storage.create_topic("标记测试")
        cid = storage.save_msg(tid, "msg", "reply", False)
        storage.update_msg_rounds(cid, "reply", False)

        storage.mark_as_summarized(cid)

        # 通过 get_unsummarized 验证
        unsummarized = storage.get_unsummarized_conversations(tid)
        assert not any(c["id"] == cid for c in unsummarized)


# ============================================================
# 7. 备份与保护
# ============================================================

class TestBackup:
    """备份与保护测试"""

    def test_auto_backup_creates_file(self, storage):
        """手动触发备份应创建文件"""
        storage.backup_now()

        backup_dir = os.path.join(os.path.dirname(os.path.abspath(storage.db_path)), "backup")
        assert os.path.isdir(backup_dir)
        files = [f for f in os.listdir(backup_dir) if f.startswith("chat_history_") and f.endswith(".db")]
        assert len(files) >= 1

    def test_close_no_error(self, storage):
        """close() 应无异常"""
        storage.close()
        # 多次 close 也不应报错
        storage.close()


# ============================================================
# 8. 元数据读写
# ============================================================

class TestMeta:
    """_meta 表读写测试"""

    def test_meta_set_and_get(self, storage):
        """设置和读取元数据"""
        storage._meta_set("test_key", "test_value")
        assert storage._meta_get("test_key") == "test_value"

    def test_meta_get_nonexistent(self, storage):
        """读取不存在的 key 返回 None"""
        assert storage._meta_get("no_such_key") is None
