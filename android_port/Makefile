# @2026-06-04 gen by tea_agent, TeaAgent Android 构建 Makefile
#
# 使用方式:
#   make setup       # 安装/检查构建依赖
#   make build       # 构建 debug APK
#   make clean       # 清理构建产物
#   make install     # 构建并安装到设备
#   make lint        # 运行代码检查
#   make help        # 显示帮助

.PHONY: setup build clean install lint help

PROJECT_DIR := tea_agent_android
APK_OUTPUT := $(PROJECT_DIR)/app/build/outputs/apk/debug/app-debug.apk

help:
	@echo "TeaAgent Android 构建命令"
	@echo "  make setup    安装/检查构建依赖"
	@echo "  make build    构建 debug APK"
	@echo "  make clean    清理构建产物"
	@echo "  make install  构建并安装到连接的设备"
	@echo "  make lint     运行代码检查"

setup:
	@echo "=== 检查环境 ==="
	@java -version 2>&1 || (echo "需要 Java 17+"; exit 1)
	@echo "Java OK"
	@if [ -z "$$ANDROID_HOME" ] && [ -z "$$ANDROID_SDK_ROOT" ]; then \
		echo "警告: ANDROID_HOME 未设置"; \
		echo "请设置: export ANDROID_HOME=~/Android/Sdk"; \
	fi

build: setup
	@echo "=== 构建 APK ==="
	cd $(PROJECT_DIR) && chmod +x gradlew && ./gradlew assembleDebug
	@if [ -f "$(APK_OUTPUT)" ]; then \
		echo "✅ APK: $(APK_OUTPUT) ($$(du -h $(APK_OUTPUT) | cut -f1))"; \
	else \
		echo "❌ 构建失败"; \
		exit 1; \
	fi

clean:
	@echo "=== 清理 ==="
	cd $(PROJECT_DIR) && ./gradlew clean 2>/dev/null || true
	rm -rf $(PROJECT_DIR)/build 2>/dev/null || true
	@echo "✅ 清理完成"

install: build
	@echo "=== 安装 ==="
	adb install -r $(APK_OUTPUT)
	@echo "✅ 安装完成"

lint:
	@echo "=== 运行 Lint ==="
	cd $(PROJECT_DIR) && ./gradlew lint
	@echo "✅ Lint 完成"
