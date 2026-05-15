/*
 * @2026-05-16 gen by tea_agent, JsBridge — JS ↔ Kotlin 桥接
 *
 * 封装所有需要 Kotlin 原生能力的接口：
 * - 对话（chat.send / chat.stop）
 * - 配置（config.get / config.set）
 * - 主题管理（topic.list / topic.select / topic.new / topic.delete）
 * - 工具管理（tool.save / tool.reload / tool.list）
 * - 系统（notify / copy / file 操作）
 */

package com.teaagent.android.bridge

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.teaagent.android.api.ApiClient
import com.teaagent.android.core.ConfigManager
import com.teaagent.android.core.ToolManager
import com.teaagent.android.db.*
import com.teaagent.android.model.Topic
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

class JsBridge(
    private val context: Context,
    private val webView: WebView,
    private val db: AppDatabase,
    private val apiClient: ApiClient,
    private val configManager: ConfigManager,
    private val toolManager: ToolManager
) {
    companion object {
        private const val TAG = "TeaJsBridge"
    }

    private val topicDao: TopicDao
    private val messageDao: MessageDao

    init {
        val wDb = db.writableDatabase
        topicDao = TopicDao(wDb)
        messageDao = MessageDao(wDb)
    }

    // ==================== Chat ====================

    @JavascriptInterface
    fun chatSend(jsonArgs: String) {
        try {
            val args = JSONObject(jsonArgs)
            val message = args.optString("message", "")
            val topicId = args.optString("topic_id", "")

            if (message.isBlank()) {
                emitEvent("error", """{"message":"消息不能为空"}""")
                return
            }

            val config = configManager.load()

            apiClient.chat(
                config = config,
                topicId = topicId,
                userMessage = message,
                callbacks = ApiClient.ChatCallbacks(
                    onToken = { token ->
                        emitEvent("token", JSONObject().apply {
                            put("text", token)
                        }.toString())
                    },
                    onThinking = { thinking ->
                        emitEvent("thinking", JSONObject().apply {
                            put("text", thinking)
                        }.toString())
                    },
                    onToolCall = { tcJson ->
                        emitEvent("tool_call", tcJson)
                    },
                    onDone = { finalText, totalTokens, promptTokens, completionTokens ->
                        emitEvent("done", JSONObject().apply {
                            put("text", finalText)
                            put("total_tokens", totalTokens)
                            put("prompt_tokens", promptTokens)
                            put("completion_tokens", completionTokens)
                        }.toString())
                    },
                    onError = { error ->
                        emitEvent("error", JSONObject().apply {
                            put("message", error)
                        }.toString())
                    }
                )
            )
        } catch (e: Exception) {
            Log.e(TAG, "chatSend error", e)
            emitEvent("error", """{"message":"${e.message?.replace("\"", "\\\"")}"}""")
        }
    }

    @JavascriptInterface
    fun chatStop() {
        apiClient.stop()
    }

    // ==================== Config ====================

    @JavascriptInterface
    fun configGet(): String {
        val config = configManager.load()
        return JSONObject().apply {
            put("main_model", modelToJson(config.mainModel))
            put("cheap_model", modelToJson(config.cheapModel))
            put("embedding_model", modelToJson(config.embeddingModel))
            put("keep_turns", config.keepTurns)
            put("max_iterations", config.maxIterations)
            put("enable_thinking", config.enableThinking)
            put("theme", config.theme)
        }.toString()
    }

    @JavascriptInterface
    fun configSet(jsonArgs: String) {
        try {
            val args = JSONObject(jsonArgs)
            val config = configManager.load()

            args.optJSONObject("main_model")?.let { config.mainModel = parseModel(it) }
            args.optJSONObject("cheap_model")?.let { config.cheapModel = parseModel(it) }
            args.optJSONObject("embedding_model")?.let { config.embeddingModel = parseModel(it) }
            if (args.has("keep_turns")) config.keepTurns = args.getInt("keep_turns")
            if (args.has("max_iterations")) config.maxIterations = args.getInt("max_iterations")
            if (args.has("enable_thinking")) config.enableThinking = args.getBoolean("enable_thinking")
            if (args.has("theme")) config.theme = args.optString("theme")

            configManager.save(config)
        } catch (e: Exception) {
            Log.e(TAG, "configSet error", e)
        }
    }

    // ==================== Topics ====================

    @JavascriptInterface
    fun topicList(): String {
        val topics = topicDao.listAll()
        return JSONArray().apply {
            topics.forEach { t ->
                put(JSONObject().apply {
                    put("id", t.id)
                    put("title", t.title)
                    put("created_at", t.createdAt)
                    put("updated_at", t.updatedAt)
                })
            }
        }.toString()
    }

    @JavascriptInterface
    fun topicNew(title: String): String {
        val id = UUID.randomUUID().toString()
        val now = System.currentTimeMillis()
        topicDao.insert(Topic(id = id, title = title, createdAt = now, updatedAt = now))
        return id
    }

    @JavascriptInterface
    fun topicDelete(topicId: String) {
        messageDao.deleteByTopic(topicId)
        topicDao.delete(topicId)
    }

    @JavascriptInterface
    fun topicMessages(topicId: String): String {
        val msgs = messageDao.getByTopic(topicId, 200)
        return JSONArray().apply {
            msgs.forEach { m ->
                put(JSONObject().apply {
                    put("id", m.id)
                    put("role", m.role)
                    put("content", m.content ?: "")
                    put("tool_calls", m.toolCalls ?: "")
                    put("token_count", m.tokenCount)
                    put("prompt_tokens", m.promptTokens)
                    put("completion_tokens", m.completionTokens)
                    put("created_at", m.createdAt)
                })
            }
        }.toString()
    }

    @JavascriptInterface
    fun topicTokenStats(topicId: String): String {
        val (total, prompt, comp) = messageDao.totalTokensByTopic(topicId)
        return JSONObject().apply {
            put("total_tokens", total)
            put("prompt_tokens", prompt)
            put("completion_tokens", comp)
        }.toString()
    }

    // ==================== Tools ====================

    @JavascriptInterface
    fun toolSave(name: String, metaJson: String, jsCode: String): String {
        return toolManager.save(name, metaJson, jsCode)
    }

    @JavascriptInterface
    fun toolReload(): String {
        // reload() 是 suspend，在 @JavascriptInterface 中需要用 runBlocking
        return kotlinx.coroutines.runBlocking {
            toolManager.reload()
        }
    }

    @JavascriptInterface
    fun toolList(): String {
        val arr = JSONArray()

        // 受保护工具
        for (name in ToolManager.PROTECTED_TOOL_NAMES) {
            arr.put(JSONObject().apply {
                put("name", name)
                put("is_protected", true)
            })
        }

        // 用户工具（SQLite）
        val wDb = db.readableDatabase
        val tools = ToolDao(wDb).listAll()
        for (t in tools) {
            arr.put(JSONObject().apply {
                put("name", t.name)
                put("meta", t.meta ?: "")
                put("created_at", t.createdAt)
                put("is_protected", false)
            })
        }

        return arr.toString()
    }

    // ==================== System ====================

    @JavascriptInterface
    fun systemNotify(title: String, message: String) {
        FileHandler.showNotification(context, title, message)
    }

    @JavascriptInterface
    fun copyToClipboard(text: String) {
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("TeaAgent", text))
    }

    // ==================== Helpers ====================

    private fun emitEvent(eventType: String, data: String) {
        val escaped = data
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        val js = "javascript:TeaBridge.emit('$eventType', '$escaped')"
        webView.post { webView.evaluateJavascript(js, null) }
    }

    private fun modelToJson(m: com.teaagent.android.model.ModelConfig) = JSONObject().apply {
        put("id", m.id)
        put("api_url", m.apiUrl)
        put("api_key", m.apiKey)
        put("model_name", m.modelName)
        put("max_tokens", m.maxTokens)
        put("temperature", m.temperature.toDouble())
    }

    private fun parseModel(obj: JSONObject) = com.teaagent.android.model.ModelConfig(
        id = obj.optString("id", ""),
        apiUrl = obj.optString("api_url", "http://10.0.2.2:11434/v1"),
        apiKey = obj.optString("api_key", ""),
        modelName = obj.optString("model_name", ""),
        maxTokens = obj.optInt("max_tokens", 4096),
        temperature = obj.optDouble("temperature", 0.7).toFloat()
    )
}
