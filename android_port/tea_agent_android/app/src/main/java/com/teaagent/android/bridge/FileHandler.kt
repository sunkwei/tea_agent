/*
 * @2026-05-16 gen by tea_agent, FileHandler — 文件 & 通知
 */

package com.teaagent.android.bridge

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.os.Environment
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import java.io.File

object FileHandler {

    private const val CHANNEL_ID = "tea_agent"

    fun readFile(context: Context, path: String): String {
        val file = resolveFile(context, path)
        return if (file.exists()) file.readText(Charsets.UTF_8)
        else """{"error":"文件不存在"}"""
    }

    fun writeFile(context: Context, path: String, content: String): Boolean {
        return try {
            resolveFile(context, path).also {
                it.parentFile?.mkdirs()
                it.writeText(content, Charsets.UTF_8)
            }
            true
        } catch (_: Exception) { false }
    }

    fun listDir(context: Context, dirPath: String): String {
        val dir = resolveFile(context, dirPath)
        if (!dir.isDirectory) return """{"error":"不是目录"}"""
        return JSONArray().apply {
            dir.listFiles()?.forEach { f ->
                put(org.json.JSONObject().apply {
                    put("name", f.name); put("is_dir", f.isDirectory)
                    put("size", f.length()); put("modified", f.lastModified())
                })
            }
        }.toString()
    }

    private fun resolveFile(context: Context, path: String): File = when {
        path.startsWith("~/") -> File(context.filesDir, path.removePrefix("~/"))
        path.startsWith("/") -> File(path)
        else -> File(context.filesDir, path)
    }

    fun showNotification(context: Context, title: String, message: String) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "TeaAgent", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
        manager.notify(
            System.currentTimeMillis().toInt(),
            NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title).setContentText(message)
                .setAutoCancel(true).build()
        )
    }
}
