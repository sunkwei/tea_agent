import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/**
 * InputArea — 消息输入区。
 *
 * 多行文本输入 + 发送按钮。
 * Enter 发送，Shift+Enter 换行。
 */
Rectangle {
    id: root

    // ── 属性（由父级注入） ─────────────────────
    property alias text: textArea.text
    property bool inputEnabled: true
    property var themeColors: ({})

    // ── 信号 ──────────────────────────────────
    signal sendRequested(string text)

    // ── 外观 ──────────────────────────────────
    color: themeColors.inputBg || "#f8f9fa"
    radius: themeColors.borderRadius || 8
    border.color: themeColors.borderColor || "#dadce0"
    border.width: 1

    // ── 布局 ──────────────────────────────────
    RowLayout {
        anchors.fill: parent
        anchors.margins: themeColors.spacing || 8
        spacing: themeColors.spacing || 8

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            TextArea {
                id: textArea
                font.family: themeColors.fontFamily || "Segoe UI, sans-serif"
                font.pixelSize: themeColors.inputSize || 14
                color: themeColors.primaryText || "#202124"
                placeholderText: "输入消息... (Enter 发送，Shift+Enter 换行)"
                wrapMode: TextEdit.WordWrap
                background: null
                topPadding: 4
                bottomPadding: 4

                Keys.onPressed: (event) => {
                    if (event.key === Qt.Key_Return && !(event.modifiers & Qt.ShiftModifier)) {
                        event.accepted = true
                        sendIfNotEmpty()
                    }
                }
            }
        }

        ColumnLayout {
            Layout.alignment: Qt.AlignBottom
            spacing: 4

            Button {
                id: sendBtn
                text: "↵ 发送"
                font.pixelSize: themeColors.smallSize || 12
                enabled: root.inputEnabled && textArea.text.trim().length > 0
                implicitWidth: 70
                implicitHeight: 32

                background: Rectangle {
                    radius: themeColors.smallRadius || 4
                    color: sendBtn.enabled
                        ? (themeColors.accentColor || "#1a73e8")
                        : (themeColors.borderColor || "#dadce0")
                }
                contentItem: Text {
                    text: sendBtn.text
                    color: "white"
                    font: sendBtn.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                onClicked: sendIfNotEmpty()
            }

            Text {
                text: "Ctrl+Enter"
                font.pixelSize: 10
                color: themeColors.secondaryText || "#5f6368"
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }

    // ── 方法 ──────────────────────────────────
    function sendIfNotEmpty() {
        var msg = textArea.text.trim()
        if (msg.length > 0) {
            sendRequested(msg)
            textArea.text = ""
            textArea.forceActiveFocus()
        }
    }

    // ── 焦点管理 ──────────────────────────────
    Component.onCompleted: {
        textArea.forceActiveFocus()
    }

    function focusInput() {
        textArea.forceActiveFocus()
    }
}
