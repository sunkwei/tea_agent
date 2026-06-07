/*
 * @2026-06-04 gen by tea_agent, MemoryManager — 长期记忆管理器
 *
 * 对标桌面版 memory.py 的 MemoryManager。
 * 使用 SQLite 持久化记忆，支持关键词搜索和自动提取。
 *
 * 记忆表结构：
 *   memories(id TEXT, content TEXT, category TEXT, tags TEXT,
 *            importance INTEGER, created_at INTEGER, accessed_at INTEGER)
 */

package com.teaagent.android.core

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * 长期记忆管理器。
 *
 * 管理 Agent 的长期记忆，支持：
 * - 添加记忆（add）
 * - 搜索记忆（search）
 * - 列出最近记忆（list）
 * - 记忆重要性标记
 * - 关键词匹配（简单语义搜索）
 */
class MemoryManager(private val db: SQLiteDatabase) {

    companion object {
        private const val TAG = "MemoryManager"
        private const val TABLE_MEMORIES = "memories"
        private const val TABLE_VERSION = 1

        // 记忆表建表 SQL
        val CREATE_TABLE_SQL = """
            CREATE TABLE IF NOT EXISTS $TABLE_MEMORIES (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT DEFAULT '',
                importance INTEGER DEFAULT 3,
                created_at INTEGER NOT NULL,
                accessed_at INTEGER NOT NULL
            )
        """.trimIndent()

        val CREATE_INDEX_SQL = """
            CREATE INDEX IF NOT EXISTS idx_memories_category ON $TABLE_MEMORIES(category)
        """.trimIndent()
    }

    init {
        // 确保表存在
        db.execSQL(CREATE_TABLE_SQL)
        db.execSQL(CREATE_INDEX_SQL)
        Log.d(TAG, "MemoryManager initialized")
    }

    // ==================== CRUD ====================

    /**
     * 添加一条记忆。
     *
     * @param content 记忆内容（精简摘要）
     * @param category 分类
     * @param tags 逗号分隔标签
     * @param importance 重要度 1-5
     * @return 记忆 ID
     */
    fun add(
        content: String,
        category: String = "general",
        tags: String = "",
        importance: Int = 3
    ): String {
        val id = UUID.randomUUID().toString()
        val now = System.currentTimeMillis()

        val cv = ContentValues().apply {
            put("id", id)
            put("content", content)
            put("category", category)
            put("tags", tags)
            put("importance", importance.coerceIn(1, 5))
            put("created_at", now)
            put("accessed_at", now)
        }

        db.insertWithOnConflict(TABLE_MEMORIES, null, cv, SQLiteDatabase.CONFLICT_REPLACE)
        Log.d(TAG, "Memory added: $id ($category, imp=$importance)")
        return id
    }

    /**
     * 搜索记忆（关键词匹配）。
     * 按相关度和重要度排序。
     *
     * @param query 搜索关键词
     * @param limit 返回数量上限
     * @param minImportance 最低重要度
     * @return 匹配的记忆列表
     */
    fun search(
        query: String,
        limit: Int = 10,
        minImportance: Int = 0
    ): List<MemoryItem> {
        val results = mutableListOf<MemoryItem>()

        // 构建查询条件
        val whereClauses = mutableListOf<String>()
        val whereArgs = mutableListOf<String>()

        if (minImportance > 0) {
            whereClauses.add("importance >= ?")
            whereArgs.add(minImportance.toString())
        }

        if (query.isNotBlank()) {
            // 关键词搜索：content LIKE %keyword%
            val keywords = query.split(Regex("[\\s,，]+")).filter { it.isNotBlank() }
            val likeClauses = keywords.map { "content LIKE ?" }
            if (likeClauses.isNotEmpty()) {
                whereClauses.add("(${likeClauses.joinToString(" OR ")})")
                whereArgs.addAll(keywords.map { "%$it%" })
            }
        }

        val whereStr = if (whereClauses.isNotEmpty()) whereClauses.joinToString(" AND ") else null
        val args = if (whereArgs.isNotEmpty()) whereArgs.toTypedArray() else null

        db.query(
            TABLE_MEMORIES, null, whereStr, args,
            null, null, "importance DESC, accessed_at DESC",
            limit.toString()
        ).use { cursor ->
            while (cursor.moveToNext()) {
                results.add(MemoryItem(
                    id = cursor.getString(cursor.getColumnIndexOrThrow("id")),
                    content = cursor.getString(cursor.getColumnIndexOrThrow("content")),
                    category = cursor.getString(cursor.getColumnIndexOrThrow("category")),
                    tags = cursor.getString(cursor.getColumnIndexOrThrow("tags")),
                    importance = cursor.getInt(cursor.getColumnIndexOrThrow("importance")),
                    createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at")),
                    accessedAt = cursor.getLong(cursor.getColumnIndexOrThrow("accessed_at"))
                ))
            }
        }

        // 更新访问时间
        for (item in results) {
            val cv = ContentValues().apply { put("accessed_at", System.currentTimeMillis()) }
            db.update(TABLE_MEMORIES, cv, "id=?", arrayOf(item.id))
        }

        return results
    }

