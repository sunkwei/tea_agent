/*
 * @2026-06-04 gen by tea_agent, SelfEvolveManager — 自我进化管理器
 *
 * 轻量级自我进化能力（Android 版）。
 * 支持：
 * - 工具代码备份和回滚
 * - 系统提示词版本管理
 * - 简单安全校验
 *
 * 对齐桌面版 toolkit_self_evolve 的 mini 版本。
 */

package com.teaagent.android.core

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.util.Log
import com.teaagent.android.db.ConfigDao
import com.teaagent.android.db.ToolDao
import com.teaagent.android.model.Tool
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * 自我进化管理器。
 *
 * 管理 Agent 的自我修改能力：
 * - 工具代码版本化备份
 * - 安全回滚
 * - 轻量级代码校验
 */
class SelfEvolveManager(
    private val db: SQLiteDatabase,
    private val toolDao: ToolDao,
    private val configDao: ConfigDao,
    private val promptManager: PromptManager? = null
) {

    companion object {
        private const val TAG = "SelfEvolve"
        private const val BACKUP_PREFIX = "tool_backup_"
        private const val KEY_EVOLVE_LOG = "self_evolve_log"
    }

    fun init() {
        val toolCount = toolDao.count()
        Log.i(TAG, "SelfEvolve initialized: $toolCount tools available")
        for (t in toolDao.listAll()) {
            Log.d(TAG, "  tool: ${t.name} (v${t.updatedAt})")
        }
    }

    // ==================== 工具代码进化 ====================

    fun evolveTool(name: String, newJsCode: String, reason: String = ""): JSONObject {
        val result = JSONObject()
        try {
            val existing = toolDao.getByName(name)
            if (existing == null) {
                result.put("ok", false); result.put("error", "工具 '$name' 不存在")
                return result
            }

            // 备份旧代码
            val backupKey = "${BACKUP_PREFIX}${name}_${existing.updatedAt}"
            val backupValue = JSONObject().apply {
                put("js_code", existing.jsCode); put("meta", existing.meta ?: "")
                put("backed_at", System.currentTimeMillis()); put("reason", reason)
            }.toString()
            configDao.set(backupKey, backupValue)

            // 更新
            toolDao.update(existing.copy(jsCode = newJsCode, updatedAt = System.currentTimeMillis()))

            // 日志
            appendEvolveLog("evolve_tool", mapOf("tool" to name, "reason" to reason))

            Log.i(TAG, "Tool '$name' evolved: ${reason.take(100)}")
            result.put("ok", true); result.put("name", name); result.put("action", "evolved")
        } catch (e: Exception) {
            Log.e(TAG, "Evolve tool error", e)
            result.put("ok", false); result.put("error", e.message)
        }
        return result
    }

    fun rollbackTool(name: String): JSONObject {
        val result = JSONObject()
        try {
            // 查找最近的备份
            val latestKey = getLatestBackupKey(name)
            if (latestKey == null) {
                result.put("ok", false); result.put("error", "没有发现 '$name' 的备份")
                return result
            }

            val backupJson = configDao.get(latestKey, "")
            if (backupJson.isBlank()) {
                result.put("ok", false); result.put("error", "备份数据损坏")
                return result
            }

            val backup = JSONObject(backupJson)
            val oldJsCode = backup.optString("js_code", "")
            val oldMeta = backup.optString("meta", "")
            if (oldJsCode.isBlank()) {
                result.put("ok", false); result.put("error", "备份代码为空")
                return result
            }

            val existing = toolDao.getByName(name)
            if (existing != null) {
                toolDao.update(existing.copy(jsCode = oldJsCode, meta = oldMeta, updatedAt = System.currentTimeMillis()))
            }
            configDao.delete(latestKey)
            Log.i(TAG, "Tool '$name' rolled back")
            result.put("ok", true); result.put("name", name); result.put("action", "rolled_back")
        } catch (e: Exception) {
            result.put("ok", false); result.put("error", e.message)
        }
        return result
    }

    // ==================== 提示词进化 ====================

    fun evolvePrompt(newPrompt: String, reason: String = ""): JSONObject {
        val result = JSONObject()
        try {
            promptManager?.let {
                val version = it.evolve(newPrompt, reason)
                result.put("ok", true); result.put("version", version)
                result.put("action", "prompt_evolved")
            } ?: run {
                result.put("ok", false); result.put("error", "PromptManager 未初始化")
            }
        } catch (e: Exception) {
            result.put("ok", false); result.put("error", e.message)
        }
        return result
    }

    // ==================== 状态查询 ====================

    fun getStatus(): JSONObject = JSONObject().apply {
        put("tool_count", toolDao.count())
        put("prompt_version", promptManager?.getCurrentVersion() ?: "N/A")
    }

    fun validateJsCode(jsCode: String): JSONObject {
        val warnings = mutableListOf<String>()
        val dangerous = listOf(
            "XMLHttpRequest" to "不推荐直接使用 XMLHttpRequest",
            "document.cookie" to "注意 Cookie 访问可能受限",
            "localStorage" to "注意：localStorage 可能与其他页面共享"
        )
        for ((pattern, warning) in dangerous) {
            if (jsCode.contains(pattern, ignoreCase = true)) warnings.add(warning)
        }
        return JSONObject().apply {
            put("ok", warnings.isEmpty())
            put("warnings", JSONObject().apply {
                warnings.forEachIndexed { i, w -> put(i.toString(), w) }
            })
            put("length", jsCode.length)
            put("has_function", jsCode.trimStart().startsWith("function"))
        }
    }

    // ==================== Private ====================

    private fun getLatestBackupKey(name: String): String? {
        db.rawQuery(
            "SELECT key FROM config WHERE key LIKE ? ORDER BY key DESC LIMIT 1",
            arrayOf("${BACKUP_PREFIX}${name}_%")
        ).use { cursor ->
            if (cursor.moveToFirst()) return cursor.getString(0)
        }
        return null
    }

    private fun appendEvolveLog(action: String, data: Map<String, String>) {
        val logStr = configDao.get(KEY_EVOLVE_LOG, "[]")
        val arr = try { JSONArray(logStr) } catch (e: Exception) { JSONArray() }
        arr.put(JSONObject().apply {
            put("action", action); put("timestamp", System.currentTimeMillis())
            data.forEach { (k, v) -> put(k, v) }
        })
        // 只保留最近 100 条
        while (arr.length() > 100) arr.remove(0)
        configDao.set(KEY_EVOLVE_LOG, arr.toString())
    }
}
