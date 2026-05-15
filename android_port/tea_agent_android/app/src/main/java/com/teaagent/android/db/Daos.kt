/*
 * @2026-05-16 gen by tea_agent, DAO 层 — 主题/消息/工具/配置 CRUD
 */

package com.teaagent.android.db

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import com.teaagent.android.model.*

class TopicDao(private val db: SQLiteDatabase) {

    fun insert(topic: Topic) {
        db.insert(AppDatabase.TABLE_TOPICS, null, topic.toCV())
    }

    fun update(topic: Topic) {
        db.update(AppDatabase.TABLE_TOPICS, topic.toCV(), "id=?", arrayOf(topic.id))
    }

    fun delete(id: String) {
        db.delete(AppDatabase.TABLE_TOPICS, "id=?", arrayOf(id))
    }

    fun getById(id: String): Topic? {
        db.query(AppDatabase.TABLE_TOPICS, null, "id=?", arrayOf(id), null, null, null)
            .use { cursor ->
                if (cursor.moveToFirst()) return cursor.toTopic()
            }
        return null
    }

    fun listAll(): List<Topic> {
        val list = mutableListOf<Topic>()
        db.query(AppDatabase.TABLE_TOPICS, null, null, null, null, null, "updated_at DESC")
            .use { cursor ->
                while (cursor.moveToNext()) list.add(cursor.toTopic())
            }
        return list
    }
}

class MessageDao(private val db: SQLiteDatabase) {

    fun insert(msg: Message) {
        db.insert(AppDatabase.TABLE_MESSAGES, null, msg.toCV())
    }

    fun getByTopic(topicId: String, limit: Int = 100): List<Message> {
        val list = mutableListOf<Message>()
        db.query(
            AppDatabase.TABLE_MESSAGES, null,
            "topic_id=?", arrayOf(topicId),
            null, null, "created_at ASC",
            limit.toString()
        ).use { cursor ->
            while (cursor.moveToNext()) list.add(cursor.toMessage())
        }
        return list
    }

    fun getByTopicAfter(topicId: String, afterTime: Long): List<Message> {
        val list = mutableListOf<Message>()
        db.query(
            AppDatabase.TABLE_MESSAGES, null,
            "topic_id=? AND created_at>?", arrayOf(topicId, afterTime.toString()),
            null, null, "created_at ASC"
        ).use { cursor ->
            while (cursor.moveToNext()) list.add(cursor.toMessage())
        }
        return list
    }

    fun getLastNByTopic(topicId: String, n: Int): List<Message> {
        val list = mutableListOf<Message>()
        db.query(
            AppDatabase.TABLE_MESSAGES, null,
            "topic_id=?", arrayOf(topicId),
            null, null, "created_at DESC",
            n.toString()
        ).use { cursor ->
            while (cursor.moveToNext()) list.add(cursor.toMessage())
        }
        return list.reversed()
    }

    fun deleteByTopic(topicId: String) {
        db.delete(AppDatabase.TABLE_MESSAGES, "topic_id=?", arrayOf(topicId))
    }

    fun totalTokensByTopic(topicId: String): Triple<Int, Int, Int> {
        var total = 0; var prompt = 0; var comp = 0
        db.rawQuery(
            "SELECT SUM(token_count), SUM(prompt_tokens), SUM(completion_tokens) FROM ${AppDatabase.TABLE_MESSAGES} WHERE topic_id=?",
            arrayOf(topicId)
        ).use { cursor ->
            if (cursor.moveToFirst()) {
                total = cursor.getInt(0)
                prompt = cursor.getInt(1)
                comp = cursor.getInt(2)
            }
        }
        return Triple(total, prompt, comp)
    }
}

class ToolDao(private val db: SQLiteDatabase) {

    fun insert(tool: Tool) {
        db.insert(AppDatabase.TABLE_TOOLS, null, tool.toCV())
    }

    fun update(tool: Tool) {
        db.update(AppDatabase.TABLE_TOOLS, tool.toCV(), "name=?", arrayOf(tool.name))
    }

    fun delete(name: String) {
        db.delete(AppDatabase.TABLE_TOOLS, "name=?", arrayOf(name))
    }

