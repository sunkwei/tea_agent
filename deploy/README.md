# Tea Agent 部署指南

## 🐳 Docker（推荐）

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f

# 访问 http://localhost:8081

# 停止
docker compose down
```

自定义配置：

```bash
# 方式一（推荐）：直接启动，首启向导会引导选服务商/模型/Key 并写入 provider.yaml
docker compose up -d

# 方式二：手工准备密钥与模型目录
mkdir -p ~/.tea_agent
cp provider.yaml.example ~/.tea_agent/provider.yaml
# 编辑 provider.yaml 填入 API Key 与模型能力

# config.yaml 可选：仅在需要覆盖运行参数/绑定角色时才创建
# cp config.yaml.example 已废弃，直接写引用 provider.yaml 的片段即可（见 README「🔧 配置」）

# 启动
docker compose up -d
```

## 🐧 Systemd（Linux 裸机部署）

```bash
# 1. 安装到 /opt
sudo cp -r . /opt/tea-agent
cd /opt/tea-agent

# 2. 创建用户
sudo useradd -r -s /bin/false tea-agent

# 3. 安装服务
sudo cp deploy/tea-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tea-agent
sudo systemctl start tea-agent

# 4. 查看状态
sudo systemctl status tea-agent
journalctl -u tea-agent -f
```

## 🌐 Nginx 反向代理

```bash
# 1. 配置域名和 SSL
sudo cp deploy/nginx.conf /etc/nginx/sites-available/tea-agent
sudo ln -s /etc/nginx/sites-available/tea-agent /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 2. 用 certbot 自动获取 SSL 证书
sudo certbot --nginx -d tea-agent.example.com
```

## 🔧 直接运行

```bash
# API 服务器（浏览器访问）
python -m tea_agent.server --host 0.0.0.0 --port 8081

# ACP 协议服务器（VS Code 连接）
python -m tea_agent.protocol --host 0.0.0.0 --port 8082
```
