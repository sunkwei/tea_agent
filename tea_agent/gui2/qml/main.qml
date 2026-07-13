import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebEngine

/**
 * main.qml — 主窗口。
 *
 * ApplicationWindow 容器，组装 Sidebar + ChatView + InputArea。
 * 所有 Python 后端对象通过 context properties 注入：
 *   - backend: BackendBridge
 *   - markdownBridge: MarkdownBridge
 *   - theme: ThemeObject (Python QObject, 颜色/字体/尺寸)
 */
ApplicationWindow {
    id: window
    visible: true

    // ── 窗口属性 ──────────────────────────────
    title: "Tea Agent — Qt GUI"
    width: 1200
    height: 800
    minimumWidth: 800
    minimumHeight: 600

    // ── 从 context 读取 theme（主窗口可直接访问 context property） ──
    readonly property var t: theme || {}

    // ── 菜单栏 ────────────────────────────────
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

    // ── 主布局 ────────────────────────────────
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── 左侧：主题侧栏 ────────────────────
        Sidebar {
            id: sidebar
            Layout.fillHeight: true
            Layout.preferredWidth: t.sidebarWidth || 260
            backend: backend
            topics: backend ? backend.topics : []
            // 手动注入 theme 值
            themeColors: t
            onTopicSelected: function(topicId) {
                backend.load_topic(topicId)
            }
            onNewTopicRequested: {
                backend.new_topic()
            }
        }

        // ── 分割线 ────────────────────────────
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: t.dividerColor || "#e8eaed"
        }

        // ── 右侧：聊天区域 ────────────────────
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // 聊天视图
            ChatView {
                id: chatView
                Layout.fillWidth: true
                Layout.fillHeight: true
                markdownBridge: markdownBridge
                messages: backend ? backend.messages : []
                themeColors: t
                onLinkClicked: function(url) {
                    handleLink(url)
                }
            }

            // 分割线
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: t.dividerColor || "#e8eaed"
            }

            // 输入区（固定高度）
            InputArea {
                id: inputArea
                Layout.fillWidth: true
                Layout.preferredHeight: 90
                Layout.leftMargin: t.spacing || 8
                Layout.rightMargin: t.spacing || 8
                Layout.bottomMargin: t.spacing || 8
                Layout.topMargin: 4
                themeColors: t
                inputEnabled: backend && !backend.generating

                onSendRequested: function(text) {
                    if (backend) {
                        backend.send_message(text)
                    }
                }
            }
        }
    }

    // ── 底部状态栏 ────────────────────────────
    footer: Rectangle {
        height: 28
        color: t.dividerColor || "#f0f0f0"

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8

            Text {
                id: statusText
                text: backend ? backend.statusText : "⏳ 初始化中..."
                font.pixelSize: 11
                color: t.secondaryText || "#5f6368"
                Layout.fillWidth: true
            }

            BusyIndicator {
                implicitWidth: 16
                implicitHeight: 16
                running: backend ? backend.generating : false
            }
        }
    }

    // ── 信号连接 ──────────────────────────────
    Connections {
        target: backend

        function onMessagesChanged() {
            chatView.messages = backend.get_messages()
            chatView.renderMessages()
        }

        function onThinkUpdated(text) {
            if (chatView.hasContent) {
                chatView.renderWithThink(text, backend.get_messages())
            }
        }

        function onStatusChanged(text) {
            // statusText 通过绑定自动更新
        }

        function onTopicsChanged() {
            // sidebar 的 topics 通过绑定自动更新
        }

        function onErrorOccurred(msg) {
            showError(msg)
        }

        function onScrollToBottom() {
            chatView.scrollToBottom()
        }
    }

    // ── 快捷键 ────────────────────────────────
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

    // ── 初始化 ────────────────────────────────
    Component.onCompleted: {
        Qt.callLater(function() {
            if (backend) {
                backend.initialize()
            }
        })
    }

    // ── 方法 ──────────────────────────────────

    function handleLink(url) {
        if (url.startsWith("tea://latest")) {
            console.log("Navigate to latest round")
        } else if (url.startsWith("tea://round/")) {
            var roundIdx = parseInt(url.substring("tea://round/".length))
            console.log("Navigate to round:", roundIdx)
        } else {
            Qt.openUrlExternally(url)
        }
    }

    function interruptGeneration() {
        if (backend) backend.interrupt()
    }

    function exportPdf() {
        showNotice("PDF 导出功能待实现")
    }

    function toggleDarkMode() {
        showNotice("暗黑模式待实现")
    }

    function showTopicDialog() {
        showNotice("主题管理对话框待实现")
    }

    function showMemoryDialog() {
        showNotice("记忆管理对话框待实现")
    }

    function showConfigDialog() {
        showNotice("配置编辑对话框待实现")
    }

    function showAbout() {
        showNotice("Tea Agent v0.10.14\n基于 QML + PySide6 的桌面版")
    }

    function showError(msg) {
        console.error("Backend error:", msg)
        statusText.text = "❌ " + msg
    }

    Timer {
        id: statusTimer
        interval: 3000
        onTriggered: {
            statusText.text = backend ? backend.statusText : "就绪"
        }
    }

    function showNotice(msg) {
        console.log("Notice:", msg)
        statusText.text = "ℹ️ " + msg
        statusTimer.restart()
    }
}
