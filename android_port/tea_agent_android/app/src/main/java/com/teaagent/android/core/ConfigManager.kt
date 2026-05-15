/*
 * @2026-05-16 gen by tea_agent, ConfigManager — 三模型配置 + 主题管理
 *
 * 存储位置：SQLite config 表 (JSON 序列化)
 */

package com.teaagent.android.core

import com.teaagent.android.db.ConfigDao
import com.teaagent.android.model.AgentConfig
import com.teaagent.android.model.ModelConfig
import org.json.JSONObject

class ConfigManager(private val configDao: ConfigDao) {

    companion object {
        private const val KEY_AGENT_CONFIG = "agent_config_json"
    }

    fun load(): AgentConfig {
        val json = configDao.get(KEY_AGENT_CONFIG, "")
        if (json.isBlank()) return AgentConfig()
        return try {
            val obj = JSONObject(json)
            AgentConfig(
                mainModel = parseModel(obj.optJSONObject("main_model")),
                cheapModel = parseModel(obj.optJSONObject("cheap_model")),
                embeddingModel = parseModel(obj.optJSONObject("embedding_model")),
                keepTurns = obj.optInt("keep_turns", 5),
                maxIterations = obj.optInt("max_iterations", 30),
                enableThinking = obj.optBoolean("enable_thinking", true),
                theme = obj.optString("theme", "dark")
            )
        } catch (e: Exception) {
            AgentConfig()
        }
    }

    fun save(config: AgentConfig) {
        val obj = JSONObject().apply {
            put("main_model", modelToJson(config.mainModel))
            put("cheap_model", modelToJson(config.cheapModel))
            put("embedding_model", modelToJson(config.embeddingModel))
            put("keep_turns", config.keepTurns)
            put("max_iterations", config.maxIterations)
            put("enable_thinking", config.enableThinking)
            put("theme", config.theme)
        }
        configDao.set(KEY_AGENT_CONFIG, obj.toString())
    }

    fun getTheme(): String = load().theme
    fun setTheme(theme: String) {
        val cfg = load()
        cfg.theme = theme
        save(cfg)
    }

    private fun parseModel(obj: JSONObject?): ModelConfig {
        if (obj == null) return ModelConfig("")
        return ModelConfig(
            id = obj.optString("id", ""),
            apiUrl = obj.optString("api_url", "http://10.0.2.2:11434/v1"),
            apiKey = obj.optString("api_key", ""),
            modelName = obj.optString("model_name", ""),
            maxTokens = obj.optInt("max_tokens", 4096),
            temperature = obj.optDouble("temperature", 0.7).toFloat()
        )
    }

    private fun modelToJson(m: ModelConfig) = JSONObject().apply {
        put("id", m.id)
        put("api_url", m.apiUrl)
        put("api_key", m.apiKey)
        put("model_name", m.modelName)
        put("max_tokens", m.maxTokens)
        put("temperature", m.temperature.toDouble())
    }
}
