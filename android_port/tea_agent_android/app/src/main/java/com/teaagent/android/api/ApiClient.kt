/*
 * @2026-06-04 gen by tea_agent, ApiClient — LLM 对话引擎（SSE + 工具调用循环）
 * @2026-06-04 refactor: 集成 ToolComponent + SessionPipeline 架构
 *
 * 对标 tea_agent 桌面版 session_api.py + agent_core.py 的 tool_loop:
 *   1. 构建 messages（system + 压缩历史 + 新用户消息）
 *   2. POST /v1/chat/completions（OpenAI 兼容，stream=true）
 *   3. 如果响应包含 tool_calls → 执行工具 → 结果追加到 messages → 回到步骤 2
 *   4. 最终文本 → 回调 onDone
 *   5. 所有消息持久化到 SQLite
 *
 * 架构升级：
 *   - 使用 ToolComponent 替代旧 ToolManager
 *   - 可选集成 SessionPipeline
 *   - 原生工具支持（toolkit_memory, toolkit_kb）
 */

package com.teaagent.android.api

import android.util.Log
import com.teaagent.android.core.*
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
    private val toolComponent: ToolComponent,
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
    private var pipeline: SessionPipeline? = null

    // ==================== Callbacks ====================

    data class ChatCallbacks(
        val onToken: (String) -> Unit = {},
        val onThinking: (String) -> Unit = {},
        val onToolCall: (String) -> Unit = {},
        val onDone: (String, Int, Int, Int) -> Unit = { _, _, _, _ -> },
        val onError: (String) -> Unit = {}
    )

    // ==================== 主聊天入口 ====================

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

                var messages = historyCompressor.buildMessages(
                    topicId, userMessage, config.keepTurns, systemPrompt
                ).toMutableList()

                val userMsgId = UUID.randomUUID().toString()
                messageDao.insert(Message(
                    id = userMsgId, topicId = topicId, role = "user",
                    content = userMessage, createdAt = System.currentTimeMillis()
                ))

                var iteration = 0
                var finalText = ""
                var totalTokens = 0
                var totalPrompt = 0
                var totalCompletion = 0

                while (iteration < config.maxIterations) {
                    iteration++
                    Log.d(TAG, "[iter $iteration/${config.maxIterations}] msgs=${messages.size}")

                    val result = callLLM(modelCfg, messages, callbacks)

                    if (result.error != null) {
                        withContext(Dispatchers.Main) { callbacks.onError(result.error) }
                        return@launch
                    }

                    totalTokens += result.tokenCount
                    totalPrompt += result.promptTokens
                    totalCompletion += result.completionTokens

                    if (result.toolCalls.isNotEmpty()) {
                        val assistantMsg = buildAssistantToolCallMsg(
                            result.toolCalls, result.content, result.reasoningContent
                        )
                        messages.add(assistantMsg)

                        val tcJson = JSONArray(result.toolCalls).toString()
                        messageDao.insert(Message(
                            id = UUID.randomUUID().toString(),
                            topicId = topicId, role = "assistant",
                            content = result.content, toolCalls = tcJson,
                            tokenCount = result.tokenCount,
                            promptTokens = result.promptTokens,
                            completionTokens = result.completionTokens,
                            createdAt = System.currentTimeMillis()
                        ))

                        for (tc in result.toolCalls) {
                            val fnName = tc.optJSONObject("function")?.optString("name") ?: continue
                            val fnArgsStr = tc.optJSONObject("function")?.optString("arguments") ?: "{}"
                            val fnArgs = try { JSONObject(fnArgsStr) } catch (_: Exception) { JSONObject() }

                            withContext(Dispatchers.Main) {
                                callbacks.onToolCall(JSONObject().apply {
                                    put("name", fnName); put("args", fnArgsStr)
                                }.toString())
                            }

                            val toolResult = toolComponent.execute(fnName, fnArgs)
                            Log.d(TAG, "[iter $iteration] exec $fnName → ${toolResult.take(100)}")

                            withContext(Dispatchers.Main) {
                                callbacks.onToolCall(JSONObject().apply {
                                    put("name", fnName); put("result", toolResult)
                                }.toString())
                            }

                            messages.add(mapOf(
                                "role" to "tool",
                                "tool_call_id" to tc.optString("id", ""),
                                "content" to toolResult
                            ))

                            messageDao.insert(Message(
                                id = UUID.randomUUID().toString(),
                                topicId = topicId, role = "tool",
                                content = toolResult,
                                toolCallId = tc.optString("id"),
                                createdAt = System.currentTimeMillis()
                            ))
                        }
                        continue
                    } else {
                        finalText = result.content ?: ""
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
                withContext(Dispatchers.Main) { callbacks.onDone("", 0, 0, 0) }
            } catch (e: java.net.ConnectException) {
                withContext(Dispatchers.Main) { callbacks.onError("连接失败：无法连接到 ${config.mainModel.apiUrl}") }
            } catch (e: Exception) {
                Log.e(TAG, "Chat error", e)
                withContext(Dispatchers.Main) { callbacks.onError(e.message ?: "未知错误") }
            }
        }
    }

    fun stop() {
        currentCall?.cancel(); currentCall = null
    }

    fun close() {
        stop(); scope.cancel()
    }

    // ==================== LLM 调用 ====================

    data class LLMResult(
        val content: String?,
        val toolCalls: List<JSONObject>,
        val tokenCount: Int,
        val promptTokens: Int,
        val completionTokens: Int,
        val error: String?,
        val reasoningContent: String? = null
    )

    private suspend fun callLLM(
        config: ModelConfig,
        messages: List<Map<String, Any?>>,
        callbacks: ChatCallbacks
    ): LLMResult = withContext(Dispatchers.IO) {
        try {
            val url = "${config.apiUrl.trimEnd('/')}/chat/completions"
            Log.d(TAG, "→ callLLM url=$url msgs=${messages.size}")

            val requestBody = JSONObject().apply {
                put("model", config.modelName)
                put("messages", JSONArray(messages.map { JSONObject(it.filterValues { it != null }) }))
                put("stream", true)
                put("max_tokens", config.maxTokens)
                put("temperature", config.temperature.toDouble())

                val toolSchemas = toolComponent.buildToolSchemas()
                if (toolSchemas.isNotEmpty()) {
                    put("tools", JSONArray(toolSchemas.map { schema ->
                        JSONObject().apply { put("type", "function"); put("function", schema) }
                    }))
                    put("tool_choice", "auto")
                }
            }.toString()

            val request = Request.Builder()
                .url(url).post(requestBody.toRequestBody("application/json".toMediaType()))
                .header("Content-Type", "application/json").header("Accept", "text/event-stream")
                .apply { if (config.apiKey.isNotBlank()) header("Authorization", "Bearer ${config.apiKey}") }
                .build()

            currentCall = client.newCall(request)
            val response = currentCall!!.execute()

            if (!response.isSuccessful) {
                return@withContext LLMResult(null, emptyList(), 0, 0, 0,
                    "HTTP ${response.code}: ${response.message}")
            }

            val reader = BufferedReader(
                InputStreamReader(response.body?.byteStream(), Charsets.UTF_8)
            )

            var contentBuilder = StringBuilder()
            var thinkingBuilder = StringBuilder()
            val toolCalls = mutableListOf<JSONObject>()
            var tokenCount = 0; var promptTokens = 0; var completionTokens = 0
            val toolCallAcc = mutableMapOf<Int, JSONObject>()
            val toolCallArgs = mutableMapOf<Int, StringBuilder>()

            reader.useLines { lines ->
                for (line in lines) {
                    if (!line.startsWith("data: ")) continue
                    val data = line.removePrefix("data: ").trim()
                    if (data == "[DONE]") break
                    try {
                        val json = JSONObject(data)
                        val choices = json.optJSONArray("choices") ?: continue
                        json.optJSONObject("usage")?.let { u ->
                            tokenCount = u.optInt("total_tokens", tokenCount)
                            promptTokens = u.optInt("prompt_tokens", promptTokens)
                            completionTokens = u.optInt("completion_tokens", completionTokens)
                        }
                        val delta = choices.optJSONObject(0)?.optJSONObject("delta") ?: continue
                        val content = if (delta.isNull("content")) "" else delta.optString("content", "")
                        if (content.isNotEmpty()) {
                            contentBuilder.append(content)
                            withContext(Dispatchers.Main) { callbacks.onToken(content) }
                        }
                        val reasoning = if (delta.isNull("reasoning_content")) "" else delta.optString("reasoning_content", "")
                        if (reasoning.isNotEmpty()) {
                            thinkingBuilder.append(reasoning)
                            withContext(Dispatchers.Main) { callbacks.onThinking(reasoning) }
                        }
                        val tcArray = delta.optJSONArray("tool_calls")
                        if (tcArray != null) {
                            for (i in 0 until tcArray.length()) {
                                val tc = tcArray.getJSONObject(i)
                                val idx = tc.optInt("index", i)
                                if (!toolCallAcc.containsKey(idx)) {
                                    toolCallAcc[idx] = JSONObject(); toolCallArgs[idx] = StringBuilder()
                                }
                                val id = tc.optString("id", "")
                                if (id.isNotEmpty()) toolCallAcc[idx]!!.put("id", id)
                                val fn = tc.optJSONObject("function")
                                if (fn != null) {
                                    if (!toolCallAcc[idx]!!.has("function")) toolCallAcc[idx]!!.put("function", JSONObject())
                                    val fnName = fn.optString("name", "")
                                    if (fnName.isNotEmpty()) toolCallAcc[idx]!!.getJSONObject("function").put("name", fnName)
                                    val args = fn.optString("arguments", "")
                                    if (args.isNotEmpty()) toolCallArgs[idx]!!.append(args)
                                }
                            }
                        }
                    } catch (_: Exception) {}
                }
            }

            for (idx in toolCallAcc.keys) {
                val tc = toolCallAcc[idx]!!
                val argsStr = toolCallArgs[idx]?.toString() ?: "{}"
                if (tc.has("function")) tc.getJSONObject("function").put("arguments", argsStr)
                if (!tc.has("id") || tc.optString("id", "").isEmpty())
                    tc.put("id", "call_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12))
                toolCalls.add(tc)
            }

            LLMResult(
                content = contentBuilder.toString().ifBlank { null },
                toolCalls = toolCalls,
                tokenCount = tokenCount, promptTokens = promptTokens,
                completionTokens = completionTokens, error = null,
                reasoningContent = thinkingBuilder.toString().ifBlank { null }
            )
        } catch (e: Exception) {
            Log.e(TAG, "callLLM error", e)
            LLMResult(null, emptyList(), 0, 0, 0, e.message)
        }
    }

    // ==================== System Prompt ====================

    private fun buildSystemPrompt(config: AgentConfig): String {
        return """
你是 TeaAgent，一个运行在 Android 上的智能助手。
当前日期：${java.text.SimpleDateFormat("yyyy-MM-dd").format(java.util.Date())}

你有以下能力：
- 流式对话
- 工具调用（Function Calling）
- 长期记忆管理（toolkit_memory）
- 知识库查询（toolkit_kb）

回复要求：使用中文，简洁准确，代码用 Markdown 代码块。
        """.trimIndent()
    }

    private fun buildAssistantToolCallMsg(
        toolCalls: List<JSONObject>, content: String?, reasoningContent: String? = null
    ): Map<String, Any?> {
        val msg = mutableMapOf<String, Any?>(
            "role" to "assistant",
            "tool_calls" to toolCalls.map { tc ->
                mapOf("id" to tc.optString("id"), "type" to "function",
                    "function" to mapOf("name" to tc.optJSONObject("function")?.optString("name"),
                        "arguments" to tc.optJSONObject("function")?.optString("arguments")))
            }
        )
        if (!content.isNullOrBlank()) msg["content"] = content
        if (!reasoningContent.isNullOrBlank()) msg["reasoning_content"] = reasoningContent
        return msg
    }
}
