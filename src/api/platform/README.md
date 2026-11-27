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

## 从 MP4 导入照片

在 API 主机安装 FFmpeg 并把它放入 `PATH`，或将 `SPATIAL_FFMPEG` 设为可执行文件路径。抽帧由 API 主机执行，选中帧照常进入照片、冻结批次和 GPU Worker 流程。数据库迁移至 `head` 后，在进行中场景的「照片采集」打开「导入 MP4」。

选择最大 200 MiB 的 MP4，填写开始时间、可选时长、帧率和帧数上限。候选帧最多 120 张，帧率可设为 0.1–30 fps，候选图长边最多 1920 像素。预览后勾选清晰画面，点击「导入选中帧」，可直接确认照片批次。关闭窗口后，可重新打开「已抽帧视频」继续选图。如使用反向代理，代理的请求体大小限制和响应超时也会影响上传。

原始 MP4 和候选图保存在 `SPATIAL_DATA_DIR/videos`，视频哈希、抽帧参数和导入关系保存在 PostgreSQL。照片上传记录和冻结批次的「原图顺序」均可查看来源并下载原始 MP4。已冻结的来源随作业写入产物 `manifest.json` 的输入帧 `video_sources`，包含原视频 SHA-256、抽帧参数、FFmpeg 版本和候选帧顺序。后来导入的来源会在下次冻结时保存。归档场景保留来源和下载权限。跨团队的原视频和候选帧请求返回 `404`。

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
| `POST /api/scenes/{scene_id}/videos` | 请求体为 `video/mp4`。查询参数为 `filename`、`start_seconds`、可选 `duration_seconds`、`fps` 和 `max_frames`。返回视频信息和有序候选帧。 |
| `GET /api/scenes/{scene_id}/videos`、`GET /api/scenes/{scene_id}/videos/{video_id}` | 查看同一场景的视频列表、抽帧参数和候选图地址。 |
| `POST /api/scenes/{scene_id}/videos/{video_id}/import` | 提交所选 `candidate_ids`，返回导入场景的去重照片。候选图和原视频均通过返回的同源地址访问。 |
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

在「批次与任务」选中原批次，可从已完成或失败的运行打开「重跑」。确认窗显示原批次、照片数量、任务类型和配方。确认后以相同输入新建一次运行，关窗取消时保持原任务。确认请求遇到网络错误时，同一个弹窗内的重试沿用原请求编号。任务队列显示运行号，历史结果仍可下载。

点云和 3DGS 查看器的「查看运行」默认跟随最新成功结果，也可选择当前批次的某一次成功运行。手动选中的模型在轮询时保持，切换批次后回到该批次时也会保留原选择。两种查看器的选择独立。选回「最新成功结果」即可恢复跟随，刷新页面也会回到默认模式。归档场景支持同样的回看操作。

归档场景对团队成员只读。它保留照片、上传记录、批次、任务和产物，普通成员仍可查看原图和下载模型。归档后改名、上传、撤图、冻结、提交和重跑返回 `409 SCENE_ARCHIVED`。归档前提交的作业可以继续完成并发布；恢复场景后按原协作权限继续操作。

## Windows 同机部署与 Cloudflare Tunnel

本机 4060 同时运行工作台、PostgreSQL 和 GPU Worker。下文用 `https://orbit.example.com` 作为公网入口示例。Cloudflare 在边缘提供 HTTPS，`cloudflared` 将流量转发到本机 `127.0.0.1:8000`。API 和 Worker 共享同一个数据目录及 Worker 令牌。

### 启动 API 和 Worker

按上面的步骤安装依赖、迁移数据库、创建内测账号并构建前端。以下命令在仓库根目录的同一个 PowerShell 执行，沿用该终端中的 `SPATIAL_DATABASE_URL` 和 GPU 环境变量。执行前将 `orbit.example.com` 换成实际子域名，将 `<SPATIAL_DATA_DIR>` 换成本机为内测准备的数据目录。每次完整启动可以生成一个新 Worker 令牌，单独重启某个进程时沿用另一进程正在使用的令牌。

