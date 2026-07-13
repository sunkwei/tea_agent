// ⚠️ [废弃] 此 QML 文件已废弃，保留仅为代码参考。
// 请使用 tea_agent.gui2 的 Web 界面（Starlette + SSE）替代。
// 删除日期: 2026-07

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebEngine

ApplicationWindow {
    id: window
    visible: true

    title: "Tea Agent — Qt GUI"
    width: 1200
    height: 800
    minimumWidth: 800
    minimumHeight: 600

    readonly property var t: theme || {}
    readonly property var bridge: backend
    readonly property var md: markdownBridge

    menuBar: MenuBar {
        Menu {
            title: "文件(&F)"
            Action { text: "新建主题"; onTriggered: sidebar.newTopicRequested() }
            MenuSeparator {}
            Action { text: "导出当前对话为 PDF"; onTriggered: exportPdf() }
            MenuSeparator {}
            Action { text: "退出(&Q)"; onTriggered: Qt.quit() }
        }
        Menu {
            title: "视图(&V)"
            Action { text: "放大"; onTriggered: chatView.zoomIn() }
            Action { text: "缩小"; onTriggered: chatView.zoomOut() }
            Action { text: "重置缩放"; onTriggered: chatView.resetZoom() }
            MenuSeparator {}
            Action { text: "切换暗黑模式"; onTriggered: toggleDarkMode() }
        }
        Menu {
            title: "工具(&T)"
            Action { text: "主题管理"; onTriggered: showTopicDialog() }
            Action { text: "记忆管理"; onTriggered: showMemoryDialog() }
            Action { text: "配置编辑"; onTriggered: showConfigDialog() }
        }
        Menu {
            title: "帮助(&H)"
            Action { text: "关于 Tea Agent"; onTriggered: showAbout() }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Sidebar {
            id: sidebar
            Layout.fillHeight: true
            Layout.preferredWidth: t.sidebarWidth || 260
            backend: bridge
            topics: []
            themeColors: t
            onTopicSelected: function(topicId) {
                bridge.load_topic(topicId)
            }
            onNewTopicRequested: {
                bridge.new_topic()
            }
        }

        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: t.dividerColor || "#e8eaed"
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            ChatView {
                id: chatView
                Layout.fillWidth: true
                Layout.fillHeight: true
                markdownBridge: md
                messages: []
                themeColors: t
                onLinkClicked: function(url) {
                    handleLink(url)
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: t.dividerColor || "#e8eaed"
            }

            InputArea {
                id: inputArea
                Layout.fillWidth: true
                Layout.preferredHeight: 90
                Layout.leftMargin: t.spacing || 8
                Layout.rightMargin: t.spacing || 8
                Layout.bottomMargin: t.spacing || 8
                Layout.topMargin: 4
                themeColors: t
                inputEnabled: bridge && !bridge.generating

                onSendRequested: function(text) {
                    if (bridge) {
                        bridge.send_message(text)
                    }
                }
            }
        }
    }

    footer: Rectangle {
        height: 28
        color: t.dividerColor || "#f0f0f0"

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8

            Text {
                id: statusText
                text: bridge ? bridge.statusText : "⏳ 初始化中..."
                font.pixelSize: 11
                color: t.secondaryText || "#5f6368"
                Layout.fillWidth: true
            }

            BusyIndicator {
                implicitWidth: 16
                implicitHeight: 16
                running: bridge ? bridge.generating : false
            }
        }
    }

    Connections {
        target: bridge

        function onMessagesChanged() {
            var msgs = bridge.getMessagesList()
            chatView.messages = msgs
            chatView.renderMessages()
            // 新 HTML 中的流式 div 默认隐藏，无需额外清除
        }

        function onThinkUpdated(text) {
            chatView.updateStreaming(text, "think")
            chatView.scrollToBottom()
        }

        function onStreamUpdated(text) {
            chatView.updateStreaming(text, "ai")
            chatView.scrollToBottom()
        }

        function onStatusChanged(text) {}

        function onTopicsChanged() {
            var newTopics = bridge.getTopicsList()
            sidebar.topics = newTopics
        }

        function onErrorOccurred(msg) {
            showError(msg)
        }

        function onScrollToBottom() {
            chatView.scrollToBottom()
        }
    }

    Shortcut {
        sequence: "Ctrl+Q"
        onActivated: Qt.quit()
    }
    Shortcut {
        sequence: "Ctrl+="
        onActivated: chatView.zoomIn()
    }
    Shortcut {
        sequence: "Ctrl+-"
        onActivated: chatView.zoomOut()
    }
    Shortcut {
        sequence: "Ctrl+0"
        onActivated: chatView.resetZoom()
    }
    Shortcut {
        sequence: "Ctrl+N"
        onActivated: sidebar.newTopicRequested()
    }
    Shortcut {
        sequence: "Escape"
        onActivated: interruptGeneration()
    }

    Component.onCompleted: {
        Qt.callLater(function() {
            if (bridge) {
                bridge.initialize()
            }
        })
    }

    function handleLink(url) {
        if (url.startsWith("http://") || url.startsWith("https://")) {
            Qt.openUrlExternally(url)
        }
    }

    function interruptGeneration() {
        if (bridge) bridge.interrupt()
    }

    function exportPdf() { showNotice("PDF 导出功能待实现") }
    function toggleDarkMode() { showNotice("暗黑模式待实现") }
    function showTopicDialog() { showNotice("主题管理对话框待实现") }
    function showMemoryDialog() { showNotice("记忆管理对话框待实现") }
    function showConfigDialog() { showNotice("配置编辑对话框待实现") }
    function showAbout() { showNotice("Tea Agent v0.10.14\n基于 QML + PySide6 的桌面版") }

    function showError(msg) {
        console.error("Backend error:", msg)
        statusText.text = "❌ " + msg
    }

    Timer {
        id: statusTimer
        interval: 3000
        onTriggered: { statusText.text = bridge ? bridge.statusText : "就绪" }
    }

    function showNotice(msg) {
        console.log("Notice:", msg)
        statusText.text = "ℹ️ " + msg
        statusTimer.restart()
    }
}
