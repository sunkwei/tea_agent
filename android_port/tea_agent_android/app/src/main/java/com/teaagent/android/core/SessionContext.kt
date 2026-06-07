/*
 * @2026-06-04 gen by tea_agent, SessionContext — 会话共享上下文
 *
 * 封装所有组件间的共享状态，对齐桌面版 session_context.py。
 * 替代通过构造函数传递多个依赖的方式。
 */

package com.teaagent.android.core

import android.webkit.WebView
import com.teaagent.android.db.AppDatabase

/**
 * 会话共享上下文。
 * 
 * 封装所有会话组件间的共享状态，由 SessionPipeline 统一管理。
 */
class SessionContext {

    // ── 数据库 ──
    var database: AppDatabase? = null
    var webView: WebView? = null

    // ── 组件实例（由 Pipeline 管理） ──
    var toolComponent: ToolComponent? = null
    var historyCompressor: HistoryCompressor? = null
    var promptManager: PromptManager? = null

    // ── 运行时状态 ──
    var currentTopicId: String = ""
    var currentModelConfig: String = ""  // JSON string of active model config
    var systemPrompt: String = ""

    // ── 回调 ──
    var onToken: ((String) -> Unit)? = null
    var onThinking: ((String) -> Unit)? = null
    var onToolCall: ((String) -> Unit)? = null
    var onDone: ((String, Int, Int, Int) -> Unit)? = null
    var onError: ((String) -> Unit)? = null

    // ── 统计 ──
    var totalTokens: Int = 0
    var totalPromptTokens: Int = 0
    var totalCompletionTokens: Int = 0
}
