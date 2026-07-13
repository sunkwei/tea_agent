import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebEngine

/**
 * ChatView — 聊天消息视图 (QWebEngineView)。
 *
 * 使用 QWebEngineView 渲染 markdown→HTML 管道生成的完整 HTML 页面，
 * 完美支持 HTML5/CSS3，解决 tkinterweb 的兼容性问题。
 */
Rectangle {
    id: root

    // ── 属性（由父级注入） ─────────────────────
    property var markdownBridge: null
    property var messages: []
    property var themeColors: ({})
    property int zoomLevel: 100
    property bool hasContent: false

    // ── 信号 ──────────────────────────────────
    signal linkClicked(string url)

    // ── 外观 ──────────────────────────────────
    color: themeColors.chatBg || "#ffffff"

    // ── 加载状态 ──────────────────────────────
    Rectangle {
        id: loadingOverlay
        anchors.fill: parent
        color: Qt.rgba(1, 1, 1, 0.85)
        visible: false
        z: 10

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 12

            BusyIndicator {
                Layout.alignment: Qt.AlignHCenter
                running: loadingOverlay.visible
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "🔄 正在渲染..."
                color: themeColors.secondaryText || "#5f6368"
                font.pixelSize: themeColors.bodySize || 14
            }
        }
    }

    // ── 空状态 ────────────────────────────────
    Text {
        id: emptyHint
        anchors.centerIn: parent
        text: "💬 开始一段新的对话\n在下方输入消息..."
        color: themeColors.secondaryText || "#5f6368"
        font.pixelSize: themeColors.bodySize || 14
        horizontalAlignment: Text.AlignHCenter
        lineHeight: 1.6
        visible: !hasContent && !loadingOverlay.visible
    }

    // ── 工具栏 ────────────────────────────────
    Rectangle {
        id: toolBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 36
        color: "#fafafa"
        visible: hasContent
        z: 5

        RowLayout {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 4

            Button {
                text: "A−"
                font.pixelSize: 12
                implicitWidth: 28
                implicitHeight: 24
                flat: true
                onClicked: root.zoomOut()
                background: Rectangle {
                    radius: 3
                    color: parent.hovered ? (themeColors.sidebarHover || "#e8f0fe") : "transparent"
                }
            }

            Text {
                text: zoomLevel + "%"
                font.pixelSize: 11
                color: themeColors.secondaryText || "#5f6368"
                horizontalAlignment: Text.AlignHCenter
                Layout.preferredWidth: 40
            }

            Button {
                text: "A+"
                font.pixelSize: 12
                implicitWidth: 28
                implicitHeight: 24
                flat: true
                onClicked: root.zoomIn()
                background: Rectangle {
                    radius: 3
                    color: parent.hovered ? (themeColors.sidebarHover || "#e8f0fe") : "transparent"
                }
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "↻"
                font.pixelSize: 14
                implicitWidth: 28
                implicitHeight: 24
                flat: true
                ToolTip.visible: hovered
                ToolTip.text: "重新渲染"
                onClicked: root.renderMessages()
                background: Rectangle {
                    radius: 3
                    color: parent.hovered ? (themeColors.sidebarHover || "#e8f0fe") : "transparent"
                }
            }
        }

        Rectangle {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: 1
            color: themeColors.dividerColor || "#e8eaed"
        }
    }

    // ── WebEngineView ────────────────────────
    WebEngineView {
        id: webView
        anchors.top: toolBar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        settings.javascriptEnabled: false
        settings.localContentCanAccessRemoteUrls: false

        onLoadingChanged: function(load) {
            if (load.status === WebEngineView.LoadSucceededStatus) {
                loadingOverlay.visible = false
                hasContent = true
                emptyHint.visible = false
            } else if (load.status === WebEngineView.LoadFailedStatus) {
                console.warn("WebEngineView load failed:", load.errorString)
                loadingOverlay.visible = false
            }
        }

        onNavigationRequested: function(request) {
            var url = request.url.toString()
            if (url.startsWith("tea://")) {
                request.action = WebEngineNavigationRequest.IgnoreRequest
                linkClicked(url)
            } else if (url.startsWith("http://") || url.startsWith("https://")) {
                request.action = WebEngineNavigationRequest.IgnoreRequest
                Qt.openUrlExternally(url)
            }
        }

        onContextMenuRequested: function(request) {
            request.accepted = true
        }
    }

    // ── 公共方法 ──────────────────────────────

    function renderMessages() {
        if (!markdownBridge) return
        if (!messages || messages.length === 0) {
            hasContent = false
            emptyHint.visible = true
            return
        }
        loadingOverlay.visible = true
        var html = markdownBridge.render_messages(messages)
        webView.loadHtml(html, "file:///")
    }

    function renderWithThink(thinkText, msgs) {
        if (!markdownBridge) return
        loadingOverlay.visible = true
        var html = markdownBridge.render_messages_with_think(thinkText, msgs)
        webView.loadHtml(html, "file:///")
    }

    function loadHtml(html) {
        webView.loadHtml(html, "file:///")
        loadingOverlay.visible = false
        hasContent = true
        emptyHint.visible = false
    }

    function scrollToBottom() {
        webView.runJavaScript("window.scrollTo(0, document.body.scrollHeight)")
    }

    function zoomIn() {
        if (zoomLevel < 200) {
            zoomLevel = Math.min(200, zoomLevel + 10)
            if (markdownBridge) {
                markdownBridge.set_zoom(zoomLevel)
                renderMessages()
            }
        }
    }

    function zoomOut() {
        if (zoomLevel > 50) {
            zoomLevel = Math.max(50, zoomLevel - 10)
            if (markdownBridge) {
                markdownBridge.set_zoom(zoomLevel)
                renderMessages()
            }
        }
    }

    function resetZoom() {
        zoomLevel = 100
        if (markdownBridge) {
            markdownBridge.set_zoom(100)
            renderMessages()
        }
    }
}
