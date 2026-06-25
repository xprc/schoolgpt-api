# schoolgpt-api
校园百事通: 后端

## 首次运行配置

第一次打开前端时会进入首次运行设置页，填写 MySQL 连接信息和第一个管理员账号。提交后后端会自动创建数据库、业务表、默认模型配置，并将运行时连接信息写入：

```text
schoolgpt-api/config/runtime_setup.json
```

## LLM 配置

后端通过数据库中的 `model_configs` 表创建 OpenAI 兼容的聊天模型。

首次启动时会自动创建一条 DeepSeek 默认配置：

- 供应商：`deepseek`
- 模型：`deepseek-v4-pro`
- Base URL：`https://api.deepseek.com`
- Chat API Path：`/chat/completions`

首次运行创建的管理员登录后，在前端 Admin 管理中心的“模型配置”页面选择 DeepSeek 或通义千问并填写 API Key。保存后新请求会按数据库中当前生效的配置加载模型。

## 服务器部署

以下示例以 Ubuntu 服务器为例，假设项目放在 `/opt/schoolgpt/schoolgpt-api`，前端由 Nginx 托管并通过 `/api/` 反向代理到后端。

### 1. 安装基础环境

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mysql-server nginx
```

建议使用 Python 3.10、3.11 或 3.12。

### 2. 准备 MySQL

登录 MySQL：

```bash
sudo mysql
```

创建专用用户：

```sql
CREATE USER IF NOT EXISTS 'schoolgpt'@'localhost' IDENTIFIED BY '请替换为强密码';
GRANT ALL PRIVILEGES ON *.* TO 'schoolgpt'@'localhost';
FLUSH PRIVILEGES;
```

首次运行设置会按页面填写的数据库名自动创建数据库和表。

### 3. 安装后端依赖

```bash
cd /opt/schoolgpt/schoolgpt-api
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. 本地启动验证

```bash
cd /opt/schoolgpt/schoolgpt-api
source .venv/bin/activate

export SCHOOLGPT_AUTH_SECRET_KEY='请替换为随机密钥'
export SCHOOLGPT_CORS_ORIGINS='["https://你的域名"]'

uvicorn api.main:app --host 127.0.0.1 --port 8000
```

如果没有域名、只是用服务器 IP 测试，可将 `SCHOOLGPT_CORS_ORIGINS` 临时改为：

```bash
export SCHOOLGPT_CORS_ORIGINS='["http://服务器IP"]'
```

### 5. 使用 systemd 托管后端

创建服务文件：

```bash
sudo nano /etc/systemd/system/schoolgpt-api.service
```

写入以下内容，并替换密码、密钥和域名：

```ini
[Unit]
Description=SchoolGPT FastAPI Backend
After=network.target mysql.service

[Service]
WorkingDirectory=/opt/schoolgpt/schoolgpt-api
Environment="SCHOOLGPT_AUTH_SECRET_KEY=请替换为随机密钥"
Environment="SCHOOLGPT_CORS_ORIGINS=[\"https://你的域名\"]"
ExecStart=/opt/schoolgpt/schoolgpt-api/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动并设置开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now schoolgpt-api
sudo systemctl status schoolgpt-api
```

查看运行日志：

```bash
journalctl -u schoolgpt-api -f
```

### 6. 配置 Nginx 反向代理

后端服务建议只监听 `127.0.0.1:8000`，由 Nginx 对外暴露 `/api/`：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
}
```
