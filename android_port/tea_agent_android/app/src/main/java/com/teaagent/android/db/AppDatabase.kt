/*
 * @2026-05-16 gen by tea_agent, SQLite 数据库 — 主题/消息/工具/配置
 *
 * 表结构:
 *   topics(id, title, created_at, updated_at)
 *   messages(id, topic_id, role, content, tool_calls, tool_call_id,
 *            token_count, prompt_tokens, completion_tokens, created_at)
 *   tools(id, name, meta, js_code, created_at, updated_at)
 *   config(key, value)
 */

package com.teaagent.android.db

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

class AppDatabase(context: Context) :
    SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    companion object {
        const val DB_NAME = "tea_agent.db"
        const val DB_VERSION = 2

        const val TABLE_TOPICS = "topics"
        const val TABLE_MESSAGES = "messages"
        const val TABLE_TOOLS = "tools"
        const val TABLE_CONFIG = "config"
        const val TABLE_MEMORIES = "memories"
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE $TABLE_TOPICS (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                is_dead INTEGER NOT NULL DEFAULT 0
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE $TABLE_MESSAGES (
                id TEXT PRIMARY KEY,
                topic_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_call_id TEXT,
                token_count INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (topic_id) REFERENCES $TABLE_TOPICS(id)
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE $TABLE_TOOLS (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                meta TEXT,
                js_code TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE $TABLE_CONFIG (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """.trimIndent())

        // 记忆表（用于长期记忆）
        db.execSQL("""
            CREATE TABLE $TABLE_MEMORIES (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT DEFAULT '',
                importance INTEGER DEFAULT 3,
                created_at INTEGER NOT NULL,
                accessed_at INTEGER NOT NULL
            )
        """.trimIndent())

        // 索引
        db.execSQL("CREATE INDEX idx_msg_topic ON $TABLE_MESSAGES(topic_id, created_at)")
        db.execSQL("CREATE INDEX idx_tools_name ON $TABLE_TOOLS(name)")
        db.execSQL("CREATE INDEX idx_memories_cat ON $TABLE_MEMORIES(category)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE $TABLE_TOPICS ADD COLUMN is_dead INTEGER NOT NULL DEFAULT 0")
        }
    }
}