```powershell
$py = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$env:SPATIAL_PUBLIC_ORIGIN = 'https://orbit.example.com'
$env:SPATIAL_DATA_DIR = '<SPATIAL_DATA_DIR>'
$env:SPATIAL_WORKER_TOKEN = (& $py -c 'import secrets; print(secrets.token_urlsafe(32))').Trim()

$apiProcess = Start-Process -FilePath $py -ArgumentList @(
    '-m', 'uvicorn', 'src.api.platform.app:create_app', '--factory',
    '--host', '127.0.0.1', '--port', '8000', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1'
) -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
```

待 `Invoke-RestMethod http://127.0.0.1:8000/api/health` 返回 `status: ok` 和 `workbench: team` 后，在当前终端启动 Worker，使两个进程继承同一个令牌。Worker 参数见 [GPU 环境说明](../../../docs/experiments/workbench-gpu-smoke.md#启动与复现)。

```powershell
& $py -m src.workers.runner --api-url http://127.0.0.1:8000
```

配置公网域名且令牌为空时，API 会拒绝启动。即使反向代理从回环地址连入，内部接口也校验 `X-Worker-Token`。令牌仅保留在本机进程环境中。上线前用不带令牌的 `POST http://127.0.0.1:8000/api/internal/workers/claim` 验证返回 `401 INVALID_WORKER_TOKEN`。

### 配置 Tunnel 和边缘规则

下载 Windows 64 位 `cloudflared.exe`，存到 `C:\Tools\cloudflared.exe`。在新的 PowerShell 终端用域名所属 Cloudflare 账号登录。已有供本项目使用的 Tunnel 时，复用其名称和 UUID。 [Cloudflare 下载](https://developers.cloudflare.com/tunnel/downloads/) · [本地管理 Tunnel](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/)

```powershell
$cf = 'C:\Tools\cloudflared.exe'
& $cf tunnel login
& $cf tunnel create orbitforge-pilot
$cfDir = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.cloudflared'
$cfg = Join-Path $cfDir 'orbit.yml'
Copy-Item -LiteralPath 'docs/deployment/cloudflared.orbit.example.yml' -Destination $cfg
notepad $cfg
```

在 [Tunnel 配置模板](../../../docs/deployment/cloudflared.orbit.example.yml) 的本机副本里填入 UUID、`tunnel create` 返回的 JSON 凭据路径和实际子域名。优先拦截 `/api/internal/`，其余发往示例子域 `orbit.example.com` 的请求转发到回环 HTTP，并将 origin Host 设为同一个子域。`cert.pem` 与 Tunnel 凭据 JSON 保留在本机。 [Ingress 规则](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/) · [Origin Host 配置](https://developers.cloudflare.com/tunnel/reference/origin-parameters/)

```powershell
& $cf tunnel --config $cfg ingress validate
& $cf tunnel --config $cfg ingress rule 'https://orbit.example.com/api/internal/workers/claim'
& $cf tunnel --config $cfg ingress rule 'https://orbit.example.com/api/health'
# 确认 orbit 记录可用于本项目后，仅在尚无该记录时执行
& $cf tunnel route dns orbitforge-pilot orbit.example.com
& $cf tunnel --config $cfg run orbitforge-pilot
```

`orbit` 已有 DNS 记录时，先在 Cloudflare 控制台核对它关联的应用和目标。如果确认应切换到本项目，将该子域的代理 CNAME 指向 `<TUNNEL_UUID>.cfargotunnel.com`。 [Tunnel DNS 路由](https://developers.cloudflare.com/tunnel/concepts/routing/)

- 在 Cloudflare 建立仅匹配 `http.host eq "orbit.example.com" and not ssl` 的 Single Redirect。目标表达式为 `concat("https://orbit.example.com", http.request.uri.path)`，状态 `308`，启用保留查询字符串。HTTP 跳转在边缘完成，同机 Worker 继续使用回环 HTTP。 [重定向规则](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/)
- 登录、原图和模型接口带 `Cache-Control: no-store`。对该子域的 `/api/` 前缀设 Cache Rule 为 Bypass cache，确保现有缓存规则不会缓存受会话保护的响应。上传按每张图一个请求，应用限制图片为 12 MiB，整个 multipart 请求为 12 MiB 加 64 KiB。Cloudflare 的有效上传限额至少要容纳该请求。 [Cache Rules](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/) · [Cloudflare 上传限制](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/)

### 跨网验收清单

- [ ] 将 `http://orbit.example.com/?probe=1` 换成实际子域地址，从校园 Wi-Fi 和手机热点分别访问，确认跳转保留查询参数。直接打开 HTTPS，浏览器证书正常，`/api/health` 返回 `{"status":"ok","workbench":"team"}`。公网 `/api/internal/workers/claim` 返回 `404`。
- [ ] 两端分别用独立同队账号登录。在 Edge 开发者工具确认 `orbitforge_session` 为 Secure、HttpOnly、SameSite=Strict。刷新后仍可访问，退出后 `/api/auth/me` 返回 `401`。
- [ ] 使用公开样例，两人依顺序各上传 16 张，按照下节完成四图点云及 `public-32-v1` 重建。单张超 12 MiB 的文件在工作台应提示超限。用登录后的接口检查时，预期收到 `413` 与 `PHOTO_LIMIT_EXCEEDED`。
- [ ] 浏览器网络面板确认 `/supersplat/zstd-decoder.wasm` 返回 `application/wasm`。已登录下载 `scene.sog` 返回 `application/octet-stream` 与 `Cache-Control: no-store`，内嵌模型可旋转。退出后重新请求同一 SOG 直链返回 `401`，隔离团队账号返回 `404`。
- [ ] 校园 Wi-Fi 与手机热点均可回看原图、批次和模型。归档后同队可回看。记录上传耗时、模型可见时间、32 图注册数以及 GLB、PLY 和 SOG 的文件大小。

2026 年 11 月 26 日，使用 `cloudflared 2026.11.2` 验证了模板格式及路由命中。本机 HTTPS 代理到 8000 端口的验收通过，包括会话 Cookie、Worker 令牌、上传大小边界、WASM 和 SOG 的范围请求、SOG 禁止缓存及下载权限。测试时，实际子域的公网 `/api/health` 返回 Cloudflare 的 404，HTTP 首页也未跳转。真实 Tunnel 接通和两网验收待确认该子域的现有 DNS 用途后进行。

## 异地内测首轮

首轮使用已冻结的公开 DL3DV 32 张 PNG，来源修订及文件顺序见 [公开样例记录](../../../docs/experiments/workbench-gpu-smoke.md#环境与输入)。原图共 33,402,150 字节。核对 `input.sha256` 的 SHA-256 为 `e381e651793996a0e99394fb611e514c5738287617e0e306c34377d5a99a91c5`，并逐张校验照片哈希。四图融合复用顺序中的前 4 张。

### 环境准备

- GPU 主机运行 PostgreSQL、FastAPI 与真实 Worker。为内测使用独立数据库及数据目录，执行数据库迁移并构建前端。准备两名同队成员账号，以及一个隔离团队的测试账号。
- 浏览器从不同网络访问同一个可用的 HTTPS 地址。将该地址的源设置为 `SPATIAL_PUBLIC_ORIGIN`。反向代理保留原始 Host，将页面、浏览器 API 和 `/supersplat/` 资源转发给 FastAPI，并允许单个照片请求携带最多 12 MiB 图片加 64 KiB 表单开销。Worker 用私有令牌连接同机回环 API，代理可对外隐藏 `/api/internal/`。

### 验收步骤

1. 成员甲登录并创建场景，按清单顺序上传前 16 张。上传完成后，成员乙从另一网络登录并打开同一场景，确认能读到这 16 张，再按顺序上传余下 16 张。两人各自查看一张照片的上传记录，确认来源账号正确。
2. 成员乙依序选中前 4 张，确认批次并提交「多图点云融合」。页面轮询后应可打开并下载 `scene.glb`、4 张深度预览和 `manifest.json`。
3. 回到照片采集，全选 32 张并确认新批次。核对批次原图清单后，选「3DGS 实景重建」和「公开 32 图验收」。400 步任务应完成 **32/32** 配准，内嵌查看器可打开 `scene.sog`，并可下载 SOG、PLY 和清单。
4. 两人各自回看原图及两批结果，核对产物清单中的有序输入 SHA-256。成员甲归档场景，成员乙刷新后应仍可回看，场景恢复后可继续操作。用隔离团队账号访问同一场景、原图、模型直链，均应返回 `404`。
5. 记录两端的网络类型、上传耗时、点击提交到模型可见的耗时、配准率和产物大小。网络及浏览器时间单独记录，便于和本机结果比较。

### 本机 HTTPS 预演记录

2026 年 11 月 26 日，两份独立 Edge 配置通过本机 HTTPS 反向代理登录，使用独立的 PostgreSQL 数据库。两名成员分别上传 16 张，逐张校验了原图，并核对两批产物清单中的输入顺序。浏览器会话使用 Secure、HttpOnly 和 SameSite=Strict，SuperSplat 的 WASM 可从同源加载。

| 作业 | 提交到模型可见 | 结果 |
| --- | ---: | --- |
| 前 4 张 DA3 融合 | 18.65 秒 | 200,000 点。GLB 3,201,232 字节，4 张深度预览和清单均可下载。 |
| 32 张 3DGS，`public-32-v1` | 51.07 秒 | 32/32 注册。PLY 1,161,725 字节，SOG 88,689 字节，清单 5,560 字节。 |

同队成员验证了预览、下载和归档回看。隔离团队账号访问场景、原图和 SOG 均返回 404。重启 API 后，两批及其作业状态保留，抽查的首尾原图和 9 个产物共 11 个文件的 SHA-256 一致。上述耗时为本机 HTTPS 结果，真实跨网耗时待团队 HTTPS 入口就绪后记录。

## 验收

2026 年 11 月 26 日，在 Windows 与 RTX 4060 Laptop 上验证了 PostgreSQL 后端、真实 Worker 和两位同队成员的访问。下表从启动单次 Worker 到 API 可读到成功状态计时，包含进程、计算与发布。

| 作业 | 耗时 | 结果 |
| --- | ---: | --- |
| DA3 四图融合 | 37.92 秒 | 200,000 点、GLB 与四张深度预览。 |
| 公开 32 图 3DGS，400 步初次运行 | 52.20 秒 | 32/32 注册，发布 PLY 和 SOG。 |
| 同批次 3DGS 重跑 | 49.17 秒 | 32/32 注册，发布新 PLY 和 SOG，默认结果切到本次运行。 |

确认了重跑排队时仍可读取初次成功结果，重跑发布成功后默认切换到第 2 次运行。重新启动 API 后，两轮 3DGS 与点云产物仍可读取。回归测试另覆盖失败重跑、旧运行晚完成、同编号重试、租约过期和跨团队的下载限制。

同日用 Edge 验证了团队工作台。用创建者账号登录、刷新保持登录、改名和归档，再切换到普通成员查看原图、配准覆盖和产物历史。归档批次的真实 GLB 和最新成功 SOG 均能在内嵌查看器打开。会话失效后页面回到登录界面，创建者重新登录并恢复场景后，可以继续采集。

通过 Edge 在同一公开 32 图批次重跑 `public-32-v1`。模拟提交响应丢失后，重试只创建一条运行记录。模拟 Worker 失败后仍能查看原 SOG，再从失败记录提交一次真实重跑。Worker 从启动到退出用时 49.38 秒，32/32 张注册成功，发布的 SOG 为 88,573 字节。页面轮询后自动载入新模型，旧 SOG 的下载地址仍可访问。

用本机真实 GLB、SOG 和 PLY 验证了运行切换。测试通过 Worker 发布接口复用已有产物触发完成状态，确认轮询会更新运行选项，手动选中的旧画布或 iframe 保持原样。切回最新后会打开新结果，3DGS 只有 PLY 时也可加载。切换批次、归档回看和刷新后恢复默认均已验证。

安装测试依赖并设置 `SPATIAL_TEST_DATABASE_URL`。测试连接账号需要能在测试数据库创建临时 schema。

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
$env:SPATIAL_TEST_DATABASE_URL = $env:SPATIAL_DATABASE_URL
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
