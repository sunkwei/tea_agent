/*
 * @2026-05-16 gen by tea_agent, 数据模型
 */

package com.teaagent.android.model

data class Topic(
    val id: String,          // UUID
    val title: String,
    val createdAt: Long,     // epoch millis
    val updatedAt: Long,
    val isDead: Boolean = false   // false=活跃, true=已标记死亡（不显示）
)

data class Message(
    val id: String,          // UUID
    val topicId: String,
    val role: String,        // "user" | "assistant" | "system" | "tool"
    val content: String? = null,
    val toolCalls: String? = null,  // JSON array
    val toolCallId: String? = null,
    val tokenCount: Int = 0,
    val promptTokens: Int = 0,
    val completionTokens: Int = 0,
    val createdAt: Long
)

data class Tool(
    val id: String,
    val name: String,
    val meta: String?,       // JSON: OpenAI tool schema
    val jsCode: String,      // JS 函数体
    val createdAt: Long,
    val updatedAt: Long
)

data class AgentConfig(
    // 三种模型
    var mainModel: ModelConfig = ModelConfig("main"),
    var cheapModel: ModelConfig = ModelConfig("cheap"),
    var embeddingModel: ModelConfig = ModelConfig("embedding"),
    // 会话参数
    var keepTurns: Int = 5,
    var maxIterations: Int = 30,
    var enableThinking: Boolean = true,
    var theme: String = "dark"  // "dark" | "light"
)

data class ModelConfig(
    val id: String,
    var apiUrl: String = "http://10.0.2.2:11434/v1",
    var apiKey: String = "",
    var modelName: String = "",
    var maxTokens: Int = 4096,
    var temperature: Float = 0.7f
)