    fun getByName(name: String): Tool? {
        db.query(AppDatabase.TABLE_TOOLS, null, "name=?", arrayOf(name), null, null, null)
            .use { cursor ->
                if (cursor.moveToFirst()) return cursor.toTool()
            }
        return null
    }

    fun listAll(): List<Tool> {
        val list = mutableListOf<Tool>()
        db.query(AppDatabase.TABLE_TOOLS, null, null, null, null, null, "name ASC")
            .use { cursor ->
                while (cursor.moveToNext()) list.add(cursor.toTool())
            }
        return list
    }

    fun count(): Int {
        db.rawQuery("SELECT COUNT(*) FROM ${AppDatabase.TABLE_TOOLS}", null)
            .use { cursor ->
                if (cursor.moveToFirst()) return cursor.getInt(0)
            }
        return 0
    }
}

class ConfigDao(private val db: SQLiteDatabase) {

    fun get(key: String, default: String = ""): String {
        db.query(AppDatabase.TABLE_CONFIG, arrayOf("value"), "key=?", arrayOf(key), null, null, null)
            .use { cursor ->
                if (cursor.moveToFirst()) return cursor.getString(0)
            }
        return default
    }

    fun set(key: String, value: String) {
        val cv = ContentValues().apply {
            put("key", key)
            put("value", value)
        }
        db.insertWithOnConflict(AppDatabase.TABLE_CONFIG, null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun getAll(): Map<String, String> {
        val map = mutableMapOf<String, String>()
        db.query(AppDatabase.TABLE_CONFIG, null, null, null, null, null, null)
            .use { cursor ->
                while (cursor.moveToNext()) {
                    map[cursor.getString(0)] = cursor.getString(1)
                }
            }
        return map
    }
}

// ==================== Extensions ====================

private fun Topic.toCV() = ContentValues().apply {
    put("id", id); put("title", title)
    put("created_at", createdAt); put("updated_at", updatedAt)
}

private fun Message.toCV() = ContentValues().apply {
    put("id", id); put("topic_id", topicId)
    put("role", role); put("content", content)
    put("tool_calls", toolCalls); put("tool_call_id", toolCallId)
    put("token_count", tokenCount); put("prompt_tokens", promptTokens)
    put("completion_tokens", completionTokens); put("created_at", createdAt)
}

private fun Tool.toCV() = ContentValues().apply {
    put("id", id); put("name", name); put("meta", meta)
    put("js_code", jsCode); put("created_at", createdAt); put("updated_at", updatedAt)
}

private fun android.database.Cursor.toTopic() = Topic(
    id = getString(getColumnIndexOrThrow("id")),
    title = getString(getColumnIndexOrThrow("title")),
    createdAt = getLong(getColumnIndexOrThrow("created_at")),
    updatedAt = getLong(getColumnIndexOrThrow("updated_at"))
)

private fun android.database.Cursor.toMessage() = Message(
    id = getString(getColumnIndexOrThrow("id")),
    topicId = getString(getColumnIndexOrThrow("topic_id")),
    role = getString(getColumnIndexOrThrow("role")),
    content = getString(getColumnIndexOrThrow("content")),
    toolCalls = getString(getColumnIndexOrThrow("tool_calls")),
    toolCallId = getString(getColumnIndexOrThrow("tool_call_id")),
    tokenCount = getInt(getColumnIndexOrThrow("token_count")),
    promptTokens = getInt(getColumnIndexOrThrow("prompt_tokens")),
    completionTokens = getInt(getColumnIndexOrThrow("completion_tokens")),
    createdAt = getLong(getColumnIndexOrThrow("created_at"))
)

private fun android.database.Cursor.toTool() = Tool(
    id = getString(getColumnIndexOrThrow("id")),
    name = getString(getColumnIndexOrThrow("name")),
    meta = getString(getColumnIndexOrThrow("meta")),
    jsCode = getString(getColumnIndexOrThrow("js_code")),
    createdAt = getLong(getColumnIndexOrThrow("created_at")),
    updatedAt = getLong(getColumnIndexOrThrow("updated_at"))
)
