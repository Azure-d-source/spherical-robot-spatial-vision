# 团队工作台与 PostgreSQL 后端

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
npm --prefix src/web ci
npm --prefix src/web run build
.\.venv\Scripts\python.exe -m uvicorn src.api.platform.app:create_app --factory --host 127.0.0.1 --port 8001
```

打开 [团队工作台](http://127.0.0.1:8001/) 后用预先创建的账号登录。创建账号时在终端输入密码。答辩可提前准备一个演示账号，团队内测为每位成员创建独立账号。同队场景可见，场景创建者和团队管理员可改名、归档或恢复。可按「全部」「进行中」「已归档」筛选。接口契约见 [OpenAPI 文档](http://127.0.0.1:8001/docs)。

异地内测时，将 `SPATIAL_PUBLIC_ORIGIN` 设为工作台的 HTTPS 源地址，例如 `https://workbench.example.com`。将页面、API 和静态查看器都转发给同一后端，并保留原始 Host。HTTPS 模式会为会话 Cookie 启用 Secure。

使用 Vite 联调前端时，启动 API 的终端需先执行 `$env:SPATIAL_PUBLIC_ORIGIN = 'http://127.0.0.1:5173'`。另开终端运行以下命令，并在浏览器使用配置中的同一个地址。

```powershell
$env:SPATIAL_API_URL = 'http://127.0.0.1:8001'
npm --prefix src/web run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

PostgreSQL 入口默认把原图写入 `data/platform-runtime/photos`。可以用 `SPATIAL_DATA_DIR` 指定独立的运行目录。每个数据库使用自己的目录，同一数据库的 API 和 Worker 使用同一目录。

## 启动 GPU Worker

API 与 Worker 启动前使用同一个 `SPATIAL_DATA_DIR`，并通过环境变量提供同一个 `SPATIAL_WORKER_TOKEN`。依照 [P3 GPU 环境说明](../../../docs/experiments/workbench-gpu-smoke.md#启动与复现) 配置 DA3 和 3DGS 的 Python 路径、DA3 权重、Brush 与可选的 SplatTransform。Worker 从同机的 API 监听地址领取作业。浏览器在异地内测时通过反向代理的 HTTPS 地址访问。

```powershell
.\.venv\Scripts\python.exe -m src.workers.runner --api-url http://127.0.0.1:8001
```

## 业务接口

| 接口 | 当前契约 |
| --- | --- |
| `GET /api/health` | 检查数据库连接并返回 `status: "ok"` 与 `workbench: "team"`，供页面启动时确认登录模式。 |
| `POST /api/auth/login` | 接收 `email`、`password`，返回身份和团队，设置会话 Cookie。 |
| `GET /api/auth/me` | 返回已登录账号、团队和角色。 |
| `POST /api/auth/logout` | 注销当前会话，返回 `204`。 |
| `POST /api/scenes` | 接收已有的 `title`、`source` 和可选 `target`。从会话确定团队及创建者，返回 `201`。 |
| `GET /api/scenes`、`GET /api/scenes/{scene_id}` | 只返回当前团队内的场景。列表默认返回全部场景，可用 `status=active` 或 `status=archived` 过滤。跨团队详情请求返回 `404`。 |
| `PATCH /api/scenes/{scene_id}` | 创建者或管理员可修改进行中场景的 `title`。 |
| `POST /api/scenes/{scene_id}/archive`、`POST /api/scenes/{scene_id}/restore` | 创建者或管理员可归档或恢复，返回场景当前状态。重复操作返回已有状态。 |
| `POST /api/scenes/{scene_id}/frames` | 表单包含 `image`、`capture_id`，可选 `view_label`、带时区的 `captured_at`。新照片返回 `201`，复用照片返回 `200`。 |
| `GET /api/scenes/{scene_id}/frames` | 按上传顺序返回去重后的照片及原图地址。 |
| `GET /api/scenes/{scene_id}/frames/{frame_id}/uploads` | 同队成员可按上传时间查看记录。返回上传人编号、账号邮箱 `uploader_email`、采集编号、机位、采集时间 `captured_at` 和上传时间 `created_at`。 |
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

点击照片卡片的「上传记录」后，工作台读取该照片的记录，并显示每次上传的账号邮箱、机位和上传时间。归档场景仍可查看。

进行中场景的未使用照片会向首次上传者、场景创建者和团队管理员显示「撤下」。确认窗显示文件名及操作影响，确认后才提交。已用于批次的照片会标记为「已用于批次」。如果照片在确认期间被其他成员加入批次，接口拒绝操作，工作台保留照片并显示原因。

撤下后，照片从常规列表、当前勾选和原图入口移出，数据库保留操作人与时间、上传历史及原文件。旧采集编号的重试会返回照片的撤下状态。用户明确用新编号重新上传相同文件时，产生一条新的可选照片记录，磁盘复用原文件。

批次按场景从第 1 版编号。修改选图顺序或补拍后确认，会形成新批次。不同场景的照片和不同仿真布局的照片不能混入同一批次。撤下与冻结在同一事务约束下校验，先完成的操作决定后续结果。

同一批次、同一作业类型的运行号递增。默认结果是运行号最大的成功记录。更新的运行处于排队、执行或失败状态时，默认入口继续返回已有成功结果。较早的运行晚完成时，保留其历史产物。各次运行使用自己的下载地址。

归档场景对团队成员只读。它保留照片、上传记录、批次、任务和产物，普通成员仍可查看原图和下载模型。归档后改名、上传、撤图、冻结、提交和重跑返回 `409 SCENE_ARCHIVED`。归档前提交的作业可以继续完成并发布；恢复场景后按原协作权限继续操作。

## 验收

2026 年 11 月 26 日，在 Windows 与 RTX 4060 Laptop 上验证了 PostgreSQL 后端、真实 Worker 和两位同队成员的访问。下表从启动单次 Worker 到 API 可读到成功状态计时，包含进程、计算与发布。

| 作业 | 耗时 | 结果 |
| --- | ---: | --- |
| DA3 四图融合 | 37.92 秒 | 200,000 点、GLB 与四张深度预览。 |
| 公开 32 图 3DGS，400 步初次运行 | 52.20 秒 | 32/32 注册，发布 PLY 和 SOG。 |
| 同批次 3DGS 重跑 | 49.17 秒 | 32/32 注册，发布新 PLY 和 SOG，默认结果切到本次运行。 |

确认了重跑排队时仍可读取初次成功结果，重跑发布成功后默认切换到第 2 次运行。重新启动 API 后，两轮 3DGS 与点云产物仍可读取。回归测试另覆盖失败重跑、旧运行晚完成、同编号重试、租约过期和跨团队的下载限制。

同日用 Edge 验证了团队工作台。用创建者账号登录、刷新保持登录、改名和归档，再切换到普通成员查看原图、配准覆盖和产物历史。归档批次的真实 GLB 和最新成功 SOG 均能在内嵌查看器打开。会话失效后页面回到登录界面，创建者重新登录并恢复场景后，可以继续采集。

安装测试依赖并设置 `SPATIAL_TEST_DATABASE_URL`。测试连接账号需要能在测试数据库创建临时 schema。

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
$env:SPATIAL_TEST_DATABASE_URL = $env:SPATIAL_DATABASE_URL
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
