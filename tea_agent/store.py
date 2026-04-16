"""
存储模块
使用 SQLite 存储聊天历史、主题和 Agent 循环详情
"""

import sqlite3
import json
from typing import Dict, Optional, List
from datetime import datetime


class Storage:
    def __init__(self, db_path="chat_history.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS topics (
                topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                create_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_update_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                user_msg TEXT NOT NULL,
                ai_msg TEXT NOT NULL,
                is_func_calling INTEGER DEFAULT 0,
                stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
            )
        ''')
        # NOTE: 2026-04-16, self-evolved by TeaAgent --- Agent 循环期间的详细请求/响应记录
        c.execute('''
            CREATE TABLE IF NOT EXISTS agent_rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                round_num INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_call_id TEXT,
                stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        ''')
        self.conn.commit()
        c.close()

    def create_topic(self, title: str) -> int:
        c = self.conn.cursor()
        c.execute('INSERT INTO topics (title) VALUES (?)', (title,))
        self.conn.commit()
        tid = c.lastrowid
        c.close()
        return tid

    def update_topic_active(self, topic_id: int):
        c = self.conn.cursor()
        c.execute(
            'UPDATE topics SET last_update_stamp = CURRENT_TIMESTAMP WHERE topic_id = ?',
            (topic_id,),
        )
        self.conn.commit()
        c.close()

    def list_topics(self) -> List[Dict]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM topics ORDER BY last_update_stamp DESC')
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def save_msg(self, topic_id: int, user_msg: str, ai_msg: str, is_func: bool) -> int:
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO conversations (topic_id, user_msg, ai_msg, is_func_calling)
            VALUES (?, ?, ?, ?)
        ''', (topic_id, user_msg, ai_msg, 1 if is_func else 0))
        conv_id = c.lastrowid
        self.conn.commit()
        c.close()
        self.update_topic_active(topic_id)
        return conv_id

    def save_agent_round(
        self,
        conversation_id: int,
        round_num: int,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None,
    ):
        """保存 Agent 循环中的一轮请求/响应"""
        tc_json = json.dumps(
            tool_calls, ensure_ascii=False) if tool_calls else None
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO agent_rounds (conversation_id, round_num, role, content, tool_calls, tool_call_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (conversation_id, round_num, role, content, tc_json, tool_call_id))
        self.conn.commit()
        c.close()

    def get_conversations(self, topic_id: int) -> List[Dict]:
        c = self.conn.cursor()
        c.execute(
            'SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp ASC', (topic_id,))
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def get_topic(self, topic_id: int) -> Optional[Dict]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM topics WHERE topic_id = ?', (topic_id,))
        r = c.fetchone()
        c.close()
        return dict(r) if r else None

    def get_agent_rounds(self, conversation_id: int) -> List[Dict]:
        """获取某个对话的所有 Agent 循环记录"""
        c = self.conn.cursor()
        c.execute(
            'SELECT * FROM agent_rounds WHERE conversation_id = ? ORDER BY id ASC',
            (conversation_id,),
        )
        rows = c.fetchall()
        c.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get('tool_calls'):
                d['tool_calls'] = json.loads(d['tool_calls'])
            result.append(d)
        return result
