# 球形机器人端云空间视觉平台搭建流程

v0.3 · 2026 年 11 月 22 日

适用范围为一个玩具与它附近的桌面。真机与仿真共用后端，照片和结果按来源分开保存。实施时先用手机或公开序列打通软件，再换球形机器人采集。[平台架构](platform-architecture.md) · [当前实测记录](../experiments/public-sample-benchmark.md)

## 1. 定下工作区和展示流程

```text
src/edge/       球形机器人拍照、上传和状态回执
src/api/        场景、目标、照片、任务、结果和设备指令接口
src/workers/    DA3 深度与点云、COLMAP 和 Brush 重建
src/web/        工作台、虚拟相机、点云查看器、高斯查看器
data/           云端持久卷，保存任务数据库、原图、结果与日志
```

现场按「点选或框选玩具 → 首拍看深度 → 换位补拍看点云 → 冻结这一批照片并重建 → 网页环绕查看」操作。仿真入口使用同一流程，先用浏览器生成真实 RGB 截图并上传，再使用云端输出。

| 里程碑 | 动手做什么 | 可以转入下一步的条件 |
| --- | --- | --- |
| P0 素材采集 | 选带纹理、有背面标记的玩具。固定布景，先以手机从相邻机位环拍一组照片，条件允许再补高一点的机位。保存原图。 | 图片清楚、曝光相近、相邻视角有重叠，玩具在各张图中的大小可看清。 |
| P1 模型试跑 | 在 GPU 环境用 DA3-BASE 跑单图和多图。按 1、4、8、16 张记录输出。 | 深度图能对照原图，GLB 中有彩色点，记录耗时和占用。 |
| P2 高斯重建 | 用同一组有足够重叠的照片跑 COLMAP，再用 Brush 或 Splatfacto 训练与导出。先跑公开样例确认环境，再换玩具。 | 能查到照片注册情况，导出的高斯资产能在答辩电脑加载并转到背面。 |
| P3 共用后端 | 创建场景、上传照片、冻结批次、提交作业、查询状态。用手机或网页关联原图及输出。 | 重复提交不会启动重复作业，失败重试能保留上一份有效结果。 |
| P4 网页与仿真 | 接入目标点选、机位清单、原图、深度、点云和 3DGS。让虚拟相机拍两组不同视角并提交。 | 页面显示正确来源与批次，仿真拍摄真的产生新图，云端结果自动刷新。 |
| P5 球形机器人 | 桌上验证相机和上传，再上球验证能换位置、停稳、看准和上传。 | 用此前未拍过的玩具现场操作，从真机照片到网页结果全部可追溯。 |
| P6 联调与提交 | 用同批照片完成 P0 至 P5，在答辩网络验收。测断网、重试和第三方只按说明重跑。 | 手册里的测试目标替换为实测记录，运行说明和现场演示同时通过。 |

P1 与 P2 可并行。机器人未装好时，手机输入和虚拟相机可以测软件部分。最终验收另跑真实球形机器人。

## 2. 先走模型的官方入口

