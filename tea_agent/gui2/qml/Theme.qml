import QtQuick
import QtQuick.Controls

/**
 * Theme — 统一颜色、字体、尺寸定义。
 *
 * 所有 QML 文件引用 Theme 的单例（通过 QML Context 注入）。
 * 适配 Windows / Linux (KDE) 两种平台。
 */
QtObject {
    // ── 颜色 ──────────────────────────────────
    property color bgColor:           "#f5f5f5"        // 窗口背景
    property color sidebarBg:         "#ffffff"        // 侧栏背景
    property color sidebarHover:      "#e8f0fe"        // 侧栏悬浮
    property color sidebarSelected:   "#cce0ff"        // 侧栏选中
    property color chatBg:            "#ffffff"        // 聊天区背景
    property color inputBg:           "#f8f9fa"        // 输入区背景
    property color primaryText:       "#202124"        // 主文字
    property color secondaryText:     "#5f6368"        // 次要文字
    property color accentColor:       "#1a73e8"        // 强调色 (Google Blue)
    property color accentHover:       "#1557b0"        // 强调悬浮
    property color borderColor:       "#dadce0"        // 边框
    property color dividerColor:      "#e8eaed"        // 分割线
    property color successColor:      "#34a853"        // 成功绿
    property color warningColor:      "#fbbc04"        // 警告黄
    property color errorColor:        "#ea4335"        // 错误红
    property color thinkBg:           "#fef3c7"        // 思考块背景 (amber 50)
    property color thinkBorder:       "#f59e0b"        // 思考块边框
    property color toolBg:            "#ecfdf5"        // 工具块背景
    property color toolBorder:        "#10b981"        // 工具块边框
    property color userBubbleBg:      "#e3f2fd"        // 用户气泡背景
    property color aiBubbleBg:        "#f1f8e9"        // AI 气泡背景

    // ── 字体 ──────────────────────────────────
    property string fontFamily:       "Segoe UI, Noto Sans SC, Microsoft YaHei, sans-serif"
    property string monoFont:         "Cascadia Code, JetBrains Mono, Consolas, monospace"
    property int titleSize:           20               // 标题字号
    property int headingSize:         15               // 副标题
    property int bodySize:            14               // 正文字号
    property int smallSize:           12               // 小字号
    property int inputSize:           14               // 输入框字号

    // ── 间距与尺寸 ────────────────────────────
    property int sidebarWidth:        260              // 侧栏宽度
    property int borderRadius:        8                // 圆角
    property int smallRadius:         4                // 小圆角
    property int padding:             12               // 内边距
    property int spacing:             8                // 间距

    // ── 暗黑模式 (预留) ───────────────────────
    property bool isDark:             false            // 是否暗黑模式
}
