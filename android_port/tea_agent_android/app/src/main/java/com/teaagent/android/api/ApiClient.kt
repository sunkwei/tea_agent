/*
 * @2026-05-16 gen by tea_agent, ApiClient — LLM 对话引擎（SSE + 工具调用循环）
 *
 * 对标 tea_agent 桌面版 session_api.py + agent_core.py 的 tool_loop:
 *   1. 构建 messages（system + 压缩历史 + 新用户消息）
 *   2. POST /v1/chat/completions（OpenAI 兼容，stream=true）
 *   3. 如果响应包含 tool_calls → 执行工具 → 结果追加到 messages → 回到步骤 2
 *   4. 最终文本 → 回调 onDone
 *   5. 所有消息持久化到 SQLite
 */

package com.teaagent.android.api

import android.util.Log
import com.teaagent.android.core.HistoryCompressor
import com.teaagent.android.core.ToolManager
import com.teaagent.android.db.MessageDao
import com.teaagent.android.model.AgentConfig
import com.teaagent.android.model.Message
import com.teaagent.android.model.ModelConfig
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.UUID
import java.util.concurrent.TimeUnit

class ApiClient(
    private val messageDao: MessageDao,
    private val toolManager: ToolManager,
    private val historyCompressor: HistoryCompressor
) {
    companion object {
        private const val TAG = "TeaApiClient"
        private const val TIMEOUT_SECONDS = 120L
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private var currentCall: Call? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    // ==================== Public API ====================

    data class ChatCallbacks(
        val onToken: (String) -> Unit = {},
        val onThinking: (String) -> Unit = {},
        val onToolCall: (String) -> Unit = {},  // JSON string
        val onDone: (String, Int, Int, Int) -> Unit = { _, _, _, _ -> }, // (finalText, totalTokens, promptTokens, completionTokens)
        val onError: (String) -> Unit = {}
    )

    fun chat(
        config: AgentConfig,
        topicId: String,
        userMessage: String,
        callbacks: ChatCallbacks
    ) {
        scope.launch {
            try {
                val modelCfg = config.mainModel
                val systemPrompt = buildSystemPrompt(config)

                // 构建初始 messages
                var messages = historyCompressor.buildMessages(
                    topicId, userMessage, config.keepTurns, systemPrompt
                )

                // 保存用户消息
                val userMsgId = UUID.randomUUID().toString()
                messageDao.insert(Message(
                    id = userMsgId, topicId = topicId, role = "user",
                    content = userMessage, createdAt = System.currentTimeMillis()
                ))

                // 工具调用循环
                var iteration = 0
                var finalText = ""
                var totalTokens = 0
                var totalPrompt = 0
                var totalCompletion = 0

                while (iteration < config.maxIterations) {
                    iteration++

                    val result = callLLM(modelCfg, messages, callbacks)

                    if (result.error != null) {
                        withContext(Dispatchers.Main) { callbacks.onError(result.error) }
                        return@launch
                    }

                    totalTokens += result.tokenCount
                    totalPrompt += result.promptTokens
                    totalCompletion += result.completionTokens

                    if (result.toolCalls.isNotEmpty()) {
                        // 处理工具调用
                        val assistantMsg = buildAssistantToolCallMsg(result.toolCalls, result.content)
                        messages.add(assistantMsg)

                        // 保存 assistant 消息（含 tool_calls）
                        val tcJson = JSONArray().apply {
                            result.toolCalls.forEach { put(it) }
                        }.toString()
                        messageDao.insert(Message(
                            id = UUID.randomUUID().toString(),
                            topicId = topicId, role = "assistant",
                            content = result.content, toolCalls = tcJson,
                            tokenCount = result.tokenCount,
                            promptTokens = result.promptTokens,
                            completionTokens = result.completionTokens,
                            createdAt = System.currentTimeMillis()
                        ))

                        // 执行每个工具
                        for (tc in result.toolCalls) {
                            val fnName = tc.optJSONObject("function")?.optString("name") ?: continue
                            val fnArgsStr = tc.optJSONObject("function")?.optString("arguments") ?: "{}"
                            val fnArgs = try { JSONObject(fnArgsStr) } catch (_: Exception) { JSONObject() }

                            withContext(Dispatchers.Main) {
                                callbacks.onToolCall(JSONObject().apply {
                                    put("name", fnName)
                                    put("args", fnArgsStr)
                                }.toString())
                            }

                            val toolResult = toolManager.execute(fnName, fnArgs)

                            withContext(Dispatchers.Main) {
                                callbacks.onToolCall(JSONObject().apply {
                                    put("name", fnName)
                                    put("result", toolResult)
                                }.toString())
                            }

                            // 添加 tool 结果到 messages
                            messages.add(mapOf(
                                "role" to "tool",
                                "tool_call_id" to tc.optString("id", ""),
                                "content" to toolResult
                            ))

                            // 保存 tool 消息
                            messageDao.insert(Message(
                                id = UUID.randomUUID().toString(),
                                topicId = topicId, role = "tool",
                                content = toolResult,
                                toolCallId = tc.optString("id"),
                                createdAt = System.currentTimeMillis()
                            ))
                        }
                        continue // 继续循环
                    } else {
                        // 最终文本响应
                        finalText = result.content ?: ""

                        // 保存 assistant 消息
                        messageDao.insert(Message(
                            id = UUID.randomUUID().toString(),
                            topicId = topicId, role = "assistant",
                            content = finalText,
                            tokenCount = result.tokenCount,
                            promptTokens = result.promptTokens,
                            completionTokens = result.completionTokens,
                            createdAt = System.currentTimeMillis()
                        ))

                        break
                    }
                }

                if (iteration >= config.maxIterations) {
                    finalText = "(已达到最大工具调用次数 ${config.maxIterations})"
                }

                withContext(Dispatchers.Main) {
                    callbacks.onDone(finalText, totalTokens, totalPrompt, totalCompletion)
                }

            } catch (e: CancellationException) {
                withContext(Dispatchers.Main) {
                    callbacks.onDone("", 0, 0, 0)
                }
            } catch (e: java.net.ConnectException) {
                withContext(Dispatchers.Main) {
                    callbacks.onError("连接失败：无法连接到 ${config.mainModel.apiUrl}")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Chat error", e)
                withContext(Dispatchers.Main) {
                    callbacks.onError(e.message ?: "未知错误")
                }
            }
        }
    }

    fun stop() {
        currentCall?.cancel()
        currentCall = null
    }

    fun close() {
        stop()
        scope.cancel()
    }

    // ==================== Private ====================

    data class LLMResult(
        val content: String?,
        val toolCalls: List<JSONObject>,
        val tokenCount: Int,
        val promptTokens: Int,
        val completionTokens: Int,
        val error: String?
    )

    private suspend fun callLLM(
        config: ModelConfig,
        messages: List<Map<String, Any?>>,
        callbacks: ChatCallbacks
    ): LLMResult {
        return withContext(Dispatchers.IO) {
            try {
                val url = "${config.apiUrl.trimEnd('/')}/chat/completions"

                val requestBody = JSONObject().apply {
                    put("model", config.modelName)
                    put("messages", JSONArray(messages.map { m ->
                        JSONObject(m.filterValues { it != null })
                    }))
                    put("stream", true)
                    put("max_tokens", config.maxTokens)
                    put("temperature", config.temperature.toDouble())

                    // 工具定义
                    val toolSchemas = toolManager.getToolSchemas()
                    if (toolSchemas.isNotEmpty()) {
                        put("tools", JSONArray(toolSchemas.map { schema ->
                            JSONObject().apply {
                                put("type", "function")
                                put("function", schema)
                            }
                        }))
                        put("tool_choice", "auto")
                    }
                }.toString()

                val body = requestBody.toRequestBody("application/json".toMediaType())

                val request = Request.Builder()
                    .url(url)
                    .post(body)
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .apply {
                        if (config.apiKey.isNotBlank()) {
                            header("Authorization", "Bearer ${config.apiKey}")
                        }
                    }
                    .build()

                currentCall = client.newCall(request)
                val response = currentCall!!.execute()

                if (!response.isSuccessful) {
                    return@withContext LLMResult(
                        null, emptyList(), 0, 0, 0,
                        "HTTP ${response.code}: ${response.message}"
                    )
                }

                val reader = BufferedReader(
                    InputStreamReader(response.body?.byteStream(), Charsets.UTF_8)
                )

                var contentBuilder = StringBuilder()
                var thinkingBuilder = StringBuilder()
                val toolCalls = mutableListOf<JSONObject>()
                var tokenCount = 0
                var promptTokens = 0
                var completionTokens = 0
                val toolCallAccumulator = mutableMapOf<Int, JSONObject>()
                val toolCallArgsAccumulator = mutableMapOf<Int, StringBuilder>()

                reader.useLines { lines ->
                    for (line in lines) {
                        if (!line.startsWith("data: ")) continue
                        val data = line.removePrefix("data: ").trim()
                        if (data == "[DONE]") break

                        try {
                            val json = JSONObject(data)
                            val choices = json.optJSONArray("choices") ?: continue

                            // Token 统计
                            val usage = json.optJSONObject("usage")
                            if (usage != null) {
                                tokenCount = usage.optInt("total_tokens", tokenCount)
                                promptTokens = usage.optInt("prompt_tokens", promptTokens)
                                completionTokens = usage.optInt("completion_tokens", completionTokens)
                            }

                            val delta = choices.optJSONObject(0)?.optJSONObject("delta") ?: continue

                            // 文本内容
                            val content = delta.optString("content", "")
                            if (content.isNotEmpty()) {
                                contentBuilder.append(content)
                                withContext(Dispatchers.Main) {
                                    callbacks.onToken(content)
                                }
                            }

                            // 思考过程（DeepSeek/Claude 等模型的 reasoning_content）
                            val reasoning = delta.optString("reasoning_content", "")
                            if (reasoning.isNotEmpty()) {
                                thinkingBuilder.append(reasoning)
                                withContext(Dispatchers.Main) {
                                    callbacks.onThinking(reasoning)
                                }
                            }

                            // 工具调用（delta 方式）
                            val tcArray = delta.optJSONArray("tool_calls")
                            if (tcArray != null) {
                                for (i in 0 until tcArray.length()) {
                                    val tc = tcArray.getJSONObject(i)
                                    val idx = tc.optInt("index", i)

                                    // 累积
                                    if (!toolCallAccumulator.containsKey(idx)) {
                                        toolCallAccumulator[idx] = JSONObject()
                                        toolCallArgsAccumulator[idx] = StringBuilder()
                                    }

                                    val acc = toolCallAccumulator[idx]!!
                                    val id = tc.optString("id", "")
                                    if (id.isNotEmpty()) acc.put("id", id)

                                    val fn = tc.optJSONObject("function")
                                    if (fn != null) {
                                        if (!acc.has("function")) acc.put("function", JSONObject())
                                        val fnAcc = acc.getJSONObject("function")
                                        val fnName = fn.optString("name", "")
                                        if (fnName.isNotEmpty()) fnAcc.put("name", fnName)

                                        val args = fn.optString("arguments", "")
                                        if (args.isNotEmpty()) {
                                            toolCallArgsAccumulator[idx]!!.append(args)
                                        }
                                    }
                                }
                            }
                        } catch (_: Exception) { /* skip malformed line */ }
                    }
                }

                // 最终组装工具调用
                for (idx in toolCallAccumulator.keys) {
                    val tc = toolCallAccumulator[idx]!!
                    val argsStr = toolCallArgsAccumulator[idx]?.toString() ?: "{}"
                    if (tc.has("function")) {
                        tc.getJSONObject("function").put("arguments", argsStr)
                    }
                    toolCalls.add(tc)
                }

                LLMResult(
                    content = contentBuilder.toString().ifBlank { null },
                    toolCalls = toolCalls,
                    tokenCount = tokenCount,
                    promptTokens = promptTokens,
                    completionTokens = completionTokens,
                    error = null
                )

            } catch (e: Exception) {
                Log.e(TAG, "callLLM error", e)
                LLMResult(null, emptyList(), 0, 0, 0, e.message ?: "Unknown error")
            }
        }
    }

    private fun buildSystemPrompt(config: AgentConfig): String {
        return """
你是 TeaAgent，一个运行在 Android 上的智能助手。
当前日期：${java.text.SimpleDateFormat("yyyy-MM-dd").format(java.util.Date())}

你有以下能力：
- 流式对话
- 工具调用（Function Calling）
- 代码编写和执行
- 文件操作（通过工具）

回复要求：
- 使用中文
- 简洁准确
- 代码用 Markdown 代码块
        """.trimIndent()
    }

    private fun buildAssistantToolCallMsg(
        toolCalls: List<JSONObject>,
        content: String?
    ): Map<String, Any?> {
        return mapOf(
            "role" to "assistant",
            "content" to (content ?: ""),
            "tool_calls" to toolCalls.map { tc ->
                mapOf(
                    "id" to tc.optString("id"),
                    "type" to "function",
                    "function" to mapOf(
                        "name" to tc.optJSONObject("function")?.optString("name"),
                        "arguments" to tc.optJSONObject("function")?.optString("arguments")
                    )
                )
            }
        )
    }
}
