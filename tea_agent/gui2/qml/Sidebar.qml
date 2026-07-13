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

        // ── 标题栏 ────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: "transparent"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 4
                anchors.topMargin: 0
                anchors.bottomMargin: 0
                spacing: 0

                Text {
                    text: "💬 茶 Agent"
                    font.pixelSize: 16
                    font.bold: true
                    color: themeColors.primaryText || "#202124"
                    Layout.fillWidth: true
                }

                // 关闭窗口按钮 — 移除 opacity，使用实色
                Button {
                    id: closeBtn
                    text: "✕"
                    implicitWidth: 32
                    implicitHeight: 32
                    flat: false
                    // 使用内联 Rectangle 代替 background，保证始终可见
                    background: Rectangle {
                        radius: 4
                        color: closeBtn.hovered
                            ? (themeColors.errorColor || "#ea4335")
                            : "transparent"
                    }
                    contentItem: Text {
                        text: closeBtn.text
                        color: closeBtn.hovered ? "#ffffff" : (themeColors.secondaryText || "#5f6368")
                        font.pixelSize: 16
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: Qt.quit()
                }
            }
        }

        // ── 分割线 ────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: themeColors.dividerColor || "#e8eaed"
        }

        // ── 新建主题按钮（实色背景，保证可读） ──
        Button {
            id: newTopicBtn
            Layout.fillWidth: true
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.topMargin: 8
            Layout.bottomMargin: 4
            text: "✏️  新建主题"
            font.pixelSize: 13
            implicitHeight: 36

            // 实色背景 + 深色文字，高可读性
            background: Rectangle {
                radius: 6
                color: newTopicBtn.hovered
                    ? (themeColors.accentColor || "#1a73e8")
                    : (themeColors.sidebarHover || "#f0f6ff")
                border.width: 1
                border.color: newTopicBtn.hovered
                    ? (themeColors.accentColor || "#1a73e8")
                    : (themeColors.borderColor || "#dadce0")
            }
            contentItem: Text {
                text: newTopicBtn.text
                color: newTopicBtn.hovered ? "#ffffff" : (themeColors.accentColor || "#1a73e8")
                font: newTopicBtn.font
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: newTopicRequested()
        }

        // ── 搜索框 ────────────────────────────
        TextField {
            id: searchField
            Layout.fillWidth: true
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.bottomMargin: 4
            placeholderText: "🔍 搜索主题..."
            font.pixelSize: 12
            implicitHeight: 32
            leftPadding: 10
            topPadding: 6
            bottomPadding: 6
            color: themeColors.primaryText || "#202124"

            background: Rectangle {
                radius: 6
                color: (themeColors.inputBg || "#f5f5f5")
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
            Layout.leftMargin: 4
            Layout.rightMargin: 4
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
                font.pixelSize: 12
                visible: topicList.count === 0
            }
        }

        // ── 底部统计 ──────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            color: themeColors.dividerColor || "#f0f0f0"

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 10
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
                radius: 6
                color: modelData.id === sidebarCurrentId
                    ? (themeColors.sidebarSelected || "#d2e3fc")
                    : (mouseArea.containsMouse ? (themeColors.sidebarHover || "#f0f6ff") : "transparent")
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                anchors.topMargin: 5
                anchors.bottomMargin: 5
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: modelData.title || "未命名主题"
                    font.pixelSize: 13
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
                acceptedButtons: Qt.LeftButton
                onClicked: {
                    topicList.currentIndex = index
                    sidebarCurrentId = modelData.id
                    topicSelected(modelData.id)
                }
            }
        }
    }

    // ── 当前选中 ID ──────────────────────────
    property string sidebarCurrentId: ""

    // ── 刷新 ──────────────────────────────────
    function refresh() {
        if (backend) {
            backend.refresh_topics()
        }
    }
}
