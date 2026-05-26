/*
 * @2026-05-16 gen by tea_agent, MainActivity — 入口
 */

package com.teaagent.android

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.teaagent.android.api.ApiClient
import com.teaagent.android.bridge.JsBridge
import com.teaagent.android.core.ConfigManager
import com.teaagent.android.core.HistoryCompressor
import com.teaagent.android.core.ToolManager
import com.teaagent.android.db.*

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    companion object {
        private const val REQUEST_LOCATION = 1001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // 请求位置权限
        requestLocationPermission()

        // DB
        val db = AppDatabase(this)
        val wDb = db.writableDatabase
        val configManager = ConfigManager(ConfigDao(wDb))
        val messageDao = MessageDao(wDb)
        val toolDao = ToolDao(wDb)

        // WebView
        webView = findViewById(R.id.webview)
        AgentWebView.setup(webView)

        // Core — init 会清理 SQLite 中的 toolkit_mgrt/reload，确保不被 LLM 修改
        val toolManager = ToolManager(toolDao, webView)
        toolManager.init()
        val historyCompressor = HistoryCompressor(messageDao)

        // API
        val apiClient = ApiClient(messageDao, toolManager, historyCompressor)

        // Bridge
        val jsBridge = JsBridge(this, webView, db, apiClient, configManager, toolManager)
        webView.addJavascriptInterface(jsBridge, "TeaNative")

        // 加载前端
        webView.loadUrl("file:///android_asset/web/index.html")
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
