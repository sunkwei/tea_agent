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
# 1. 创建配置文件
mkdir -p ~/.tea_agent
cp config.example.yaml ~/.tea_agent/config.yaml
# 编辑 config.yaml 填入 API Key

# 2. 使用自定义配置启动
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
