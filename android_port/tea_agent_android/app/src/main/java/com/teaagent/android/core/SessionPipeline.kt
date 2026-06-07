/*
 * @2026-06-04 gen by tea_agent, SessionPipeline — 会话 Pipeline 管理器
 *
 * 管理对话流程的步骤，对齐桌面版 session_pipeline.py。
 * 支持：
 * - 注册/启用/禁用步骤
 * - 按顺序执行步骤
 * - 跳过步骤
 * - 组件生命周期管理
 */

package com.teaagent.android.core

import android.util.Log

/**
 * Pipeline 步骤定义
 */
data class PipelineStep(
    /** 步骤名称（唯一标识） */
    val name: String,
    /** 执行函数，返回 true=继续，false=跳过后续步骤 */
    val execute: suspend () -> Boolean,
    /** 是否启用 */
    var enabled: Boolean = true,
    /** 步骤描述 */
    val description: String = "",
    /** 执行顺序（越小越先执行） */
    val position: Int = 0
)

/**
 * 会话 Pipeline 管理器。
 * 
 * 管理对话流程的步骤序列，支持动态启用/禁用和组件生命周期。
 * 对齐桌面版 SessionPipeline。
 */
class SessionPipeline(private val ctx: SessionContext) {

    companion object {
        private const val TAG = "SessionPipeline"
    }

    private val steps = mutableMapOf<String, PipelineStep>()
    private val stepOrder = mutableListOf<String>()
    private val components = mutableListOf<SessionComponent>()

    // ==================== 组件管理 ====================

    /**
     * 注册一个组件。组件中的步骤可以通过 registerStep 添加。
     */
    fun registerComponent(component: SessionComponent) {
        if (components.any { it.name == component.name }) {
            Log.w(TAG, "Component '${component.name}' already registered, skipping")
            return
        }
        components.add(component)
        component.initialize()
        Log.d(TAG, "Component '${component.name}' initialized")
    }

    /**
     * 启动 Pipeline：初始化所有已注册组件。
     */
    fun start() {
        for (component in components) {
            component.initialize()
        }
        Log.d(TAG, "Pipeline started with ${components.size} components, ${steps.size} steps")
    }

    /**
     * 停止 Pipeline：销毁所有组件。
     */
    fun stop() {
        for (component in components.reversed()) {
            try {
                component.destroy()
            } catch (e: Exception) {
                Log.e(TAG, "Error destroying component '${component.name}'", e)
            }
        }
        components.clear()
        steps.clear()
        stepOrder.clear()
        Log.d(TAG, "Pipeline stopped")
    }

    // ==================== 步骤管理 ====================

    /**
     * 注册一个 Pipeline 步骤。
     * 
     * @param name 步骤名称（唯一标识）
     * @param execute 执行函数
     * @param enabled 是否启用
     * @param description 步骤描述
     * @param position 执行顺序（越小越先执行）
     * @param before 在哪个步骤之前执行（可选）
     * @param after 在哪个步骤之后执行（可选）
     */
    fun registerStep(
        name: String,
        execute: suspend () -> Boolean,
        enabled: Boolean = true,
        description: String = "",
        position: Int = 0,
        before: String? = null,
        after: String? = null
    ) {
        if (name in steps) {
            Log.w(TAG, "Step '$name' already exists, skipping")
            return
        }

        val step = PipelineStep(
            name = name,
            execute = execute,
            enabled = enabled,
            description = description,
            position = position
        )
        steps[name] = step

        // 插入到正确的位置
        when {
            before != null && before in stepOrder -> {
                val idx = stepOrder.indexOf(before)
                stepOrder.add(idx, name)
            }
            after != null && after in stepOrder -> {
                val idx = stepOrder.indexOf(after)
                stepOrder.add(idx + 1, name)
            }
            else -> stepOrder.add(name)
        }

        // 按 position 排序
        stepOrder.sortBy { steps[it]?.position ?: 0 }
    }

    /**
     * 启用指定步骤。
     */
    fun enableStep(name: String) {
        steps[name]?.let { it.enabled = true }
    }

    /**
     * 禁用指定步骤。
     */
    fun disableStep(name: String) {
        steps[name]?.let { it.enabled = false }
    }

    /**
     * 获取启用的步骤列表。
     */
    fun getEnabledSteps(): List<PipelineStep> {
        return stepOrder
            .mapNotNull { steps[it] }
            .filter { it.enabled }
    }

    // ==================== 执行 ====================

    /**
     * 执行 Pipeline 中的所有启用的步骤。
     * 
     * @param fromStep 从指定步骤开始执行（可选）
     * @return true=全部完成, false=被跳过中断
     */
    suspend fun execute(fromStep: String? = null): Boolean {
        val enabledSteps = getEnabledSteps()
        val startIdx = if (fromStep != null) {
            enabledSteps.indexOfFirst { it.name == fromStep }.coerceAtLeast(0)
        } else 0

        for (i in startIdx until enabledSteps.size) {
            val step = enabledSteps[i]
            Log.d(TAG, "→ Executing step: ${step.name}")

            try {
                val shouldContinue = step.execute()
                if (!shouldContinue) {
                    Log.d(TAG, "  ↪ Step '${step.name}' requested to stop pipeline")
                    return false
                }
            } catch (e: Exception) {
                Log.e(TAG, "  ❌ Step '${step.name}' failed: ${e.message}")
                return false
            }
        }

        return true
    }

    /**
     * 重新执行从指定步骤开始的 Pipeline。
     * 用于工具调用循环中重新执行 AI 推理步骤。
     */
    suspend fun reexecute(fromStep: String): Boolean {
        return execute(fromStep)
    }

    // ==================== 查询 ====================

    fun hasStep(name: String): Boolean = name in steps

    fun getStep(name: String): PipelineStep? = steps[name]

    fun getSteps(): List<PipelineStep> = stepOrder.mapNotNull { steps[it] }

    fun getComponents(): List<SessionComponent> = components.toList()
}