DA3 与高斯重建分开配置。DA3 按 GPU 驱动锁定 Python、PyTorch/CUDA 和模型版本。先按附录 B 复现已在 Windows 验证的 COLMAP + Brush，迁移时核对 Linux 云机的 GPU 与 Vulkan 支持。Splatfacto 是另一套依赖环境，作为备选。记录驱动、依赖版本、仓库提交和模型修订号，确认产物后再封装 API。 [DA3 安装与模型表](https://github.com/ByteDance-Seed/Depth-Anything-3) · [Nerfstudio 安装](https://docs.nerf.studio/quickstart/installation.html)

### DA3 单图和多视角

将照片按拍摄顺序放进 `raw/`，模型在 Worker 启动时加载一次。下面示例同时输出 GLB 和深度可视化。固定首图做参考机位便于比较，同一尺度叠加前另做坐标对齐验证。 [DA3 API](https://github.com/ByteDance-Seed/Depth-Anything-3/blob/main/docs/API.md)

```python
from pathlib import Path

from depth_anything_3.api import DepthAnything3

images = sorted(p for p in Path("raw").iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
model = DepthAnything3.from_pretrained("depth-anything/DA3-BASE").to("cuda").eval()

for label, batch in (("preview", images[:1]), ("fusion", images[:8])):
    model.inference(
        [str(path) for path in batch],
        process_res=504,
        ref_view_strategy="first",
        export_dir=f"trial/{label}",
        export_format="glb-depth_vis",
        show_cameras=False,
        num_max_points=200_000,
    )
```

演示时每新增一轮照片，用**该批次全部已确认的照片联合推理**。单张估得的相对深度各有坐标与尺度，直接拼接单图点云容易出现重影。网页比较两个版本时先并排独立呈现。统一坐标和尺度后，才加入叠加、差异染色或距离量测。限点数是为了传输和显示，不能用点数增长当扫描覆盖率。

### COLMAP 和 Splatfacto（备选）

在含 FFmpeg、COLMAP 和适配 GPU 工具链的 Nerfstudio 环境执行。先使用预览迭代数验证导出，然后在玩具实拍集上按画质和耗时调节。 [自定义图片数据](https://docs.nerf.studio/quickstart/custom_dataset.html) · [Splatfacto 导出](https://docs.nerf.studio/nerfology/methods/splat.html)

```bash
ns-process-data images --data ./raw --output-dir ./ns-data
ns-train splatfacto --data ./ns-data --output-dir ./runs \
  --max-num-iterations 7000 --vis tensorboard
CONFIG=$(find ./runs -name config.yml -print -quit)
# 建议每次试跑使用独立目录，确认 CONFIG 属于本次训练。
ns-export gaussian-splat --load-config "$CONFIG" --output-dir ./exports
```

- 先检查照片注册率和轨迹。背面取景只有在注册且训练覆盖后才计入可验收范围。
- 预处理失败优先补拍中间机位、解决模糊或减少高反光。完成注册后再调高斯训练参数。
- 将导出的高斯 PLY 放在平台同源地址，网页用 SuperSplat Viewer 加载。先验证原始 PLY，素材过大再试压缩。普通彩色点云 GLB 由 Three.js 打开。
- 一个高斯资产先做「玩具近看」「桌面总览」两个镜头。单独的玩具资产按附录 C 裁剪并另存。
- 用一张训练留出的照片作外观检查，完成后可用全部合格图片重建展品。浏览时能看哪些区域以实拍覆盖为准。

## 3. 定义三个端共用的数据关系

```text
场景 Scene           scene_id  source=robot|simulation|sample
目标 Target          target_id  scene_id  reference_frame_id  selection  view_checklist
照片 Frame           frame_id  scene_id  capture_id  view_label  captured_at  sha256  image_url
照片批次 Revision    revision_id  scene_id  ordered_frame_ids
计算任务 Job         job_id  revision_id  kind=depth|fusion|splat
产物 Artifact        artifact_id  job_id  kind  url  size  sha256
```

- 场景创建时标记来源。不同来源用不同场景记录，数据库保存输入列表快照。新照片进入新批次，旧照片与原有结果地址保持可回看。
- 相机可以传曝光/姿态等可选信息。仿真相机的真值只在单独验证时写入，普通推理与真机走同一个 RGB 入口。
- 同一批次分别运行 fusion 和 splat。重试对应原批次；更改输入另开批次。记录实际模型和参数，保证结果可以复现。
- 按文件哈希检测重复且检查 JPEG/PNG 实际解码。相机断网重试时复用同一个 capture_id。避免同一照片因重传被算两次。

| 接口示例 | 请求数据 | 返回与行为 |
| --- | --- | --- |
| POST /api/scenes | title、source | 201，返回 scene_id。 |
| PUT /api/scenes/{id}/target | reference_frame_id、selection、view_checklist | 200，保存当前目标与待拍方向。 |
| POST /api/scenes/{id}/frames | image、capture_id、view_label、captured_at | 201 返回 frame_id。相同 capture_id 和内容重试时返回已有记录。 |
| POST /api/scenes/{id}/revisions | 按拍摄顺序排列的 frame_ids | 201，冻结输入列表。 |
| POST /api/jobs | revision_id、kind、recipe_version（默认 v1） | 202，返回 job_id。相同批次、类型和配方版本复用作业记录。 |
| GET /api/scenes/{id}/jobs | scene_id | 返回该场景下所有批次的作业。 |
| GET /api/jobs/{id} | job_id | 当前返回作业状态和输入批次。阶段、错误码和产物地址随 Worker 接入。 |
| GET /api/scenes/{id} | scene_id | 当前照片、各批次和可打开的历史结果。 |

上传、建批次和开作业按场景鉴权。网页和静态产物通过同源 HTTPS 地址服务。板端可以主动轮询服务器上的拍照指令，以回避现场局域网无法主动连入板端的问题。照片成功入库后确认指令已执行。现场也可从板端按钮触发同一个上传流程。

## 4. 让网页在补拍完成后自动更新

- 操作者在预览原图上选玩具，页面把正、侧、背、顶机位状态和对应照片关联起来。拍照后显示新原图和上传状态。处理阶段按「排队 → 处理中 → 成功或失败」展示。
- 任务状态每 1–2 秒查询一次作为初版建议。成功后加载针对该批次的结果，网页以 **revision_id** 核对当前结果。旧作业晚完成时保留在历史页。
- 首版单卡用一个 GPU Worker 串行执行。短预览任务先进入队列，3DGS 提供独立作业入口和阶段信息。同卡运行长重建期间，预览可能排队。若实测答辩必须两条线同时完成，则采用独立 GPU Worker 或提前安排重建时段。
- 后端使用 FastAPI，SQLite 保存任务和版本，持久盘保存照片和输出。用暂存目录完成导出与校验，再发布产物并更新状态。Worker 重启时回收超时执行记录，保留失败日志和上一份可用结果。
- 浏览器点云用 Three.js 的 GLTFLoader，页面可调点大小和相机视角。高斯用 SuperSplat 嵌入页，资产和查看器版本固定到已测组合。 [Three.js GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html) · [SuperSplat 嵌入文档](https://developer.playcanvas.com/user-manual/supersplat/viewer/embedding/)
- 仿真设置一个球形机器人和可移动虚拟相机。使用该相机渲染到独立画布，调用截图后提交 PNG。虚拟玩具静态放置，换相机位置做融合；移近玩具后单独重拍可以演示深度变化。 [Three.js 渲染目标](https://threejs.org/manual/pages/rendertargets.html)

## 5. 上机配置和故障处理

| 架构位置 | 首版配置 | 联调重点 |
| --- | --- | --- |
| 球形机器人 | 单 RGB 相机、Linux 板端、Wi-Fi、匹配的供电与驱动机构 | 分别测试拍照、机位移动、停车后画面稳定、断网重传。镜头安装要能在不同方向看到玩具。 |
| 云端 | Linux GPU 主机、DA3 与 GS 独立环境、应用及持久磁盘 | 先试租 24 GB 级 NVIDIA GPU，按显存和耗时实测决定配置。核对权重与第三方许可、赛事允许范围。 |
| 演示机 | 浏览器、网页工作台、点云与高斯查看器 | 同一环境打开空场景、真实模型输出和离线保留的结果，检查网络、加载与交互。 |

| 症状 | 优先检查 |
| --- | --- |
| 点云层层重影 | 相邻机位是否有重叠，是否跑同一批多图推理，坐标系是否误用。 |
| 背面糊或 GS 漂浮物明显 | 对照背面原图、照片注册结果和视角覆盖，先补拍过渡角度。 |
| 网页只看到空白 | 核实 HTTP 状态、文件大小和解析器。点云 GLB 与高斯 PLY 各用对应查看器。 |
| 云端慢或显存告急 | 分开测照片上传、排队、计算、导出、下载。先限制批量与输出点数，再根据画质和峰值决定 GPU。 |
| 赛场网络不通 | 用已生成并保存的同场景记录演示可交互结果，明确显示原始批次与生成时间。真实采集恢复后重新提交。 |

## 6. 验收时要留的证据

记录日期、来源、场景编号、照片数量和尺寸、配置版本、开发机与云卡型号、GPU 峰值、各阶段耗时。一个用例至少留原图、任务记录、可打开的产物和一张结果截图。重复测量保留各次原始值，正式赛前用答辩网络再测一次。

| 场景 | 可检查的判定 |
| --- | --- |
| 单图深度 | 原图中近远已知的物体，在深度显示与点云中呈现合理层次。标明相对深度。 |
| 补拍后更新 | 点选的目标、已拍机位和对应原图可回看。新批次能查看真实拍到的背面与贴纸，旧批次仍可打开。深度图和点云显示同一个输入版本。 |
| 3DGS | 从同组原图重建并在浏览器打开。玩具近看、桌面总览与绕看实拍覆盖区域均正常。 |
| 仿真 | 两次机位有变化，上传文件不同，任务来源为仿真。界面在计算完成后换到正确结果。 |
| 故障恢复 | 重复提交、上传失败、重新连线和旧作业延迟返回都能复现，历史产物可回看。 |

建议三人按板端与采集、模型与部署、平台与仿真分工。大家共享同一份素材和接口定义。首版如实记录点云“每批计算后刷新”耗时，以及浏览器加载 3DGS 后的交互表现。

## 附录 A 公开素材复现记录

素材来自 DA3 官方演示空间的 [DL3DV_10K_a401469cb0 文件夹](https://huggingface.co/spaces/depth-anything/depth-anything-3/tree/cfa6140634d538a5a3609178ae7a9fdc3e91a514/workspace/gradio/examples/DL3DV_10K_a401469cb0)。下载该文件夹的 32 张 PNG。以下记录来自开发机 RTX 4060 Laptop 8 GB，用于验证实现和接口。正式答辩另用球形机器人拍摄自己的玩具。

- DA3 源码提交为 `3d835ec1a5802d64a8b8b15f817a1ab54809bfe4`。DA3-BASE 权重版本为 `f4a6c9b3c95e41c82048423d3493a81ec3fa810e`，DA3-GIANT-1.1 权重版本为 `72ee9f89ce4e50d704e9d55ee9c646ec8dc25a19`。
- 实测用 Python 3.12、PyTorch 2.11.0 cu128、NumPy 1.26.4、PyCOLMAP 4.2.1。DA3 API 从固定提交的 `src` 导入，使用官方权重。保持 PyTorch CUDA 版本及推理依赖匹配。
- DA3-BASE 按文件名顺序取 1、4、8、16 张，处理分辨率参数 504，最多导出 20 万点。预热一次后，每组各跑三次，计时含预处理、推理和本地导出。多图基准用默认 `saddle_balanced` 选参考图。
- 单图至 16 图的本机中位数分别约为 **0.16、0.45、0.81、1.65 秒**。8 图点云文件约 3.05 MiB，已在 Edge 的 Three.js 测试页加载到 20 万点。上传、队列和下载应另计。
- 仿真浏览器实际生成四张不同机位的 PNG。用本机 HTTP 验证上传、提交、轮询和下载，1 图约 0.88 秒，4 图约 0.66 秒，各测一次。第一组含首次推理开销。重复提交复用了任务号，无效图片被拒绝。
- DA3-GIANT-1.1 以 336 处理分辨率、8 张照片生成约 26.91 MiB 高斯 PLY，已在 SuperSplat 加载。该批次画面有明显模糊和边缘拉伸，适合作为接入和快速预览验证。
- COLMAP 在长边 900 时，用间隔抽取的 16 图得到规模最大的 8 图子模型，全量 32 图得到规模最大的 27 图子模型。全量 32 图、长边 1200 时形成单个 32 图子模型。不同子模型可以包含相同照片。检查最大子模型的照片数，并逐一核对侧面和背面照片是否注册。正式素材需独立复测。

如果只要 DA3 高斯资产，固定上述提交并把预测和导出分开。该版本的统一导出入口可能同时尝试新视角视频渲染，下面是已经验证的纯 PLY 调用。

```python
from depth_anything_3.api import DepthAnything3
from depth_anything_3.utils.export.gs import export_to_gs_ply

model = DepthAnything3.from_pretrained("depth-anything/DA3-GIANT-1.1").to("cuda").eval()
prediction = model.inference([str(path) for path in images[:8]], process_res=336, infer_gs=True)
export_to_gs_ply(prediction, "./trial/fast-splat")
```

这里的 `images` 是同一静态场景的 8 个 RGB 文件路径。高斯权重的许可和赛事适用范围应按官方型号表确认。

## 附录 B 已验证的高斯训练入口

在 Windows 上使用 [Brush v0.3.0 官方发布包](https://github.com/ArthurBrussee/brush/releases/tag/v0.3.0)。把同一批 RGB 文件放在 `images/`，COLMAP 输出放在 `sparse/0/`。三个基本模型文件是 `cameras.bin`、`images.bin`、`points3D.bin`。

```powershell
# 在放置 brush_app.exe 和 colmap-data 的目录下执行
.\brush_app.exe .\colmap-data --total-steps 2000 --max-resolution 900 --max-splats 300000 --eval-split-every 8 --eval-every 500 --eval-save-to-disk --export-every 1000 --export-path .\brush-output
```

如需复现照片注册，使用 PyCOLMAP 4.2.1 的 CPU 特征提取与全量匹配后运行增量重建。试验将原图变换到长边 1200 像素后处理，共用一套相机内参。将选定子模型保存在 sparse/0 目录并检查注册清单。

32 张均注册后，按每 8 张留一张进行外观检查。2,000 步训练加评估和导出本机约 **32 秒**，最终高斯 PLY 约 **1.86 MiB**。该计时从启动 Brush 到进程结束，COLMAP 预处理与页面加载另计。训练完成后，先检查留出机位渲染图，再让网页加载导出文件。云端可以先验证同版本 Brush 的 Vulkan GPU 运行条件，或按第 2 节走 COLMAP 和 Splatfacto。 [Brush 文档](https://github.com/ArthurBrussee/brush)

较早的 8,000 步试验在同一硬件耗时 **133.74 秒**，输出约 **21.97 MiB**，4 个留出机位的平均 PSNR 为 **19.54 dB**。这些机位已参与相机注册，随后从高斯训练照片中留出。在不同设置下先固定数据切分，记录玩具纹理、贴纸和边缘是否清楚，再决定训练时长。现场如果用独立重建任务，分别记录开始、完成、首次可交互的时间。后续完整资产复跑的设置、计时和画质见[公开样例实测](../experiments/public-sample-benchmark.md)。

## 附录 C 同批照片输出场景和独立玩具

首版先在同一高斯资产上配置近看玩具和桌面总览两个镜头。同一份模型可放在两个页面入口。需要单独的高斯玩具文件时，保留场景原件，在 SuperSplat 内用三维区域选择框选玩具，旋转检查选区，再分离为新资产。保存为 `toy.ply`，独立记录其父场景、照片批次、裁剪工具版本与日期。玩具底面和边缘保留情况按实拍覆盖验收。 [SuperSplat 选择与裁剪](https://developer.playcanvas.com/user-manual/gaussian-splatting/editing/supersplat/editing-splats/)

## 交付前的复核顺序

1. 把手机样例换成真机新拍的玩具照片，检查上传回执与任务来源。
2. 分别在开发网、现场网络用 1 图和 8 图记录完整耗时。内测暂用单图 5 秒、8 图融合 10 秒作为改进目标，以现场数据更新要求。
3. 冻结一批确认覆盖的照片，跑最终高斯训练，保留注册报告、导出资产和浏览器视角检查。现场若用预先训练结果，选择对应的历史任务。
4. 检查仿真能生成新 RGB 图、点云计算后能刷新。与真机版本使用同一套接口与查看器。
5. 将已有设计文档的候选模型、运行条件和占位测试换成实际版本及结果，依赛事要求核验授权、匿名材料和运行入口。
