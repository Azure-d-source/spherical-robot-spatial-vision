# 后端第一段联调

此入口用于联调 PostgreSQL、账号会话、团队场景、照片采集、冻结批次与重建作业。API 和 Worker 在团队部署时使用同一台 GPU 主机和同一运行数据目录。

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

PostgreSQL 入口默认把原图写入 `data/platform-runtime/photos`。可以用 `SPATIAL_DATA_DIR` 指定独立的运行目录。每个数据库使用自己的目录，同一数据库的 API 和 Worker 使用同一目录。

## 启动 GPU Worker

API 与 Worker 启动前使用同一个 `SPATIAL_DATA_DIR`，并通过环境变量提供同一个 `SPATIAL_WORKER_TOKEN`。依照 [P3 GPU 环境说明](../../../docs/experiments/workbench-gpu-smoke.md#启动与复现) 配置 DA3 和 3DGS 的 Python 路径、DA3 权重、Brush 与可选的 SplatTransform。Worker 从同机的 API 监听地址领取作业。浏览器在异地内测时通过反向代理的 HTTPS 地址访问。

```powershell
.\.venv\Scripts\python.exe -m src.workers.runner --api-url http://127.0.0.1:8001
```

## 业务接口

| 接口 | 当前契约 |
| --- | --- |
| `POST /api/auth/login` | 接收 `email`、`password`，返回身份和团队，设置会话 Cookie。 |
| `GET /api/auth/me` | 返回已登录账号、团队和角色。 |
| `POST /api/auth/logout` | 注销当前会话，返回 `204`。 |
| `POST /api/scenes` | 接收已有的 `title`、`source` 和可选 `target`。从会话确定团队及创建者，返回 `201`。 |
| `GET /api/scenes`、`GET /api/scenes/{scene_id}` | 只返回当前团队内的场景。跨团队详情请求返回 `404`。 |
| `POST /api/scenes/{scene_id}/frames` | 表单包含 `image`、`capture_id`，可选 `view_label`、带时区的 `captured_at`。新照片返回 `201`，复用照片返回 `200`。 |
| `GET /api/scenes/{scene_id}/frames` | 按上传顺序返回去重后的照片及原图地址。 |
| `GET /api/scenes/{scene_id}/frames/{frame_id}/uploads` | 返回谁上传了同一张照片，含各自的采集编号、机位和时间。 |
| `GET /api/frames/{frame_id}/image` | 登录后按照片所属场景校验团队权限，并返回原图。 |
| `DELETE /api/scenes/{scene_id}/frames/{frame_id}` | 首次上传者、场景创建者或管理员可撤下未用于批次的照片。成功和重复撤下均返回 `204`。已用于批次时返回 `409 FRAME_IN_USE`。 |
| `POST /api/scenes/{scene_id}/revisions` | 提交有序的 `frame_ids`，新建返回 `201`，完全相同的清单复用时返回 `200`。照片已撤下时返回 `409 FRAME_WITHDRAWN`。 |
| `GET /api/scenes/{scene_id}/revisions`、`GET /api/scenes/{scene_id}/revisions/{revision_id}` | 返回批次版本、创建者以及冻结时的照片顺序。 |
| `POST /api/jobs` | 传 `revision_id`、`kind` 和可选 `recipe_version`，返回 `202`。相同批次、类型和配方的普通提交复用首次作业。 |
| `POST /api/jobs/{job_id}/rerun` | 使用原作业的批次、类型和配方，新建一条运行记录。每次主动重跑使用新的 `Idempotency-Key`，网络重试使用同一个值。 |
| `GET /api/jobs/{job_id}`、`GET /api/scenes/{scene_id}/jobs` | 查询运行号、提交人、状态、错误信息和历史产物。 |
| `GET /api/scenes/{scene_id}/revisions/{revision_id}/results` | 返回 `depth`、`fusion`、`splat` 的当前成功运行。某一类型无成功产物时返回 `null`。 |
| `GET /api/artifacts/{job_id}/{filename}` | 下载指定成功运行的产物，按作业所属团队校验权限。 |

声明的业务错误用 `code` 和 `message`，请求校验失败额外返回 `fields`。会话令牌在客户端以 HttpOnly Cookie 保存，数据库存令牌哈希和过期时间。

同一场景内，照片按文件内容合并，照片列表保留首次上传的原图信息。每位成员有自己的上传记录。同一成员用同一个 `capture_id` 重传相同内容时复用原记录，换成不同内容会返回 `409 CAPTURE_CONFLICT`。其他成员即使用了同一个编号，也能留下自己的上传记录。上传支持静态 JPEG、PNG 和 WebP，每张最多 12 MiB、2400 万像素。

撤下后，照片从常规列表和原图入口移出，数据库保留操作人与时间、上传历史及原文件。旧采集编号的重试会返回照片的撤下状态。用户明确用新编号重新上传相同文件时，产生一条新的可选照片记录，磁盘复用原文件。

批次按场景从第 1 版编号。修改选图顺序或补拍后确认，会形成新批次。不同场景的照片和不同仿真布局的照片不能混入同一批次。撤下与冻结在同一事务约束下校验，先完成的操作决定后续结果。

同一批次、同一作业类型的运行号递增。默认结果是运行号最大的成功记录。更新的运行处于排队、执行或失败状态时，默认入口继续返回已有成功结果。较早的运行晚完成时，保留其历史产物。各次运行使用自己的下载地址。

## 验收

2026 年 11 月 26 日，在 Windows 与 RTX 4060 Laptop 上验证了 PostgreSQL 后端、真实 Worker 和两位同队成员的访问。下表从启动单次 Worker 到 API 可读到成功状态计时，包含进程、计算与发布。

| 作业 | 耗时 | 结果 |
| --- | ---: | --- |
| DA3 四图融合 | 37.92 秒 | 200,000 点、GLB 与四张深度预览。 |
| 公开 32 图 3DGS，400 步初次运行 | 52.20 秒 | 32/32 注册，发布 PLY 和 SOG。 |
| 同批次 3DGS 重跑 | 49.17 秒 | 32/32 注册，发布新 PLY 和 SOG，默认结果切到本次运行。 |

确认了重跑排队时仍可读取初次成功结果，重跑发布成功后默认切换到第 2 次运行。重新启动 API 后，两轮 3DGS 与点云产物仍可读取。回归测试另覆盖失败重跑、旧运行晚完成、同编号重试、租约过期和跨团队的下载限制。

安装测试依赖并设置 `SPATIAL_TEST_DATABASE_URL`。测试连接账号需要能在测试数据库创建临时 schema。

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
$env:SPATIAL_TEST_DATABASE_URL = $env:SPATIAL_DATABASE_URL
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
