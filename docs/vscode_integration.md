# Tea Agent x VS Code

## 推荐：vscode-acp
1. VS Code → 扩展(Ctrl+Shift+X) → 搜索 vscode-acp
2. 安装后 Ctrl+Shift+P → ACP: Connect to Agent
3. 输入 http://127.0.0.1:8082

## acpx CLI
```
npm install -g @openclaw/acpx
acpx --agent http://127.0.0.1:8082
```

## 启动
```
python -m tea_agent.protocol --port 8082
```
