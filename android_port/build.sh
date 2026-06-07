#!/bin/bash
#
# @2026-06-04 gen by tea_agent, TeaAgent Android 构建脚本
# 支持 Linux/macOS/WSL，自动检测环境并安装缺失依赖
#
# 使用方式:
#   chmod +x build.sh
#   ./build.sh              # 完整构建 APK
#   ./build.sh setup        # 仅安装依赖
#   ./build.sh clean        # 清理构建产物
#   ./build.sh install      # 构建并安装到设备
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/tea_agent_android"
BUILD_DIR="$PROJECT_DIR/build"
OUTPUT_DIR="$PROJECT_DIR/app/build/outputs/apk/debug"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_java() {
    if command -v java &>/dev/null; then
        JAVA_VER=$(java -version 2>&1 | head -1 | sed 's/[^0-9.]//g' | cut -d. -f1)
        if [ "$JAVA_VER" -ge 17 ] 2>/dev/null; then
            log_ok "Java $JAVA_VER+ 已安装"
            return 0
        fi
    fi
    log_error "需要 Java 17+（当前: $(java -version 2>&1 | head -1 || echo '未安装')）"
    log_info "安装: sudo apt install openjdk-17-jdk 或从 https://adoptium.net 下载"
    return 1
}

check_android_sdk() {
    local sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
    
    if [ -d "$sdk_root" ]; then
        log_ok "Android SDK 已安装: $sdk_root"
        export ANDROID_HOME="$sdk_root"
        return 0
    fi
    
    log_warn "Android SDK 未安装"
    log_info "自动安装到 $HOME/Android/Sdk..."
    
    install_android_sdk "$sdk_root"
}

install_android_sdk() {
    local sdk_root="$1"
    mkdir -p "$sdk_root"
    
    # 下载 cmdline-tools
    local cmdline_tools_url="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
    local tmp_zip="/tmp/android-cmdline-tools.zip"
    
    log_info "下载 Android cmdline-tools..."
    if command -v curl &>/dev/null; then
        curl -fsSL "$cmdline_tools_url" -o "$tmp_zip"
    elif command -v wget &>/dev/null; then
        wget -q "$cmdline_tools_url" -O "$tmp_zip"
    else
        log_error "需要 curl 或 wget"
        return 1
    fi
    
    log_info "解压 cmdline-tools..."
    unzip -q "$tmp_zip" -d "/tmp/android-cmdline-tools"
    mkdir -p "$sdk_root/cmdline-tools"
    mv /tmp/android-cmdline-tools/cmdline-tools "$sdk_root/cmdline-tools/latest"
    rm -f "$tmp_zip"
    rm -rf /tmp/android-cmdline-tools
    
    export ANDROID_HOME="$sdk_root"
    export PATH="$PATH:$sdk_root/cmdline-tools/latest/bin"
    
    # 安装必要组件
    log_info "安装 Android SDK 组件（build-tools, platform, platform-tools）..."
    yes | sdkmanager --sdk_root="$sdk_root" \
        "platforms;android-34" \
        "build-tools;34.0.0" \
        "platform-tools" \
        "ndk;25.2.9519653" 2>/dev/null || true
    
    log_ok "Android SDK 安装完成"
}

ensure_gradlew() {
    # 如果 gradlew 已存在，直接返回
    if [ -f "$PROJECT_DIR/gradlew" ]; then
        chmod +x "$PROJECT_DIR/gradlew"
        log_ok "Gradle Wrapper 已就绪"
        return 0
    fi

    # 检查是否有 gradle-wrapper.jar
    if [ ! -f "$PROJECT_DIR/gradle/wrapper/gradle-wrapper.jar" ]; then
        log_error "gradlew 和 gradle-wrapper.jar 都不存在"
        log_info "请重新生成: cd $PROJECT_DIR && gradle wrapper --gradle-version=8.5"
        return 1
    fi

    log_warn "gradlew 不存在，正在自动创建..."
    cat > "$PROJECT_DIR/gradlew" << 'GRADLEW_EOF'
#!/bin/sh
APP_HOME=$(cd "${0%/*}" 2>/dev/null; echo "$PWD")
CLASSPATH=$APP_HOME/gradle/wrapper/gradle-wrapper.jar
JAVACMD=${JAVA_HOME:+$JAVA_HOME/bin/java}
[ -z "$JAVACMD" ] && JAVACMD=java
exec "$JAVACMD" -Dorg.gradle.appname=gradlew -classpath "$CLASSPATH" org.gradle.wrapper.GradleWrapperMain "$@"
GRADLEW_EOF
    chmod +x "$PROJECT_DIR/gradlew"
    log_ok "gradlew 已创建"
}

setup() {
    log_info "检查构建环境..."
    check_java
    check_android_sdk
    ensure_gradlew
    log_ok "环境检查完成"
}

clean() {
    log_info "清理构建产物..."
    cd "$PROJECT_DIR"
    ./gradlew clean 2>/dev/null || true
    rm -rf "$BUILD_DIR" 2>/dev/null || true
    log_ok "清理完成"
}

build_apk() {
    log_info "开始构建 APK..."
    cd "$PROJECT_DIR"
    
    export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
    # 优先使用 JDK 17（AGP 不支持 Java 25+）
    if [ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]; then
        export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"
        log_info "使用 JDK 17: $JAVA_HOME"
    fi
    
    # 确保 Gradle Wrapper 可执行
    chmod +x gradlew
    
    # 执行构建
    ./gradlew assembleDebug 2>&1 | tail -20
    
    # 检查构建结果
    if [ -f "$OUTPUT_DIR/app-debug.apk" ]; then
        local size=$(du -h "$OUTPUT_DIR/app-debug.apk" | cut -f1)
        log_ok "构建成功！APK: $OUTPUT_DIR/app-debug.apk ($size)"
    else
        log_error "构建失败：APK 未生成"
        log_info "查看详细日志: cd $PROJECT_DIR && ./gradlew assembleDebug --info"
        return 1
    fi
}

install_apk() {
    if ! command -v adb &>/dev/null; then
        log_error "adb 未安装。请安装 platform-tools 或使用 Android Studio"
        return 1
    fi
    
    build_apk
    
    log_info "查找连接的设备..."
    adb devices | grep -q "device$" || {
        log_error "未发现 Android 设备"
        return 1
    }
    
    log_info "安装 APK..."
    adb install -r "$OUTPUT_DIR/app-debug.apk"
    log_ok "安装完成！"
}

# ====== 主入口 ======

case "${1:-build}" in
    setup)
        setup
        ;;
    clean)
        clean
        ;;
    build)
        setup
        build_apk
        ;;
    install)
        install_apk
        ;;
    *)
        echo "用法: $0 {setup|clean|build|install}"
        echo ""
        echo "  setup   - 安装/检查构建依赖（Java, Android SDK, Gradle）"
        echo "  clean   - 清理构建产物"
        echo "  build   - 完整构建 debug APK"
        echo "  install - 构建并安装到连接的设备"
        exit 1
        ;;
esac
