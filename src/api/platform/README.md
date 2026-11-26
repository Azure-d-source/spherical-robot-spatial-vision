# 后端第一段联调

此入口用于联调 PostgreSQL、账号会话与团队场景。API 和 Worker 在团队部署时使用同一台 GPU 主机和同一运行数据目录。

## 启动与数据库迁移

在仓库根目录运行以下 PowerShell 命令。将测试连接串中的账号、密码和数据库替换为自己的值。数据库可先用一个空的开发库。

```powershell
.\.venv\Scripts\python.exe -m pip install -r src/api/platform/requirements.txt
$env:SPATIAL_DATABASE_URL = 'postgresql+psycopg://user:password@127.0.0.1:5432/orbitforge'
.\.venv\Scripts\python.exe -m alembic -c src/api/platform/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m src.api.platform.manage create-team orbitforge
.\.venv\Scripts\python.exe -m src.api.platform.manage create-account orbitforge owner@example.test --role admin
.\.venv\Scripts\python.exe -m src.api.platform.manage create-account orbitforge member@example.test
.\.venv\Scripts\python.exe -m uvicorn src.api.platform.app:create_app --factory --host 127.0.0.1 --port 8001
```

打开 [接口文档](http://127.0.0.1:8001/docs)，先登录，再创建和查看场景。账号密码通过终端提示输入。异地内测时，将 `SPATIAL_PUBLIC_ORIGIN` 设为工作台的 HTTPS 源地址，例如 `https://workbench.example.com`。HTTPS 模式会为会话 Cookie 启用 Secure，反向代理应保留该站点的 Host。原有采集、批次和 GPU 演示可继续通过 [工作台原入口](../../README.md#本地启动工作台) 验证。

| 接口 | 当前契约 |
| --- | --- |
| `POST /api/auth/login` | 接收 `email`、`password`，返回身份和团队，设置会话 Cookie。 |
| `GET /api/auth/me` | 返回已登录账号、团队和角色。 |
| `POST /api/auth/logout` | 注销当前会话，返回 `204`。 |
| `POST /api/scenes` | 接收已有的 `title`、`source` 和可选 `target`。从会话确定团队及创建者，返回 `201`。 |
| `GET /api/scenes`、`GET /api/scenes/{scene_id}` | 只返回当前团队内的场景。跨团队详情请求返回 `404`。 |

声明的业务错误用 `code` 和 `message`，请求校验失败额外返回 `fields`。会话令牌在客户端以 HttpOnly Cookie 保存，数据库存令牌哈希和过期时间。

## 验收

安装测试依赖并设置 `SPATIAL_TEST_DATABASE_URL`。测试连接账号需要能在测试数据库创建临时 schema。

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
$env:SPATIAL_TEST_DATABASE_URL = $env:SPATIAL_DATABASE_URL
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
