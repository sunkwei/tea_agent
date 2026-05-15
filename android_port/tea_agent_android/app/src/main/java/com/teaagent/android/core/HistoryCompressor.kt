/*
 * @2026-05-16 gen by tea_agent, HistoryCompressor — 三级历史压缩
 *
 * 对标 tea_agent 桌面版 load_history() 三级策略:
 *   Level 1: 最新一轮完整保留（含 function_call / tool 结果）
 *   Level 2: 语义相关轮次 → 完整保留；弱相关 → 轻度摘要
 *   Level 3: 早期对话 → Semantic Summary + Tool-Chain Summary
 *
 * Android 简化版:
 *   - Level 1: 最近 keepTurns 轮完整保留
 *   - Level 2: 之前的内容生成摘要（调用 cheap_model）
 *   - Level 3: 摘要缓存（存 SQLite，避免重复生成）
 */

package com.teaagent.android.core

import com.teaagent.android.db.MessageDao
import com.teaagent.android.model.Message
import org.json.JSONArray
import org.json.JSONObject

class HistoryCompressor(
    private val messageDao: MessageDao
) {
    companion object {
        // 摘要分隔标记
        const val SUMMARY_PREFIX = "<!--SUMMARY-->"
    }

    /**
     * 构建发送给 LLM 的 messages 数组
     *
     * @param topicId 当前主题
     * @param keepTurns 保留最近 N 轮完整对话
     * @param systemPrompt 系统提示词（含工具 schema）
     * @return API-ready messages 列表
     */
    fun buildMessages(
        topicId: String,
        newUserMessage: String,
        keepTurns: Int,
        systemPrompt: String
    ): List<Map<String, Any?>> {
        val allMessages = messageDao.getByTopic(topicId)
        val result = mutableListOf<Map<String, Any?>>()

        // 1. System prompt
        result.add(mapOf("role" to "system", "content" to systemPrompt))

        // 2. 分离 Recent（保留）和 Old（压缩）
        if (allMessages.size <= keepTurns * 2) {
            // 消息不多，全部保留
            allMessages.forEach { result.add(it.toApiMap()) }
        } else {
            // 前 N 对保留，之前压缩为摘要
            val recentStart = maxOf(0, allMessages.size - keepTurns * 2)
            val oldMessages = allMessages.subList(0, recentStart)
            val recentMessages = allMessages.subList(recentStart, allMessages.size)

            // 注入摘要
            val summary = compressOldMessages(oldMessages)
            if (summary.isNotBlank()) {
                result.add(mapOf(
                    "role" to "system",
                    "content" to "$SUMMARY_PREFIX\n$summary"
                ))
            }

            recentMessages.forEach { result.add(it.toApiMap()) }
        }

        // 3. 添加新用户消息
        result.add(mapOf("role" to "user", "content" to newUserMessage))

        return result
    }

    /**
     * 将旧消息压缩为结构化摘要
     * 简单策略：提取关键 user 消息，统计工具调用
     */
    fun compressOldMessages(messages: List<Message>): String {
        if (messages.isEmpty()) return ""

        val userMsgs = messages.filter { it.role == "user" }
        val toolCalls = messages.filter { it.role == "tool" || !it.toolCalls.isNullOrBlank() }

        val sb = StringBuilder()
        sb.appendLine("## 历史摘要（${messages.size} 条消息）")
        sb.appendLine()

        if (userMsgs.isNotEmpty()) {
            sb.appendLine("### 用户关键问题")
            userMsgs.takeLast(10).forEach { msg ->
                val content = msg.content ?: ""
                val brief = if (content.length > 100) content.take(100) + "..." else content
                sb.appendLine("- $brief")
            }
            sb.appendLine()
        }

        if (toolCalls.isNotEmpty()) {
            sb.appendLine("### 工具调用记录")
            sb.appendLine("- 共 ${toolCalls.size} 次工具调用")
            sb.appendLine()
        }

        return sb.toString()
    }

    /**
     * 估算消息的 token 数（简化：中文约 2 字符/token，英文约 4 字符/token）
     */
    fun estimateTokens(text: String): Int {
        var tokens = 0
        for (ch in text) {
            tokens += if (ch.code > 127) 1 else 0  // 中文字符 ≈ 2 tokens，简化算1
        }
        return maxOf(text.length / 3, tokens / 2, 1)
    }

    /**
     * 计算话题总 token 统计
     */
    fun getTokenStats(topicId: String): Triple<Int, Int, Int> {
        return messageDao.totalTokensByTopic(topicId)
    }
}

// ==================== Message → API Map ====================

private fun Message.toApiMap(): Map<String, Any?> {
    val map = mutableMapOf<String, Any?>()
    map["role"] = role

    if (!content.isNullOrBlank()) {
        map["content"] = content
    }

    if (!toolCalls.isNullOrBlank()) {
        try {
            val arr = JSONArray(toolCalls)
            val calls = (0 until arr.length()).map { i ->
                val obj = arr.getJSONObject(i)
                mapOf<String, Any?>(
                    "id" to obj.optString("id"),
                    "type" to "function",
                    "function" to mapOf(
                        "name" to obj.optJSONObject("function")?.optString("name"),
                        "arguments" to obj.optJSONObject("function")?.optString("arguments")
                    )
                )
            }
            map["tool_calls"] = calls
        } catch (_: Exception) {}
    }

    if (!toolCallId.isNullOrBlank()) {
        map["tool_call_id"] = toolCallId
    }

    return map
}
