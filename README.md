# schoolgpt-api
校园百事通: 后端

## MySQL 配置

用户系统默认使用 MySQL，连接配置可通过环境变量覆盖：

- `SCHOOLGPT_DATABASE_URL`: 完整 SQLAlchemy 连接串，例如 `mysql+pymysql://root:password@127.0.0.1:3306/schoolgpt?charset=utf8mb4`
- `SCHOOLGPT_MYSQL_HOST`: 默认 `127.0.0.1`
- `SCHOOLGPT_MYSQL_PORT`: 默认 `3306`
- `SCHOOLGPT_MYSQL_USER`: 默认 `root`
- `SCHOOLGPT_MYSQL_PASSWORD`: 默认空
- `SCHOOLGPT_MYSQL_DATABASE`: 默认 `schoolgpt`

首次启动时会自动创建数据库和 `users` 表，并在空表中创建默认账号 `admin / admin123456`。

## LLM 配置

后端默认通过 `model/factory.py` 创建 OpenAI 兼容的聊天模型，当前读取以下环境变量：

- `DEEPSEEK_MODELNAME`: 模型名称，例如 `deepseek-v4-flash`
- `DEEPSEEK_BASEURL`: OpenAI 兼容接口地址，例如 `https://api.deepseek.com/`
- `DEEPSEEK_API_KEY`: LLM API Key

本地开发可在 `schoolgpt-api/.env` 中配置：

```env
DEEPSEEK_MODELNAME=deepseek-v4-flash
DEEPSEEK_BASEURL=https://api.deepseek.com/
DEEPSEEK_API_KEY=请替换为你的 API Key
```

服务器部署时建议写入 systemd 服务的 `Environment` 配置中。由于模型对象在应用导入时创建，修改这些变量后必须重启后端服务。

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

创建数据库和专用用户：

```sql
CREATE DATABASE IF NOT EXISTS schoolgpt
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'schoolgpt'@'localhost' IDENTIFIED BY '请替换为强密码';
GRANT ALL PRIVILEGES ON schoolgpt.* TO 'schoolgpt'@'localhost';
FLUSH PRIVILEGES;
```

如果需要手动导入表结构，可在项目根目录执行：

```bash
mysql -u schoolgpt -p schoolgpt < ../schoolgpt-db/001_create_users.sql
mysql -u schoolgpt -p schoolgpt < ../schoolgpt-db/002_create_conversations.sql
```

后端首次启动时也会自动创建数据库、用户表和会话相关表。

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

export SCHOOLGPT_MYSQL_HOST=127.0.0.1
export SCHOOLGPT_MYSQL_PORT=3306
export SCHOOLGPT_MYSQL_USER=schoolgpt
export SCHOOLGPT_MYSQL_PASSWORD='请替换为强密码'
export SCHOOLGPT_MYSQL_DATABASE=schoolgpt
export SCHOOLGPT_AUTH_SECRET_KEY='请替换为随机密钥'
export SCHOOLGPT_DEFAULT_USERNAME=admin
export SCHOOLGPT_DEFAULT_PASSWORD='请替换为管理员密码'
export SCHOOLGPT_CORS_ORIGINS='["https://你的域名"]'
export DEEPSEEK_MODELNAME=deepseek-v4-flash
export DEEPSEEK_BASEURL=https://api.deepseek.com/
export DEEPSEEK_API_KEY='请替换为你的 API Key'

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
Environment="SCHOOLGPT_MYSQL_HOST=127.0.0.1"
Environment="SCHOOLGPT_MYSQL_PORT=3306"
Environment="SCHOOLGPT_MYSQL_USER=schoolgpt"
Environment="SCHOOLGPT_MYSQL_PASSWORD=请替换为强密码"
Environment="SCHOOLGPT_MYSQL_DATABASE=schoolgpt"
Environment="SCHOOLGPT_AUTH_SECRET_KEY=请替换为随机密钥"
Environment="SCHOOLGPT_DEFAULT_USERNAME=admin"
Environment="SCHOOLGPT_DEFAULT_PASSWORD=请替换为管理员密码"
Environment="SCHOOLGPT_CORS_ORIGINS=[\"https://你的域名\"]"
Environment="DEEPSEEK_MODELNAME=deepseek-v4-flash"
Environment="DEEPSEEK_BASEURL=https://api.deepseek.com/"
Environment="DEEPSEEK_API_KEY=请替换为你的 API Key"
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