    /**
     * 列出最近记忆。
     */
    fun list(limit: Int = 20, category: String? = null): List<MemoryItem> {
        val results = mutableListOf<MemoryItem>()

        val where = if (category != null) "category=?" else null
        val args = if (category != null) arrayOf(category) else null

        db.query(TABLE_MEMORIES, null, where, args, null, null,
            "created_at DESC", limit.toString()).use { cursor ->
            while (cursor.moveToNext()) {
                results.add(MemoryItem(
                    id = cursor.getString(cursor.getColumnIndexOrThrow("id")),
                    content = cursor.getString(cursor.getColumnIndexOrThrow("content")),
                    category = cursor.getString(cursor.getColumnIndexOrThrow("category")),
                    tags = cursor.getString(cursor.getColumnIndexOrThrow("tags")),
                    importance = cursor.getInt(cursor.getColumnIndexOrThrow("importance")),
                    createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at")),
                    accessedAt = cursor.getLong(cursor.getColumnIndexOrThrow("accessed_at"))
                ))
            }
        }

        return results
    }

    /**
     * 获取记忆统计信息。
     */
    fun stats(): String {
        var count = 0
        var maxImp = 0
        val categories = mutableMapOf<String, Int>()

        db.rawQuery("SELECT COUNT(*), MAX(importance) FROM $TABLE_MEMORIES", null).use { c ->
            if (c.moveToFirst()) {
                count = c.getInt(0); maxImp = c.getInt(1)
            }
        }

        db.rawQuery("SELECT category, COUNT(*) FROM $TABLE_MEMORIES GROUP BY category", null).use { c ->
            while (c.moveToNext()) {
                categories[c.getString(0)] = c.getInt(1)
            }
        }

        return JSONObject().apply {
            put("total", count)
            put("max_importance", maxImp)
            put("categories", JSONObject(categories as Map<String, Any>))
        }.toString()
    }

    /**
     * 删除记忆。
     */
    fun delete(id: String): Boolean {
        return db.delete(TABLE_MEMORIES, "id=?", arrayOf(id)) > 0
    }

    /**
     * 清除所有记忆。
     */
    fun clear() {
        db.delete(TABLE_MEMORIES, null, null)
        Log.w(TAG, "All memories cleared")
    }

    /**
     * 从对话内容中提取关键信息并添加为记忆。
     *
     * @param conversation 对话文本
     * @return 提取的记忆列表
     */
    fun autoExtract(conversation: String): List<String> {
        val extracted = mutableListOf<String>()

        // 简单提取规则：长句子 → 如果包含关键信息词，作为记忆
        // 更复杂的提取需要 LLM 辅助（未来版本）
        val keyPatterns = listOf(
            Regex("我喜欢\\S+"), Regex("我需要\\S+"),
            Regex("我用\\S+"), Regex("我是\\S+"),
            Regex("我的\\S+是\\S+"), Regex("我在用\\S+")
        )

        for (line in conversation.split("\n")) {
            for (pattern in keyPatterns) {
                val match = pattern.find(line)
                if (match != null) {
                    val id = add(match.value, category = "preference", importance = 2)
                    extracted.add(id)
                    break
                }
            }
        }

        return extracted
    }
}

/**
 * 记忆数据类
 */
data class MemoryItem(
    val id: String,
    val content: String,
    val category: String,
    val tags: String,
    val importance: Int,
    val createdAt: Long,
    val accessedAt: Long
)
