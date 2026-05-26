/*
 * @2026-05-16 gen by tea_agent, ToolManager — JS 工具动态加载与执行
 * @2026-05-14 gen by tea_agent, toolkit_mgrt/reload 固化为受保护元工具，不存 SQLite
 *
 * 核心能力:
 *   toolkit_mgrt(name, meta, js_code) → 存入 SQLite（拒绝覆盖受保护工具）
 *   toolkit_reload() → 重新加载所有工具到 WebView JS 上下文
 *   执行任意已注册工具（通过 WebView.evaluateJavascript）
 *
 * 受保护工具：toolkit_mgrt / toolkit_reload 硬编码在 Kotlin 侧，
 * 不存储到 SQLite，不经过 WebView JS 执行，确保不被 LLM 误修改。
 *
 * 工具代码规范：
 *   js_code 是一个 JS 函数体，接收单个 args 对象，返回结果。
 *   例：function(args) { return args.a + args.b; }
 */

package com.teaagent.android.core

import android.util.Log
import android.webkit.WebView
import com.teaagent.android.db.ToolDao
import com.teaagent.android.model.Tool
import kotlinx.coroutines.*
import org.json.JSONObject
import java.util.UUID

class ToolManager(
    private val toolDao: ToolDao,
    private val webView: WebView
) {
    companion object {
        private const val TAG = "ToolManager"

        // 受保护的工具名 — 不在 SQLite 中存储，不可被 toolkit_mgrt 覆盖
        val PROTECTED_TOOL_NAMES = setOf("toolkit_mgrt", "toolkit_reload")
    }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    // ==================== 受保护工具 schema（硬编码） ====================

    private fun getProtectedToolSchemas(): List<JSONObject> = listOf(
        JSONObject(
            """{"name":"toolkit_mgrt","description":"保存一个新的工具函数到工具库。工具代码为 JavaScript，接收 args 对象参数，必须返回结果。保存后自动加载，下次对话即可调用。","parameters":{"type":"object","properties":{"name":{"type":"string","description":"工具名称，以 toolkit_ 为前缀"},"meta":{"type":"object","description":"OpenAI function calling schema，含 name/description/parameters"},"js_code":{"type":"string","description":"JavaScript 函数体，格式: function(args) { ... return result; }。args 是 LLM 传入的参数对象"}},"required":["name","meta","js_code"]}}"""
        ),
        JSONObject(
            """{"name":"toolkit_reload","description":"重新加载所有已保存的工具函数到执行环境。新注册/修改的工具需要 reload 后才能在下一次 tool_choice 中出现。","parameters":{"type":"object","properties":{},"required":[]}}"""
        )
    )

    // ==================== 初始化 ====================

    /**
     * 启动时调用：清除 SQLite 中可能残留的受保护工具，加载用户工具
     * 仅在主线程 onCreate() 调用，直接操作 WebView 无线程问题
     */
    fun init() {
        for (name in PROTECTED_TOOL_NAMES) {
            if (toolDao.getByName(name) != null) {
                toolDao.delete(name)
                Log.w(TAG, "Removed protected tool '$name' from SQLite")
            }
        }
        val tools = toolDao.listAll()
        tools.forEach { injectToolToWebView(it.name, it.jsCode) }
        Log.d(TAG, "init: loaded ${tools.size} user tools")
    }

    /**
     * toolkit_mgrt — 存储或更新用户工具（拒绝覆盖受保护工具）
     */
    fun save(name: String, metaJson: String, jsCode: String): String {
        if (name in PROTECTED_TOOL_NAMES) {
            Log.w(TAG, "Blocked attempt to modify protected tool: $name")
            return """{"ok":false,"error":"Cannot modify protected tool: $name"}"""
        }
        try {
            val existing = toolDao.getByName(name)
            val now = System.currentTimeMillis()
            if (existing != null) {
                toolDao.update(existing.copy(
                    meta = metaJson, jsCode = jsCode, updatedAt = now
                ))
                return """{"ok":true,"name":"$name","action":"updated"}"""
            } else {
                val tool = Tool(
                    id = UUID.randomUUID().toString(),
                    name = name, meta = metaJson, jsCode = jsCode,
                    createdAt = now, updatedAt = now
                )
                toolDao.insert(tool)
                return """{"ok":true,"name":"$name","action":"created"}"""
            }
        } catch (e: Exception) {
            Log.e(TAG, "save error", e)
            return """{"ok":false,"error":"${e.message?.replace("\"", "\\\"")}"}"""
        }
    }

    /**
     * toolkit_reload — 重新加载所有工具到 WebView（必须在主线程调用 WebView）
     */
    suspend fun reload(): String = withContext(Dispatchers.Main) {
        try {
            val tools = toolDao.listAll()
            tools.forEach { injectToolToWebView(it.name, it.jsCode) }
            """{"ok":true,"count":${tools.size}}"""
        } catch (e: Exception) {
            Log.e(TAG, "reload error", e)
            """{"ok":false,"error":"${e.message}"}"""
        }
    }

    /**
     * 执行指定工具。受保护工具走原生 Kotlin，普通工具走 WebView JS。
     */
    suspend fun execute(name: String, args: JSONObject): String {
        // --- 受保护工具：原生 Kotlin 执行 ---
        when (name) {
            "toolkit_mgrt" -> {
                val toolName = args.optString("name", "")
                if (toolName.isBlank()) return """{"ok":false,"error":"缺少 name 参数"}"""
                // meta 可能是 JSONObject（LLM 直接传）或 String
                val metaStr = when (val metaVal = args.opt("meta")) {
                    is JSONObject -> metaVal.toString()
                    null -> ""
                    else -> metaVal.toString()
                }
                val jsCode = args.optString("js_code", "")
                if (jsCode.isBlank()) return """{"ok":false,"error":"缺少 js_code 参数"}"""
                // 注入 WebView 必须在主线程
                withContext(Dispatchers.Main) { injectToolToWebView(toolName, jsCode) }
                return try {
                    save(toolName, metaStr, jsCode)
                } catch (e: Exception) {
                    """{"ok":false,"error":"${e.message?.replace("\"", "\\\"")}"}"""
                }
            }
            "toolkit_reload" -> return try {
                reload()
            } catch (e: Exception) {
                """{"ok":false,"error":"${e.message?.replace("\"", "\\\"")}"}"""
            }
        }

        // --- 普通工具：SQLite → WebView JS ---
        val tool = toolDao.getByName(name)
        if (tool == null) {
            return """{"error":"Tool not found: $name"}"""
        }

        return try {
            val argsJson = args.toString()
            val jsCode = """
                (function() {
                    try {
                        var fn = window['$name'];
                        if (typeof fn !== 'function') {
                            return JSON.stringify({error: 'Tool function not loaded: $name'});
                        }
                        var result = fn($argsJson);
                        if (result === undefined) return JSON.stringify({ok: true});
                        if (typeof result === 'string') {
                            try { JSON.parse(result); return result; } catch(e) {}
                            return JSON.stringify({ok: true, result: result});
                        }
                        return JSON.stringify({ok: true, result: result});
                    } catch(e) {
                        return JSON.stringify({error: e.message || 'Tool execution error'});
                    }
                })();
            """.trimIndent()

            // WebView.evaluateJavascript 必须在主线程调用
            withContext(Dispatchers.Main) {
                val deferred = CompletableDeferred<String>()
                webView.evaluateJavascript(jsCode) { result ->
                    val parsed = when {
                        result == "null" || result.isNullOrBlank() -> """{"ok":true}"""
                        result.startsWith("\"") && result.endsWith("\"") ->
                            result.substring(1, result.length - 1).replace("\\\"", "\"")
                        else -> result
                    }
                    deferred.complete(parsed)
                }
                deferred.await()
            }
        } catch (e: Exception) {
            """{"error":"${e.message}"}"""
        }
    }

    /**
     * 获取所有工具的 OpenAI tool schema 列表（受保护工具 + 用户工具，用于 API 请求）
     */
    fun getToolSchemas(): List<JSONObject> {
        val userTools = toolDao.listAll().mapNotNull { tool ->
            try {
                if (!tool.meta.isNullOrBlank()) JSONObject(tool.meta) else null
            } catch (e: Exception) { null }
        }
        return getProtectedToolSchemas() + userTools
    }

    fun getToolNames(): List<String> = PROTECTED_TOOL_NAMES.toList() + toolDao.listAll().map { it.name }

    fun hasTools(): Boolean = PROTECTED_TOOL_NAMES.isNotEmpty() || toolDao.count() > 0

    /**
     * 将单个工具注入 WebView 全局作用域
     */
    private fun injectToolToWebView(name: String, jsCode: String) {
        val safeName = name.replace("\"", "\\\"")
        val safeCode = jsCode
            .replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("${'$'}", "\\${'$'}")

        val script = """
            window['$safeName'] = $safeCode;
            console.log('Tool loaded: $safeName');
        """.trimIndent()

        webView.evaluateJavascript(script, null)
    }
}
