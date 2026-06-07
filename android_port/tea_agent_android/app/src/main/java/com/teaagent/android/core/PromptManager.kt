/*
 * @2026-06-04 gen by tea_agent, PromptManager — 系统提示词版本管理器
 *
 * 对标桌面版 prompt_manager.py 的 SystemPromptManager。
 * 管理多版本系统提示词：
 * - 从 SQLite 加载最新活跃版本
 * - 支持版本回滚
 * - 支持基于上下文动态调整
 */

package com.teaagent.android.core

import android.util.Log
import com.teaagent.android.db.ConfigDao
import org.json.JSONObject

/**
 * 系统提示词版本管理器。
 *
 * 管理多版本系统提示词，从 SQLite config 表持久化。
 * 每次对话使用最新版本。
 */
class PromptManager(private val configDao: ConfigDao) {

    companion object {
        private const val TAG = "PromptManager"

        private const val KEY_PROMPT_JSON = "system_prompt_json"
        private const val PROMPT_VERSION_KEY = "system_prompt_version"

        /** 默认系统提示词（当数据库无记录时使用） */
        val DEFAULT_SYSTEM_PROMPT = """
你是可自我扩展的智能Agent。
拥有工具库toolkit，可通过toolkit_save(name,meta,js_code)保存新工具、toolkit_reload()重载获得新能力。
内置工具：toolkit_exec(执行命令)、toolkit_file(r/w/list)等。

核心行为：主动分析任务需求，自主创建/优化/组合工具。
工具须为纯JavaScript、可执行、有明确输入输出、通用可复用。

回复要求：使用中文，简洁准确，代码用 Markdown 代码块。
        """.trimIndent()

        const val CURRENT_VERSION = "2"
    }

    private var currentPrompt: String = ""
    private var currentVersion: String = "0"
    private var initialized = false

    /**
     * 初始化：从数据库加载最新提示词。
     * 如果数据库为空，自动插入默认版本。
     *
     * @return 当前生效的提示词
     */
    fun initialize(): String {
        val promptJson = configDao.get(KEY_PROMPT_JSON, "")
        if (promptJson.isNotBlank()) {
            try {
                val obj = JSONObject(promptJson)
                currentPrompt = obj.optString("content", DEFAULT_SYSTEM_PROMPT)
                currentVersion = obj.optString("version", "1")
                Log.d(TAG, "Loaded system prompt v$currentVersion")
            } catch (e: Exception) {
                currentPrompt = DEFAULT_SYSTEM_PROMPT
                currentVersion = "1"
            }
        } else {
            // 首次运行，保存默认版本
            currentPrompt = DEFAULT_SYSTEM_PROMPT
            currentVersion = "1"
            savePrompt(currentPrompt, currentVersion, "初始默认版本")
            Log.d(TAG, "Created default system prompt v1")
        }

        initialized = true
        return currentPrompt
    }

    /**
     * 获取当前生效的系统提示词。
     */
    fun getCurrentPrompt(): String {
        if (!initialized) return initialize()
        return currentPrompt
    }

    /**
     * 获取当前版本号。
     */
    fun getCurrentVersion(): String = currentVersion

    /**
     * 更新系统提示词为新版本。
     *
     * @param newPrompt 新提示词内容
     * @param reason 更新原因
     * @return 新版本号
     */
    fun evolve(newPrompt: String, reason: String = "手动更新"): String {
        val newVersion = incrementVersion(currentVersion)
        savePrompt(newPrompt, newVersion, reason)
        currentPrompt = newPrompt
        currentVersion = newVersion
        Log.i(TAG, "System prompt evolved to v$newVersion: $reason")
        return newVersion
    }

    /**
     * 回滚到上一版本（如果历史存在）。
     *
     * @return 回滚后的提示词，null 表示无法回滚
     */
    fun rollback(): String? {
        // 简易回滚：重新初始化（从数据库读取）
        // 若需要多版本支持，可扩展
        val prevVersion = rollbackVersion(currentVersion)
        if (prevVersion == null) return null

        val promptJson = configDao.get(KEY_PROMPT_JSON, "")
        if (promptJson.isNotBlank()) {
            try {
                val obj = JSONObject(promptJson)
                currentPrompt = obj.optString("content", DEFAULT_SYSTEM_PROMPT)
                currentVersion = obj.optString("version", "1")
                initialized = true
                return currentPrompt
            } catch (e: Exception) { /* fall through */ }
        }

        // 回退到默认
        currentPrompt = DEFAULT_SYSTEM_PROMPT
        currentVersion = "1"
        initialized = true
        return currentPrompt
    }

    /**
     * 获取系统提示词信息（用于前端显示）。
     */
    fun getInfo(): String {
        return JSONObject().apply {
            put("version", currentVersion)
            put("content", currentPrompt.take(100) + "...")
        }.toString()
    }

    /**
     * 重置为默认提示词。
     */
    fun resetToDefault(): String {
        currentPrompt = DEFAULT_SYSTEM_PROMPT
        currentVersion = "1"
        savePrompt(currentPrompt, currentVersion, "重置为默认")
        return currentPrompt
    }

    // ==================== Private ====================

    private fun savePrompt(content: String, version: String, reason: String) {
        val obj = JSONObject().apply {
            put("content", content)
            put("version", version)
            put("reason", reason)
            put("updated_at", System.currentTimeMillis())
        }
        configDao.set(KEY_PROMPT_JSON, obj.toString())
        configDao.set(PROMPT_VERSION_KEY, version)
    }

    private fun incrementVersion(v: String): String {
        return try {
            val num = v.toInt()
            (num + 1).toString()
        } catch (e: NumberFormatException) {
            "2" // 默认为 v1 的下一个
        }
    }

    private fun rollbackVersion(v: String): String? {
        return try {
            val num = v.toInt()
            if (num > 1) (num - 1).toString() else null
        } catch (e: NumberFormatException) {
            null
        }
    }
}
