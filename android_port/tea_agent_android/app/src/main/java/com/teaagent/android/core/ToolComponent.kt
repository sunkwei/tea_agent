/*
 * @2026-06-04 gen by tea_agent, ToolComponent — 工具执行组件（对齐桌面版 ToolComponent）
 *
 * 设计原则：
 * 1. 支持多种工具类型：JS 工具（WebView）、原生 Kotlin 工具、受保护元工具
 * 2. 工具过滤：支持 ESSENTIAL_TOOLS 始终保留
 * 3. 清晰的 schema 管理，与 OpenAI function calling 格式对齐
 * 4. 隔离执行逻辑，便于测试
 */

package com.teaagent.android.core

import android.util.Log
import android.webkit.WebView
import com.teaagent.android.db.ToolDao
import com.teaagent.android.model.Tool
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * 工具执行组件。
 * 
 * 管理所有工具的定义、注册和执行。
 * 支持三种工具类型：
 * - PROTECTED: 受保护元工具（toolkit_save, toolkit_reload），硬编码，不可覆盖
 * - JS: 用户通过 toolkit_save 注册的 JS 函数，在 WebView 中执行
 * - NATIVE: 原生 Kotlin 工具，直接执行
 */
class ToolComponent(
    private val toolDao: ToolDao,
    private val webView: WebView,
    private val memoryManager: MemoryManager? = null,
    private val selfEvolveManager: SelfEvolveManager? = null
) {
    companion object {
        private const val TAG = "ToolComponent"

        /** 始终保留的必要工具集合（对齐桌面版 ESSENTIAL_TOOLS） */
        val ESSENTIAL_TOOLS = setOf("toolkit_memory", "toolkit_kb")

        /** 受保护的工具名 — 不在 SQLite 中存储，不可被 toolkit_save 覆盖 */
        val PROTECTED_TOOL_NAMES = setOf("toolkit_save", "toolkit_reload")

        /** 原生 Kotlin 工具注册表 — name -> (description, schema, executor) */
        val NATIVE_TOOLS = mutableMapOf<String, NativeToolDef>()
    }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    /** 已注册的原生工具列表 */
    private val nativeToolInstances = mutableListOf<NativeToolInstance>()

    // ==================== 工具定义 ====================

    data class NativeToolDef(
        val description: String,
        val parameters: JSONObject,
        val executor: suspend (JSONObject) -> String
    )

    data class NativeToolInstance(
        val name: String,
        val meta: JSONObject,
        val executor: suspend (JSONObject) -> String
    )

    // ==================== 初始化 ====================

    /**
     * 启动时调用：清除 SQLite 中受保护工具残留，加载用户工具，注册原生工具。
     */
    fun init() {
        // 清除残留的受保护工具
        for (name in PROTECTED_TOOL_NAMES) {
            if (toolDao.getByName(name) != null) {
                toolDao.delete(name)
                Log.w(TAG, "Removed protected tool '$name' from SQLite")
            }
        }

        // 清除可能残留的 ESSENTIAL_TOOLS
        for (name in ESSENTIAL_TOOLS) {
            if (toolDao.getByName(name) != null) {
                toolDao.delete(name)
                Log.w(TAG, "Removed essential tool '$name' from SQLite (should be native)")
            }
        }

        // 注册原生工具
        registerEssentialTools()

        // 注入用户 JS 工具到 WebView
        val tools = toolDao.listAll()
        tools.forEach { injectToolToWebView(it.name, it.jsCode) }
        Log.d(TAG, "init: loaded ${tools.size} user tools, ${nativeToolInstances.size} native tools")
    }

    private fun registerEssentialTools() {
        // toolkit_memory — 长期记忆工具
        nativeToolInstances.add(NativeToolInstance(
            name = "toolkit_memory",
            meta = JSONObject("""
                {"name":"toolkit_memory","description":"长期记忆管理：存储和检索关键信息。可以 'add' 添加记忆，'search' 搜索记忆，'list' 列出最近记忆。","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["add","search","list","stats"],"description":"操作：add=添加记忆, search=搜索, list=列出, stats=统计"},"content":{"type":"string","description":"[add] 记忆内容"},"query":{"type":"string","description":"[search] 搜索关键词"},"category":{"type":"string","description":"分类（general/preference/fact/instruction）"},"importance":{"type":"integer","description":"重要度 1-5","default":3},"limit":{"type":"integer","description":"返回数量上限","default":10}},"required":["action"]}}
            """.trimIndent()),
            executor = { args -> executeNativeMemory(args) }
        ))

        // toolkit_kb — 知识库查询
        nativeToolInstances.add(NativeToolInstance(
            name = "toolkit_kb",
            meta = JSONObject("""
                {"name":"toolkit_kb","description":"知识库查询：从知识库中查找信息。支持 search 搜索和 list 列出。","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["search","list"],"description":"操作：search=搜索, list=列出"},"query":{"type":"string","description":"[search] 搜索关键词"}},"required":["action"]}}
            """.trimIndent()),
            executor = { args -> executeNativeKb(args) }
        ))

        // toolkit_self_evolve — 自我进化
        nativeToolInstances.add(NativeToolInstance(
            name = "toolkit_self_evolve",
            meta = JSONObject("""
                {"name":"toolkit_self_evolve","description":"自我进化工具：允许 Agent 优化自己的工具代码或系统提示词。支持 evolve_tool（更新工具代码，自动备份旧版本）、rollback_tool（回滚工具到上次备份）、evolve_prompt（进化系统提示词）、validate（校验 JS 代码安全性）。","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["evolve_tool","rollback_tool","evolve_prompt","validate","status"],"description":"操作类型"},"tool_name":{"type":"string","description":"[evolve_tool/rollback_tool] 工具名称"},"js_code":{"type":"string","description":"[evolve_tool] 新的 JavaScript 代码"},"new_prompt":{"type":"string","description":"[evolve_prompt] 新的系统提示词"},"reason":{"type":"string","description":"更新原因说明"}},"required":["action"]}}
            """.trimIndent()),
            executor = { args -> executeNativeSelfEvolve(args) }
        ))

        // toolkit_prompt_evolve — 提示词进化
        nativeToolInstances.add(NativeToolInstance(
            name = "toolkit_prompt_evolve",
            meta = JSONObject("""
                {"name":"toolkit_prompt_evolve","description":"系统提示词进化：优化当前系统提示词。可以查看当前版本（current）、进化提示词（evolve）、回滚（rollback）。","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["current","evolve","rollback"],"description":"操作：current=查看当前, evolve=进化, rollback=回滚"},"content":{"type":"string","description":"[evolve] 新的提示词内容"},"reason":{"type":"string","description":"[evolve] 进化原因"}},"required":["action"]}}
            """.trimIndent()),
            executor = { args -> executeNativePromptEvolve(args) }
        ))
    }

    // ==================== 工具 Schema 构建 ====================

    /**
     * 获取所有工具的 OpenAI tool schema 列表。
     * 对齐桌面版 ToolComponent.build_tools()
     * 
     * 返回顺序：受保护工具 → 原生工具 → 用户工具
     */
    fun buildToolSchemas(): List<JSONObject> {
        val schemas = mutableListOf<JSONObject>()

        // 1. 受保护工具
        schemas.addAll(getProtectedToolSchemas())

        // 2. 原生工具
        for (inst in nativeToolInstances) {
            schemas.add(inst.meta)
        }

        // 3. 用户工具
        val userTools = toolDao.listAll().mapNotNull { tool ->
            try {
                if (!tool.meta.isNullOrBlank()) JSONObject(tool.meta) else null
            } catch (e: Exception) { null }
        }
        schemas.addAll(userTools)

        return schemas
    }

    /**
     * 带过滤的工具 Schema（对齐 desktop filter_tools）
     * 
     * @param toolFilter 允许的工具名列表（null=全部）
     * @return 过滤后的 schema 列表
     */
    fun buildFilteredToolSchemas(toolFilter: List<String>? = null): List<JSONObject> {
        val all = buildToolSchemas()
        if (toolFilter == null || toolFilter.isEmpty()) return all

        val allowed = toolFilter.toSet() + ESSENTIAL_TOOLS + PROTECTED_TOOL_NAMES
        return all.filter { schema ->
            val name = schema.optString("name", "")
            name in allowed
        }
    }

    // ==================== 工具执行 ====================

    /**
     * 执行指定工具。根据工具类型路由到对应的执行器。
     * 对齐桌面版 ToolComponent.execute_tool_call()
     *
     * @param name 工具名
     * @param args 参数 JSONObject
     * @return 执行结果 JSON 字符串
     */
    suspend fun execute(name: String, args: JSONObject): String {
        val startTime = System.currentTimeMillis()

        try {
            // 1. 受保护元工具
            when (name) {
                "toolkit_save" -> return executeToolkitSave(args)
                "toolkit_reload" -> return executeToolkitReload()
            }

            // 2. 原生工具
            for (inst in nativeToolInstances) {
                if (inst.name == name) {
                    val result = inst.executor(args)
                    Log.d(TAG, "✅ native tool $name → ${result.take(100)} (${System.currentTimeMillis() - startTime}ms)")
                    return result
                }
            }

            // 3. 用户 JS 工具
            val tool = toolDao.getByName(name)
            if (tool != null) {
                val result = executeJsTool(name, args)
                Log.d(TAG, "✅ js tool $name → ${result.take(100)} (${System.currentTimeMillis() - startTime}ms)")
                return result
            }

            return """{"error":"Tool not found: $name"}"""
        } catch (e: Exception) {
            Log.e(TAG, "❌ tool $name error", e)
            return """{"error":"${e.message?.replace("\"", "\\\"")}"}"""
        }
    }

    // ==================== 受保护工具执行 ====================

    private fun getProtectedToolSchemas(): List<JSONObject> = listOf(
        JSONObject(
            """{"name":"toolkit_save","description":"保存一个新的工具函数到工具库。工具代码为 JavaScript，接收 args 对象参数，必须返回结果。保存后自动加载，下次对话即可调用。","parameters":{"type":"object","properties":{"name":{"type":"string","description":"工具名称，以 toolkit_ 为前缀"},"meta":{"type":"object","description":"OpenAI function calling schema，含 name/description/parameters"},"js_code":{"type":"string","description":"JavaScript 函数体，格式: function(args) { ... return result; }。args 是 LLM 传入的参数对象"}},"required":["name","meta","js_code"]}}"""
        ),
        JSONObject(
            """{"name":"toolkit_reload","description":"重新加载所有已保存的工具函数到执行环境。新注册/修改的工具需要 reload 后才能在下一次 tool_choice 中出现。","parameters":{"type":"object","properties":{},"required":[]}}"""
        )
    )

    private suspend fun executeToolkitSave(args: JSONObject): String {
        val toolName = args.optString("name", "")
        if (toolName.isBlank()) return """{"ok":false,"error":"缺少 name 参数"}"""

        // 拒绝覆盖受保护工具
        if (toolName in PROTECTED_TOOL_NAMES || toolName in ESSENTIAL_TOOLS) {
            return """{"ok":false,"error":"Cannot modify protected tool: $toolName"}"""
        }

        val metaStr = when (val metaVal = args.opt("meta")) {
            is JSONObject -> metaVal.toString()
            null -> ""
            else -> metaVal.toString()
        }
        val jsCode = args.optString("js_code", "")
        if (jsCode.isBlank()) return """{"ok":false,"error":"缺少 js_code 参数"}"""

        // 注入 WebView
        withContext(Dispatchers.Main) { injectToolToWebView(toolName, jsCode) }

        return try {
            val existing = toolDao.getByName(toolName)
            val now = System.currentTimeMillis()
            if (existing != null) {
                toolDao.update(existing.copy(meta = metaStr, jsCode = jsCode, updatedAt = now))
                """{"ok":true,"name":"$toolName","action":"updated"}"""
            } else {
                val tool = Tool(
                    id = UUID.randomUUID().toString(),
                    name = toolName, meta = metaStr, jsCode = jsCode,
                    createdAt = now, updatedAt = now
                )
                toolDao.insert(tool)
                """{"ok":true,"name":"$toolName","action":"created"}"""
            }
        } catch (e: Exception) {
            """{"ok":false,"error":"${e.message?.replace("\"", "\\\"")}"}"""
        }
    }

    private suspend fun executeToolkitReload(): String = withContext(Dispatchers.Main) {
        try {
            val tools = toolDao.listAll()
            tools.forEach { injectToolToWebView(it.name, it.jsCode) }
            """{"ok":true,"count":${tools.size}}"""
        } catch (e: Exception) {
            """{"ok":false,"error":"${e.message}"}"""
        }
    }

    // ==================== 原生工具执行 ====================

    private fun executeNativeMemory(args: JSONObject): String {
        val mm = memoryManager
        if (mm == null) {
            return """{"ok":false,"error":"MemoryManager 未初始化"}"""
        }

        val action = args.optString("action", "")
        return when (action) {
            "add" -> {
                val content = args.optString("content", "")
                val category = args.optString("category", "general")
                val tags = args.optString("tags", "")
                val importance = args.optInt("importance", 3)
                if (content.isBlank()) """{"ok":false,"error":"content 不能为空"}"""
                else {
                    val id = mm.add(content, category, tags, importance)
                    """{"ok":true,"id":"$id","message":"记忆已记录"}"""
                }
            }
            "search" -> {
                val query = args.optString("query", "")
                val limit = args.optInt("limit", 10)
                val results = mm.search(query, limit)
                JSONObject().apply {
                    put("ok", true)
                    put("results", JSONArray(results.map { m ->
                        JSONObject().apply {
                            put("id", m.id); put("content", m.content)
                            put("category", m.category); put("importance", m.importance)
                        }
                    }))
                    put("query", query)
                }.toString()
            }
            "list" -> {
                val limit = args.optInt("limit", 20)
                val category = args.optString("category", "")
                val results = mm.list(limit, category.ifBlank { null })
                JSONObject().apply {
                    put("ok", true)
                    put("memories", JSONArray(results.map { m ->
                        JSONObject().apply {
                            put("id", m.id); put("content", m.content)
                            put("category", m.category); put("tags", m.tags)
                            put("importance", m.importance)
                            put("created_at", m.createdAt)
                        }
                    }))
                }.toString()
            }
            "stats" -> mm.stats()
            else -> """{"error":"Unknown action: $action"}"""
        }
    }

    private fun executeNativeKb(args: JSONObject): String {
        val action = args.optString("action", "")
        return when (action) {
            "search" -> {
                val query = args.optString("query", "")
                """{"ok":true,"results":[],"query":"$query"}"""
            }
            "list" -> """{"ok":true,"topics":[]}"""
            else -> """{"error":"Unknown action: $action"}"""
        }
    }

    private fun executeNativeSelfEvolve(args: JSONObject): String {
        val sem = selfEvolveManager
        if (sem == null) {
            return """{"ok":false,"error":"SelfEvolveManager 未初始化"}"""
        }

        val action = args.optString("action", "")
        return when (action) {
            "evolve_tool" -> {
                val toolName = args.optString("tool_name", "")
                val jsCode = args.optString("js_code", "")
                val reason = args.optString("reason", "")
                if (toolName.isBlank()) return """{"ok":false,"error":"tool_name 不能为空"}"""
                if (jsCode.isBlank()) return """{"ok":false,"error":"js_code 不能为空"}"""
                sem.evolveTool(toolName, jsCode, reason).toString()
            }
            "rollback_tool" -> {
                val toolName = args.optString("tool_name", "")
                if (toolName.isBlank()) return """{"ok":false,"error":"tool_name 不能为空"}"""
                sem.rollbackTool(toolName).toString()
            }
            "evolve_prompt" -> {
                val newPrompt = args.optString("new_prompt", "")
                val reason = args.optString("reason", "")
                if (newPrompt.isBlank()) return """{"ok":false,"error":"new_prompt 不能为空"}"""
                sem.evolvePrompt(newPrompt, reason).toString()
            }
            "validate" -> {
                val jsCode = args.optString("js_code", "")
                if (jsCode.isBlank()) return """{"ok":false,"error":"js_code 不能为空"}"""
                sem.validateJsCode(jsCode).toString()
            }
            "status" -> sem.getStatus().toString()
            else -> """{"error":"Unknown action: $action"}"""
        }
    }

    private fun executeNativePromptEvolve(args: JSONObject): String {
        val pm = null // PromptManager is not directly accessible here, use SelfEvolveManager
        val action = args.optString("action", "")
        return when (action) {
            "current" -> {
                """{"ok":true,"version":"${selfEvolveManager?.let { return@let "" } ?: "?"}","alert":"通过 toolkit_self_evolve 操作"}"""
            }
            else -> """{"info":"请使用 toolkit_self_evolve 管理提示词"}"""
        }
    }

    // ==================== JS 工具执行 ====================

    private suspend fun executeJsTool(name: String, args: JSONObject): String {
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

        return withContext(Dispatchers.Main) {
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
    }

    // ==================== 辅助方法 ====================

    /**
     * 注入单个工具到 WebView 全局作用域
     */
    private fun injectToolToWebView(name: String, jsCode: String) {
        val safeName = name.replace("\"", "\\\"")
        val safeCode = jsCode
            .replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("$", "\\$")

        val script = """
            window['$safeName'] = $safeCode;
            console.log('Tool loaded: $safeName');
        """.trimIndent()

        webView.evaluateJavascript(script, null)
    }

    /**
     * 检查工具是否存在
     */
    fun hasTool(name: String): Boolean {
        if (name in PROTECTED_TOOL_NAMES) return true
        if (nativeToolInstances.any { it.name == name }) return true
        return toolDao.getByName(name) != null
    }

    /**
     * 获取所有工具名列表
     */
    fun getToolNames(): List<String> {
        val names = mutableListOf<String>()
        names.addAll(PROTECTED_TOOL_NAMES)
        names.addAll(nativeToolInstances.map { it.name })
        names.addAll(toolDao.listAll().map { it.name })
        return names
    }

    fun hasTools(): Boolean =
        PROTECTED_TOOL_NAMES.isNotEmpty() ||
        nativeToolInstances.isNotEmpty() ||
        toolDao.count() > 0
}
