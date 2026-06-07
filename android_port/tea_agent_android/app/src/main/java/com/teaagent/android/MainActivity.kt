/*
 * @2026-06-04 gen by tea_agent, MainActivity — 入口
 * @2026-06-04 refactor: 集成 ToolComponent + PromptManager + SessionContext
 */

package com.teaagent.android

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.teaagent.android.api.ApiClient
import com.teaagent.android.bridge.JsBridge
import com.teaagent.android.core.*
import com.teaagent.android.db.*

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    companion object {
        private const val REQUEST_LOCATION = 1001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        requestLocationPermission()

        // DB
        val db = AppDatabase(this)
        val wDb = db.writableDatabase
        val configDao = ConfigDao(wDb)
        val configManager = ConfigManager(configDao)
        val messageDao = MessageDao(wDb)
        val toolDao = ToolDao(wDb)

        // WebView
        webView = findViewById(R.id.webview)
        AgentWebView.setup(webView)

        // ── 新架构组件 ──

        // PromptManager（版本化系统提示词）
        val promptManager = PromptManager(configDao)
        promptManager.initialize()
        Log.d("MainActivity", "Prompt v${promptManager.getCurrentVersion()} loaded")

        // MemoryManager（长期记忆）
        val memoryManager = MemoryManager(wDb)
        Log.d("MainActivity", "MemoryManager initialized")

        // SelfEvolveManager（自我进化）
        val selfEvolveManager = SelfEvolveManager(wDb, toolDao, configDao, promptManager)
        selfEvolveManager.init()
        Log.d("MainActivity", "SelfEvolveManager initialized")

        // ToolComponent（统一工具系统，集成 MemoryManager 和 SelfEvolveManager）
        val toolComponent = ToolComponent(toolDao, webView, memoryManager, selfEvolveManager)
        toolComponent.init()
        Log.d("MainActivity", "ToolComponent initialized: ${toolComponent.getToolNames().size} tools")

        // HistoryCompressor（历史压缩）
        val historyCompressor = HistoryCompressor(messageDao)

        // ApiClient（聊天引擎，使用 ToolComponent）
        val apiClient = ApiClient(messageDao, toolComponent, historyCompressor)

        // SessionContext（共享上下文）
        val sessionCtx = SessionContext().apply {
            this.database = db
            this.webView = this@MainActivity.webView
            this.toolComponent = toolComponent
            this.historyCompressor = historyCompressor
            this.promptManager = promptManager
        }

        // Bridge（JS ↔ Kotlin，使用 ToolComponent 替代旧 ToolManager）
        val jsBridge = JsBridge(this, webView, db, apiClient, configManager, toolComponent)
        webView.addJavascriptInterface(jsBridge, "TeaNative")

        // 加载前端
        webView.loadUrl("file:///android_asset/web/index.html")

        Log.i("MainActivity", "TeaAgent Android v0.3.0 started")
    }

    override fun onDestroy() {
        super.onDestroy()
        // 清理 WebView
        webView.destroy()
    }

    private fun requestLocationPermission() {
        val permissions = arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        )
        val needRequest = permissions.any {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (needRequest) {
            ActivityCompat.requestPermissions(this, permissions, REQUEST_LOCATION)
        }
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }
}
