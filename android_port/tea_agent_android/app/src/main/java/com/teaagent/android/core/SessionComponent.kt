/*
 * @2026-06-04 gen by tea_agent, SessionComponent — 会话组件基类
 *
 * 所有会话组件的统一接口，对齐桌面版 SessionComponent。
 * 每个组件通过 context 访问共享状态。
 */

package com.teaagent.android.core

/**
 * 会话组件基类。
 * 
 * 所有组件的统一接口。每个组件通过构造函数接收 SessionContext，
 * 在 execute() 中实现具体业务逻辑。
 */
abstract class SessionComponent(protected val ctx: SessionContext) {

    /** 组件名称，用于日志和调试 */
    abstract val name: String

    /**
     * 组件初始化。
     * 在 Pipeline 启动时调用。
     */
    open fun initialize() {}

    /**
     * 组件销毁。
     * 在 Pipeline 停止时调用。
     */
    open fun destroy() {}
}
