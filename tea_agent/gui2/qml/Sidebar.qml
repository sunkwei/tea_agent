import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/**
 * Sidebar — 主题列表侧栏。
 *
 * 显示所有聊天主题，支持选中、搜索、新建。
 */
Rectangle {
    id: root

    // ── 属性（由父级注入） ─────────────────────
    property var topics: []
    property var backend: null
    property var themeColors: ({})

    // ── 信号 ──────────────────────────────────
    signal topicSelected(string topicId)
    signal newTopicRequested()

    // ── 外观 ──────────────────────────────────
    color: themeColors.sidebarBg || "#ffffff"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── 标题 ──────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: "transparent"

            RowLayout {
                anchors.fill: parent
                anchors.margins: themeColors.padding || 12
                spacing: themeColors.spacing || 8

                Text {
                    text: "💬 茶 Agent"
                    font.pixelSize: themeColors.headingSize || 15
                    font.bold: true
                    color: themeColors.primaryText || "#202124"
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: "✕"
                    font.pixelSize: 16
                    flat: true
                    opacity: 0.6
                    onClicked: Qt.quit()
                    background: null
                    contentItem: Text {
                        text: parent.text
                        color: themeColors.secondaryText || "#5f6368"
                        font: parent.font
                    }
                }
            }
        }

        // ── 分割线 ────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: themeColors.dividerColor || "#e8eaed"
        }

        // ── 新建主题按钮 ──────────────────────
        Button {
            Layout.fillWidth: true
            Layout.margins: themeColors.spacing || 8
            text: "✏️ 新建主题"
            font.pixelSize: themeColors.smallSize || 12

            background: Rectangle {
                radius: themeColors.smallRadius || 4
                color: parent.hovered
                    ? (themeColors.sidebarHover || "#e8f0fe")
                    : "transparent"
                border.color: themeColors.borderColor || "#dadce0"
                border.width: 1
            }

            onClicked: newTopicRequested()
        }

        // ── 搜索框 ────────────────────────────
        TextField {
            id: searchField
            Layout.fillWidth: true
            Layout.leftMargin: themeColors.spacing || 8
            Layout.rightMargin: themeColors.spacing || 8
            Layout.bottomMargin: (themeColors.spacing || 8) / 2
            placeholderText: "🔍 搜索主题..."
            font.pixelSize: themeColors.smallSize || 12
            leftPadding: 8
            topPadding: 6
            bottomPadding: 6

            background: Rectangle {
                radius: themeColors.smallRadius || 4
                color: themeColors.inputBg || "#f8f9fa"
                border.color: searchField.activeFocus
                    ? (themeColors.accentColor || "#1a73e8")
                    : (themeColors.borderColor || "#dadce0")
                border.width: 1
            }
        }

        // ── 主题列表 ──────────────────────────
        ListView {
            id: topicList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: (themeColors.spacing || 8) / 2
            Layout.rightMargin: (themeColors.spacing || 8) / 2
            clip: true

            model: topics
            delegate: topicDelegate
            currentIndex: -1
            spacing: 2

            ScrollBar.vertical: ScrollBar {
                active: true
                policy: ScrollBar.AsNeeded
            }

            // 空状态
            Text {
                anchors.centerIn: parent
                text: "暂无主题"
                color: themeColors.secondaryText || "#5f6368"
                font.pixelSize: themeColors.smallSize || 12
                visible: topicList.count === 0
            }
        }

        // ── 底部状态栏 ────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            color: "#f0f0f0"

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                text: "📦 " + topics.length + " 个主题"
                font.pixelSize: 11
                color: themeColors.secondaryText || "#5f6368"
            }
        }
    }

    // ── 主题项委托 ────────────────────────────
    Component {
        id: topicDelegate

        Item {
            width: topicList.width
            height: 44

            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: themeColors.smallRadius || 4
                color: modelData.id === sidebarCurrentId
                    ? (themeColors.sidebarSelected || "#cce0ff")
                    : (mouseArea.containsMouse ? (themeColors.sidebarHover || "#e8f0fe") : "transparent")
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 8
                anchors.topMargin: 4
                anchors.bottomMargin: 4
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: modelData.title || "未命名主题"
                    font.pixelSize: (themeColors.smallSize || 12) + 1
                    font.bold: modelData.id === sidebarCurrentId
                    color: themeColors.primaryText || "#202124"
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }

                Text {
                    Layout.fillWidth: true
                    text: modelData.updated || ""
                    font.pixelSize: 10
                    color: themeColors.secondaryText || "#5f6368"
                    elide: Text.ElideRight
                }
            }

            MouseArea {
                id: mouseArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor

                onClicked: {
                    topicList.currentIndex = index
                    sidebarCurrentId = modelData.id
                    topicSelected(modelData.id)
                }
            }
        }
    }

    // ── 当前选中 ID（内部状态） ──────────────
    property string sidebarCurrentId: ""

    // ── 刷新主题列表 ──────────────────────────
    function refresh() {
        if (backend) {
            backend.refresh_topics()
        }
    }
}
