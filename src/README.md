# 源码布局

视觉作业在开发机和云 GPU 使用相同的命令行和文件约定。各作业记录冻结的输入、参数及产物，供查看器和工作台使用。 [云 GPU 试跑](../docs/design/cloud-pilot.md)

| 目录 | 阶段与职责 |
| --- | --- |
| `workers/` | 视频抽帧，以及领取作业并调用 DA3、COLMAP、Brush、SplatTransform 与留出渲染评估。 |
| `web/` | 场景、照片、批次、作业状态、注册覆盖、点云与 3DGS 查看、虚拟相机取景。 |
| [`web/scan-demo/`](web/scan-demo/) | 仿真扫描台简版。24 个机位、RGB-D 采集、点云融合和单物体 3DGS 对照。 |
| `api/` | FastAPI 管理场景、原图、批次、作业租约和产物发布。`api/platform/` 提供使用 PostgreSQL 和账号登录的团队工作台。 |
| `edge/` | 实体蛇形机器人接入阶段。蛇头相机拍照、低姿/抬头停稳、缓存与传输。 |

文件交接与验收依据见 [系统架构](../docs/design/platform-architecture.md)和[实施指南](../docs/design/implementation-guide.md)。

## 本地启动工作台

使用账号登录的答辩和内测环境见 [团队工作台启动说明](api/platform/README.md)。下面是历史 SQLite 原型的本地启动方式。

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

### 查看三维结果与虚拟取景

- 在工作台的 **查看批次** 选择已完成的批次。**点云** 打开该批次的 GLB，支持拖动、缩放、调节点尺寸和重置视角。**3DGS** 从同源 iframe 加载该批次的 SOG，缺少 SOG 时打开 PLY。
- 创建来源为 **虚拟相机** 的场景，打开 **虚拟相机** 标签。用预设或蛇形机位角度、高度和距离预览取景。点击 **拍摄并上传** 补拍一张，或点击 **环拍并上传 24 张** 完成一圈。上传的照片会自动加入当前布局的待确认批次。
- 点击 **确认照片批次**，分别提交 **多图点云融合** 和 **3DGS 实景重建 → 普通重建**。看到桌上机器人的黄色 **07** 背面徽章后，可移动或旋转展品，捕捉新布局并确认新批次。使用 **查看批次**切换历史，展开 **查看批次的原图顺序** 可在工作台里打开任意原图。 [仿真扫描验收记录](../docs/experiments/sim-scan-demo.md)
- `npm run dev` 和 `npm run build` 从锁定版本的 npm 包复制 SuperSplat 脚本、样式、WASM 和许可到 `public/supersplat/`。生产构建将它们复制到 `dist/supersplat/`，启动 FastAPI 后与工作台同源，浏览无需 CDN。构建会检查 Three.js 仅通过两个三维模块的动态导入加载。

2026 年 11 月 24 日在本机 Edge 验证了上述流程。复用 P3 的真实 GLB 和 32 图 SOG、PLY，验证了点云调参与环绕查看。模拟旧批次晚完成后，正在查看的批次和画布保持稳定。正面、左侧取景上传的两张 RGB PNG 哈希不同，实际 DA3 融合返回 200,000 点，工作台轮询后加载新 GLB。浏览器限制外网访问期间，查看与取景流程未发出外部请求。

## 回归验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix src/web run build
```

## 仿真扫描台简版

准备 Python 3.11+、NumPy、Pillow、SciPy、Node.js，以及项目实测使用的 Brush 0.3.0 和 SplatTransform 3.12.0。在项目根目录运行，指定一个新输出目录和两个工具的实际路径。

```powershell
python src/web/scan-demo/build.py data/sim-workbench-demo `
    --brush 'D:/vision-tools/brush/brush_app.exe' `
    --splat-tool 'D:/vision-tools/node_modules/@playcanvas/splat-transform/bin/cli.mjs'
```

打开生成的 `demo/index.html`。把 `orbitforge-scan-demo.zip`（当前简版脚本打包名暂沿用旧名）解压到同一目录可直接分享两页演示。原始 RGB、毫米深度图、已知相机参数、两组 PLY 和留出渲染保存在输出目录。页面按选定机位取用生成的 RGB-D，交互时执行点云融合，高斯查看器加载预先训练的环拍模型。 [仿真实测记录](../docs/experiments/public-sample-benchmark.md#仿真扫描台简版)

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

高斯作业可用 `--ssim-weight 0.40` 复现结构损失候选。增加 `--eval-split-every 8` 时，Brush 从已注册照片中留出每八张中的一张，保存最后一个检查点的渲染及 `evaluation/holdout.txt`，并在清单中记录哪些照片参与场景优化。候选间需要锁定相机位姿时，使用同一份已注册目录按云试跑手册的命令训练。 [固定留出视角复跑](../docs/design/cloud-pilot.md#3-固定留出视角和参数调优)

点云作业增加 `--with-raw` 时，会在浏览资产导出前同步保存 `raw.npz`，其中包括有序的 RGB、深度、置信度和相机内外参。直接匹配原始输入顺序。外参使用 OpenCV 世界到相机坐标，深度与置信度保留模型原精度。用仿真真值或已知参照统一尺度后再做几何误差评估。未启用该开关时沿用原 GLB 路线。

- [点云作业](workers/point_cloud.py) · [3DGS 作业](workers/reconstruct_gaussians.py)
- [工具版本、权重与复现配置](../docs/design/implementation-guide.md)

## 视频抽帧

安装 FFmpeg 及 Python 3.11 或更新版。先对有重叠的短片段按 2 帧/秒试采样，例如从第 0 秒开始的 12 秒，最多取 24 张候选图。

```powershell
python -m src.workers.extract_frames .\data\scene.mp4 --start 0 --duration 12 --fps 2 --max-frames 24 --output-dir .\data\video-candidates
```

输出有序 RGB PNG 和记录原视频 SHA-256、截取参数、FFmpeg 版本的 `manifest.json`。筛掉重复、模糊或缺少重叠的画面后，按采集顺序提交同一组图片至点云或高斯作业。下一轮改采样频率或区间时使用新的输出目录。 [视频抽帧作业](workers/extract_frames.py) · [视频与云端重建](../docs/design/cloud-pilot.md#4-虚拟蛇形机器人自有视频与预制公开资产)

## 留出视角评估

在含 NumPy、Pillow 和 scikit-image 的 Python 环境运行。冻结留出清单，每行写一个画面文件名。参考目录使用配准准备阶段的 RGB 图，渲染目录只放同批留出画面，文件主名和尺寸保持一致。

```powershell
python -m src.workers.evaluate_renderings --reference-dir .\data\registered\images --render-dir .\data\eval_6000 --holdout-list .\data\holdout.txt --output .\data\eval-6000.json
```

报告记录每张参考图和渲染图的 SHA-256、PSNR、SSIM、强边缘误差，以及均值和各指标最差视角。相同图像的 PSNR 在 JSON 里用空值与精确匹配字段标识。 [评估入口](workers/evaluate_renderings.py) · [精细化验收](../docs/experiments/visual-quality-plan.md)
