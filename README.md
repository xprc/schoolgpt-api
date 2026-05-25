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
