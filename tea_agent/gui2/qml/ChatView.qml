// ⚠️ [废弃] 此 QML 文件已废弃，保留仅为代码参考。
// 请使用 tea_agent.gui2 的 Web 界面替代。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebEngine

Rectangle {
    id: root

    property var markdownBridge: null
    property var messages: []
    property var themeColors: ({})
    property int zoomLevel: 100
    property bool hasContent: false
    property string streamContent: ""
    property string streamRole: ""
    property bool _pendingScroll: false

    signal linkClicked(string url)

    // 页面加载完成后若有待滚标志则自动滚到底
    function _onPageLoaded() {
        loadingOverlay.visible = false
        hasContent = true
        emptyHint.visible = false
        if (_pendingScroll) {
            _pendingScroll = false
            scrollToBottom()
        }
    }

    color: themeColors.chatBg || "#ffffff"

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
                id: zoomOutBtn
                text: "A−"
                font.pixelSize: 13
                font.bold: true
                implicitWidth: 32
                implicitHeight: 26
                onClicked: root.zoomOut()
                background: Rectangle {
                    radius: 4
                    color: zoomOutBtn.hovered ? (themeColors.sidebarHover || "#e8f0fe") : "transparent"
                    border.width: 1
                    border.color: zoomOutBtn.hovered ? (themeColors.borderColor || "#dadce0") : "transparent"
                }
                contentItem: Text {
                    text: zoomOutBtn.text
                    color: themeColors.primaryText || "#202124"
                    font: zoomOutBtn.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Text {
                text: zoomLevel + "%"
                font.pixelSize: 11
                font.bold: true
                color: themeColors.secondaryText || "#5f6368"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                Layout.preferredWidth: 40
                Layout.minimumWidth: 40
            }

            Button {
                id: zoomInBtn
                text: "A+"
                font.pixelSize: 13
                font.bold: true
                implicitWidth: 32
                implicitHeight: 26
                onClicked: root.zoomIn()
                background: Rectangle {
                    radius: 4
                    color: zoomInBtn.hovered ? (themeColors.sidebarHover || "#e8f0fe") : "transparent"
                    border.width: 1
                    border.color: zoomInBtn.hovered ? (themeColors.borderColor || "#dadce0") : "transparent"
                }
                contentItem: Text {
                    text: zoomInBtn.text
                    color: themeColors.primaryText || "#202124"
                    font: zoomInBtn.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Item { Layout.fillWidth: true }

            Button {
                id: refreshBtn
                text: "↻"
                font.pixelSize: 15
                implicitWidth: 32
                implicitHeight: 26
                ToolTip.visible: hovered
                ToolTip.text: "重新渲染"
                onClicked: root.renderMessages()
                background: Rectangle {
                    radius: 4
                    color: refreshBtn.hovered ? (themeColors.sidebarHover || "#e8f0fe") : "transparent"
                    border.width: 1
                    border.color: refreshBtn.hovered ? (themeColors.borderColor || "#dadce0") : "transparent"
                }
                contentItem: Text {
                    text: refreshBtn.text
                    color: themeColors.primaryText || "#202124"
                    font: refreshBtn.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
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

    // ── 主内容区（WebView + 流式浮层） ──

    Item {
        anchors.top: toolBar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true

        WebEngineView {
            id: webView
            anchors.fill: parent

            settings.javascriptEnabled: true
            settings.localContentCanAccessRemoteUrls: false
            settings.errorPageEnabled: false

            onLoadingChanged: function(load) {
                if (load.status === WebEngineView.LoadSucceededStatus) {
                    root._onPageLoaded()
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

        // ── 流式生成浮层（覆盖在 WebView 底部） ──
        Rectangle {
            id: streamBanner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: false
            height: Math.min(streamScroll.contentHeight + 32, parent.height * 0.5)
            color: streamRole === "think" ? "#fff8e1" : "#f0f7ff"
            z: 20

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 2
                color: streamRole === "think" ? "#f9a825" : "#1976d2"
            }

            Flickable {
                id: streamScroll
                anchors.fill: parent
                anchors.margins: 12
                contentHeight: streamLabel.height + streamBody.height + 8
                flickableDirection: Flickable.VerticalFlick
                clip: true

                Column {
                    id: streamCol
                    width: parent.width
                    spacing: 4

                    Row {
                        spacing: 6

                        Text {
                            id: streamIcon
                            text: streamRole === "think" ? "💭" : "🤖"
                            font.pixelSize: 16
                        }

                        Text {
                            id: streamLabel
                            text: streamRole === "think" ? "思考中..." : "生成中..."
                            font.pixelSize: 13
                            font.bold: true
                            color: streamRole === "think" ? "#e65100" : "#1565c0"
                        }
                    }

                    Text {
                        id: streamBody
                        width: parent.width
                        text: streamContent
                        font.pixelSize: 14
                        color: themeColors.primaryText || "#202124"
                        wrapMode: Text.WordWrap
                        textFormat: Text.MarkdownText
                    }
                }
            }
        }
    }

    // ── 渲染 ──

    function renderMessages() {
        if (!markdownBridge) return
        if (!messages || messages.length === 0) {
            hasContent = false
            emptyHint.visible = true
            streamContent = ""
            streamBanner.visible = false
            return
        }
        loadingOverlay.visible = true
        streamContent = ""
        streamBanner.visible = false
        _pendingScroll = true  // 标记需要加载后自动滚动
        var html = markdownBridge.render_messages(messages)
        webView.loadHtml(html, "file:///")
    }

    function renderWithThink(thinkText, msgs) {
        if (!markdownBridge) return
        loadingOverlay.visible = true
        _pendingScroll = true
        var html = markdownBridge.render_messages_with_think(thinkText, msgs)
        webView.loadHtml(html, "file:///")
    }

    function loadHtml(html) {
        webView.loadHtml(html, "file:///")
        loadingOverlay.visible = false
        hasContent = true
        emptyHint.visible = false
    }

    // ── 流式更新 ──

    function updateStreaming(text, role) {
        streamContent = text
        streamRole = role
        if (!text) {
            streamBanner.visible = false
            return
        }
        streamBanner.visible = true
        streamScroll.contentY = Math.max(0, streamScroll.contentHeight - streamScroll.height)
    }

    function clearStreaming() {
        streamContent = ""
        streamRole = ""
        streamBanner.visible = false
    }

    function scrollToBottom() {
        webView.runJavaScript('window.scrollTo(0, document.body.scrollHeight)')
    }

    // ── 缩放 ──

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
