# 源码布局

视觉作业在开发机和云 GPU 使用相同的命令行和文件约定。各作业记录冻结的输入、参数及产物，供查看器和工作台使用。 [云 GPU 试跑](../docs/design/cloud-pilot.md)

| 目录 | 阶段与职责 |
| --- | --- |
| `workers/` | 视频抽帧，以及领取作业并调用 DA3、COLMAP、Brush 和 SplatTransform。 |
| `web/` | 场景、照片、批次、作业状态、注册覆盖和产物下载。 |
| `api/` | FastAPI 管理场景、原图、批次、作业租约和产物发布。SQLite 保存任务记录。 |
| `edge/` | 实体球接入阶段。设备拍照、缓存和传输。 |

文件交接与验收依据见 [系统架构](../docs/design/platform-architecture.md)和[实施指南](../docs/design/implementation-guide.md)。

## 本地启动工作台

从仓库根目录执行。开发环境使用 Python 3.12 和 Node.js 22.12 或更高版本。数据默认保存在 `data/runtime/`，可通过 `SPATIAL_DATA_DIR` 指定其他目录。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src/api/requirements.txt
npm --prefix src/web ci
npm --prefix src/web run build
.\.venv\Scripts\python.exe -m uvicorn src.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

打开 [采集工作台](http://127.0.0.1:8000/) 或 [API 文档](http://127.0.0.1:8000/docs)。编辑前端时保留 API 进程，在另一个终端执行 `npm --prefix src/web run dev`，Vite 转发 API 请求。修改后端时可在 Uvicorn 命令末尾加 `--reload --reload-dir src/api`。

启动真实 Worker 时，两端使用同一数据目录。按 [P3 本机 GPU 联调记录](../docs/experiments/workbench-gpu-smoke.md#启动与复现) 配置 `ORBIT_DA3_PY`、`ORBIT_DA3_MODEL`、`ORBIT_GS_PY`、`ORBIT_BRUSH` 和可选的 `ORBIT_SOG_CLI`。两类执行器各自使用对应的 Python 解释器。一张 GPU 启动一个 Worker。若启用 Worker 鉴权，API 和 Worker 使用同一个 `SPATIAL_WORKER_TOKEN`。

```powershell
.\.venv\Scripts\python.exe -m src.workers.runner --api-url http://127.0.0.1:8000
```

## 回归验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix src/web run build
```

## 本地视觉作业

先按已验证版本准备 DA3 源码和本机 BASE 权重、PyCOLMAP、Brush，以及需要 SOG 时使用的 Node.js 和 SplatTransform。点云与 3DGS 可以使用各自的 Python 环境。照片作为位置参数按采集顺序输入，每次运行指定一个新输出目录。

```powershell
$photos = @(Get-ChildItem -LiteralPath .\data\frames -File |
    Where-Object Extension -In '.jpg', '.jpeg', '.png' |
    Sort-Object Name | ForEach-Object FullName)
$da3Model = 'D:\vision-models\DA3-BASE'
$brush = 'D:\vision-tools\brush_app.exe'
$splatCli = 'D:\vision-tools\node_modules\@playcanvas\splat-transform\bin\cli.mjs'

# 样例文件名按拍摄顺序编号。先比较首图和前四张。
python .\src\workers\point_cloud.py --model-dir $da3Model --output-dir .\data\point-single $photos[0]
$pointPhotos = $photos | Select-Object -First 4
python .\src\workers\point_cloud.py --model-dir $da3Model --output-dir .\data\point-multi @pointPhotos

# 短轮验证注册、优化和压缩。按画质检查再提高步数。
python .\src\workers\reconstruct_gaussians.py --brush-exe $brush --splat-transform-cli $splatCli --steps 400 --output-dir .\data\gs-smoke @photos
```

点云作业输出 `scene.glb` 与 `manifest.json`，增加 `--with-depth` 可导出深度预览。高斯作业要求照片使用同一相机和画幅，保存 `scene.ply`、注册结果及 `manifest.json`，指定 `--splat-transform-cli` 时追加 `scene.sog`。用独立查看器打开产物。短轮仅用于检查流程，正式画质用固定视角和实际参数验收。

- [点云作业](workers/point_cloud.py) · [3DGS 作业](workers/reconstruct_gaussians.py)
- [工具版本、权重与复现配置](../docs/design/implementation-guide.md)

## 视频抽帧

安装 FFmpeg 及 Python 3.11 或更新版。先对有重叠的短片段按 2 帧/秒试采样，例如从第 0 秒开始的 12 秒，最多取 24 张候选图。

```powershell
python -m src.workers.extract_frames .\data\scene.mp4 --start 0 --duration 12 --fps 2 --max-frames 24 --output-dir .\data\video-candidates
```

输出有序 RGB PNG 和记录原视频 SHA-256、截取参数、FFmpeg 版本的 `manifest.json`。筛掉重复、模糊或缺少重叠的画面后，按采集顺序提交同一组图片至点云或高斯作业。下一轮改采样频率或区间时使用新的输出目录。 [视频抽帧作业](workers/extract_frames.py) · [视频与云端重建](../docs/design/cloud-pilot.md#4-虚拟球自有视频与预制公开资产)
