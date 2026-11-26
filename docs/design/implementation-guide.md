# SplatForge · 灵境智绘实施指南

面向受限空间的仿生蛇形 3DGS 与多维空间视觉仿真工作台 · v0.5 · 2026 年 11 月 23 日

本阶段并行推进本机视觉基线和云 GPU 试部署。开发电脑用素材目录、CLI、日志与查看器复现多视角点云和 3DGS。云端用 RTX 4090 或 RTX 5090 复跑同一公开原图批次，从自有域名打开本轮生成的资产。内嵌工作台验证新图、位姿和交互结果，正式前后端、作业 API 和实体蛇形机器人通信随联调推进。 [执行方案](execution-plan.md) · [架构](platform-architecture.md) · [云 GPU 试部署](cloud-pilot.md) · [公开实测](../experiments/public-sample-benchmark.md)

## 1. 准备素材与离线环境

本地采集工作台已接入真实 DA3 和 3DGS 作业。浏览器通过 `POST /api/jobs` 提交，通过 `GET /api/scenes/{scene_id}/jobs` 查询状态和产物。普通 3DGS 配方接受满足最低配准条件的部分注册，公开 32 图验收配方要求 32/32 后才发布。 [工作台启动](../../src/README.md#本地启动工作台) · [P3 工作台 GPU 实测](../experiments/workbench-gpu-smoke.md)

在联网准备阶段下载固定版本的工具、模型权重和公开素材。准备 Python 环境、DA3 权重、本地浏览模块、Brush、SplatTransform，以及视频线路使用的 FFmpeg，记录来源、版本、输入尺寸和设备信息。本机验证以已经跑过样例的 RTX 4060 Laptop 8 GB 为起点。目录为验证约定，可按实际工作盘安排。

```text
models/DA3-BASE/                    DA3 本地权重及配置
data/<scene-id>/raw/                原图或选出的真实视频帧
data/<scene-id>/batches/            有序照片清单与布局快照
data/<scene-id>/runs/<run-id>/      配置、注册摘要、日志、GLB、PLY、SOG
data/<scene-id>/viewer/             本地查看资源或单文件示例
```

| 顺序 | 做什么 | 完成条件 |
| --- | --- | --- |
| 1 | 公开 RGB 跑 DA3 多图，打开彩色点云。用少量邻近视角和补过侧、背面的另一批分别计算。 | 两批原图和 GLB 可追溯，能核对新增可见表面。 |
| 2 | 同批 RGB 跑 COLMAP + Brush，再将 PLY 转为 SOG。独立打开预制公开高斯资产。 | 注册报告、PLY 与 SOG 都保留。在浏览器可加载并在已覆盖区域连续换视角。 |
| 3 | 加可操作的仿真取景样件，实际移动蛇形本体、相机及桌面摆设，导出新 RGB。 | 仅移动相机的输入可做补扫，移动展品后创建新快照并用新图独立重建。 |
| 4 | 用户离线提供真实 MP4 后，保存原片并筛选关键帧，检查注册，再在本机或云端优化 3DGS。 | 演示前准备可打开的 3DGS，留存原片、关键帧、注册摘要、优化日志和实际覆盖。 |
| 5 | 断开外网，执行已准备的本地流程，保存产物和复跑步骤。 | 能在离线环境重新生成点云和 3DGS，公开成果和已导出的单文件可独立打开。 |

本机复现与云端试部署可同时开始。云端先复跑同一批公开 RGB，从自有域名验证新生成的轻量资产加载和互动，再试自录片段或较大房间。公开原始 RGB、真实 MP4 关键帧及虚拟蛇形机器人生成的新 RGB 共用批次清单、注册摘要和 PLY/SOG 约定。预制公开高斯资产作为浏览对照。 [云 GPU 试部署](cloud-pilot.md)

## 2. 运行本地视觉作业

### DA3 多视角点云

将已确认的同一静态布局的照片按捕获顺序编号。用预训练 DA3-BASE 本地推理，至少测一批邻近照片和补拍后的更完整批次。下面用最前面 4、8 张说明两批实验，实际按有序清单选择真实补拍照片，关键侧、背面应在第二批中出现。单图深度和深度热图可用于诊断前后层次。[DA3 安装与模型表](https://github.com/ByteDance-Seed/Depth-Anything-3) · [DA3 API](https://github.com/ByteDance-Seed/Depth-Anything-3/blob/main/docs/API.md)

```python
from pathlib import Path

from depth_anything_3.api import DepthAnything3

images = sorted(path for path in Path("raw").iterdir()
                if path.suffix.lower() in {".jpg", ".jpeg", ".png"})
model = DepthAnything3.from_pretrained("models/DA3-BASE").to("cuda").eval()

for label, batch in (("initial", images[:4]), ("supplemented", images[:8])):
    model.inference(
        [str(path) for path in batch],
        process_res=504,
        ref_view_strategy="first",
        export_dir=f"trial/{label}",
        export_format="glb",
        show_cameras=False,
        num_max_points=200_000,
    )
```

要同时导出深度热图，将 `export_format` 设为 `glb-depth_vis`。需要与单图对照时单独用 `images[:1]`。两批的点云先分别打开，用补拍原图核对新增可见表面。每批联合估计的尺度和坐标可能不同，做叠加或距离量测前先配准和标定。点数限制用于显示开销控制。

### COLMAP、Brush 与 SOG

1. 用已确认的原图批次跑 PyCOLMAP 的 CPU SIFT、匹配与增量重建，公开基准见附录 B。检查最大子模型、相机轨迹和各关键视角。背面标记至少有一张清晰的已注册照片参与高斯优化。如做留出评估，选可对照的过渡视角。
2. 结合附录 B，用 Brush 导出完整 PLY，分别看展品近景、总览和换位时的边缘表现。当前条件下失败优先核对模糊、反光、遮挡、曝光和相邻重叠，登记需要补拍的机位。
3. 将同一完整模型转换为 SOG，保留 PLY 作为源资产。在准备阶段取得 SplatTransform 3.12.0。下列命令使用已安装的本地 CLI，设备编号按实际列表选择。生成单文件时省去 `--unbundled`。拆分版可用本机静态文件服务打开，单文件可直接打开。[SplatTransform](https://github.com/playcanvas/splat-transform)

```powershell
splat-transform --list-gpus
splat-transform -g 0 --unbundled export_8000.ply viewer/index.html
splat-transform -g 0 export_8000.ply viewer-offline.html
python -m http.server 8000 --bind 127.0.0.1 --directory viewer
```

点云 GLB 用已有点云查看器或 Three.js 测试页。完整 PLY 与 SOG 用高斯查看器。GS 资产可以预先加载并实时换视角，分别计注册、优化、转码、打开到首帧和首次可操作。固定浏览器、分辨率与视角路径，记录连续换位的帧间隔、关键画面和测试网络。高斯浏览耗时与重建耗时采用各自起点。[点云查看入口](https://threejs.org/docs/pages/GLTFLoader.html) · [高斯查看器](https://developer.playcanvas.com/user-manual/supersplat/viewer/)

## 3. 仿真场景、照片与批次

- 用独立相机渲染相同场景中的当前 RGB。仿真界面允许摆放或移动物体、移动蛇形本体并调整其蛇头低机位与抬头朝向，取景画面随着相机变化。用机位和画面校对相机确实随蛇头到达预期位置。采集时去掉屏幕标注、控制组件，以及跟随相机移动的机身可视层。[Three.js 渲染目标](https://threejs.org/manual/pages/rendertargets.html)
- 拍摄前保存布局快照，包含参与重建的摆设和环境。只挪蛇形本体与相机，沿用该快照追加视角。移动、旋转或增删参与重建的物体后另建布局版本，从新布局重新采集。先取有重叠的正、侧、背和过渡视图，保存旧原图与旧结果供回看。
- 保存 `scene_id`、`layout_id`、素材来源、`frame_id`、机位、有序原图清单与 `revision_id`。选存仿真的相机内外参用于诊断。主流程用原图注册，保证能联用真实输入。每次计算保留工具版本、参数、生成时间和日志，绑定所用 `revision_id`。
- 成功产物单独保存。重跑使用独立运行目录，核对清单和输出后再作为有效结果，保留之前可打开的版本。

## 4. 公开与自有素材的前置条件

| 输入 | 前置条件 | 操作 |
| --- | --- | --- |
| 预制公开高斯资产 | 下载可被本地查看器读取的 SOG 或高斯 PLY，核对格式、版本及素材授权。 | 作为浏览对照直接加载，检查连续转向和移动，记录首帧、交互或显示异常。 |
| 公开原始 RGB | 选择有连续视角和同一静态场景的素材，记录原始来源与版本。 | 同一批次分别运行本机与云端注册和高斯优化，保留完整资产、留出渲染及分段计时。用 DA3 导出点云。 |
| 用户离线提供的真实 MP4 | 固定场景与焦段，沿可达区域平移或绕拍，保证相邻重叠、稳定照明和清晰度。可从书桌及邻接角落开始。被遮挡的台沿以及纹理较少的墙面和地面需检查覆盖。 | 保存原片与关键帧，筛除抖动、模糊和过密帧。检查机位及注册结果，再在本机或云端训练与导出，演示前准备资产。 |
| 已拼接球面全景 | 保存全景图并确认投影格式。若自采双鱼眼或全景视频，先确认相机模型、标定或拼接方式，再评估能否直接接入重建。 | 单站全景可转头查看。要用 3DGS 连续走动，需相邻站点或普通相机轨迹中有实际位移与共视区域。 |

普通视频先用 `python -m src.workers.extract_frames input.mp4 --duration 12 --fps 2 --max-frames 24 --output-dir data/video-candidates` 取首批候选帧。按清晰度、视差和重叠调整区间与采样频率。选定后保留有序 PNG、视频哈希和参数清单，并用同一组入选图运行本机或云端重建。全景浏览的范围以输入观察到的区域为准。 [视频作业](../../src/README.md#视频抽帧) · [COLMAP 采集建议](https://colmap.github.io/tutorial.html)

## 5. 视觉验证与平台接入条件

| 检查项 | 通过依据 |
| --- | --- |
| 仿真取景与物体移动 | 蛇形本体换位或抬头后捕获不同原图，同布局内可追加补扫。另移动桌面摆设并拍摄，产生新布局，旧布局照片仍可回看。 |
| 多视角点云 | 补拍批次出现新观察到的表面，能打开对应 RGB。保留两批导出物，并记录处理与打开耗时。 |
| 3DGS 生成及已有场景浏览 | 三条输入路线分别留存注册和优化记录，核对各自 PLY、SOG 与实际覆盖。虚拟展品的背面关键图参与优化。预制公开资产用于查看器对照。 |
| 离线回放和复跑 | 环境准备后断开外网，重新启动，完成取图、作业与输出浏览。在独立查看器中另打开公开高斯和离线单文件。 |
| 云 GPU 与域名预览 | 云端实跑同一公开照片批次，记录实际 GPU 型号、显存、工具版本和分段耗时。从自有域名打开本轮生成的资产，检查首次可交互时间及连续换视角。 |

记录每次输入、机型、版本和边界。工作台内先确定可重复的视觉交付。云端并行验证 GPU 相容性和真实网络加载，保留同输入对照。云端样例通过后再扩展较大室内场景。 [云 GPU 试部署](cloud-pilot.md)

## 附录 A 公开素材复现记录

素材来自 DA3 官方演示空间的 [DL3DV_10K_a401469cb0 文件夹](https://huggingface.co/spaces/depth-anything/depth-anything-3/tree/cfa6140634d538a5a3609178ae7a9fdc3e91a514/workspace/gradio/examples/DL3DV_10K_a401469cb0)。下载该文件夹的 32 张 PNG。以下记录来自开发机 RTX 4060 Laptop 8 GB，用于比较输入、配置、输出及耗时。独立复跑仿真和用户自有素材时，记录为不同来源。

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

这里的 `images` 是同一静态场景的 8 个 RGB 文件路径。该片段用于复现实验。离线时将模型名改为已准备的本地权重目录。高斯权重的许可和赛事适用范围应按官方型号表确认。

## 附录 B 已验证的高斯训练入口

在 Windows 上使用 [Brush v0.3.0 官方发布包](https://github.com/ArthurBrussee/brush/releases/tag/v0.3.0)。把同一批 RGB 文件放在 `images/`，COLMAP 输出放在 `sparse/0/`。三个基本模型文件是 `cameras.bin`、`images.bin`、`points3D.bin`。

```powershell
# 在放置 brush_app.exe 和 colmap-data 的目录下执行
.\brush_app.exe .\colmap-data --total-steps 2000 --max-resolution 900 --max-splats 300000 --eval-split-every 8 --eval-every 500 --eval-save-to-disk --export-every 1000 --export-path .\brush-output
```

如需复现照片注册，使用 PyCOLMAP 4.2.1 的 CPU 特征提取与全量匹配后运行增量重建。试验将原图变换到长边 1200 像素后处理，共用一套相机内参。将选定子模型保存在 sparse/0 目录并检查注册清单。

32 张均注册后，按每 8 张留一张进行外观检查。2,000 步训练加评估和导出本机约 **32 秒**，最终高斯 PLY 约 **1.86 MiB**。该计时从启动 Brush 到进程结束，COLMAP 预处理与页面加载另计。训练完成后，先检查留出机位渲染图，再让网页加载导出文件。先在本机确认使用独立显卡。后续迁移到云机时，验证同版本 Brush 的无桌面 GPU 环境，或单独复测 Splatfacto 备选路线。 [Brush 文档](https://github.com/ArthurBrussee/brush)

较早的 8,000 步试验在同一硬件耗时 **133.74 秒**，输出约 **21.97 MiB**，4 个留出机位的平均 PSNR 为 **19.54 dB**。这些机位已参与相机注册，随后从高斯训练照片中留出。在不同设置下先固定数据切分，记录玩具纹理、贴纸和边缘是否清楚，再决定训练时长。现场如果用独立重建任务，分别记录开始、完成、首次可交互的时间。后续完整资产复跑的设置、计时和画质见[公开样例实测](../experiments/public-sample-benchmark.md)。

## 附录 C 同批照片输出场景和独立玩具

首版先在同一高斯资产上配置近看玩具和桌面总览两个镜头。同一份模型可放在两个页面入口。需要单独的高斯玩具文件时，保留场景原件，在 SuperSplat 内用三维区域选择框选玩具，旋转检查选区，再分离为新资产。保存为 `toy.ply`，独立记录其父场景、照片批次、裁剪工具版本与日期。玩具底面和边缘保留情况按实拍覆盖验收。 [SuperSplat 选择与裁剪](https://developer.playcanvas.com/user-manual/gaussian-splatting/editing/supersplat/editing-splats/)
