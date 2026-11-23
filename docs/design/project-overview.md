# OrbitForge · 球迹视界

**球形机器人端云协同三维扫描系统**

2026 年 11 月 23 日 · v0.5 · 当前执行路线

## 1. 作品与现阶段范围

OrbitForge 把球形机器人的移动取景变成可以回看、补拍的三维扫描。方案以一件背面有标记的展品为例：球从正面绕到侧面和背面，沿途照片按机位进入工作台。操作者在分批点云中核对新拍到的表面，再从桌面总览移动到展品近景，在 3DGS 实景中查看背面标记、细边和纹理。

**本机复现与云端试部署并行。** 本机 RTX 4060 Laptop 建立可离线复跑的视觉基线。云端用单张 RTX 4090 或 RTX 5090 复跑同一公开原图批次，完成注册、高斯训练和导出，并从自有域名预览生成的资产。内嵌工作台优先验证取景、点云和 3DGS，深度图用于诊断。正式前后端和实体球通信随联调推进，较大室内范围在小样跑通后分块扩展。 [执行方案](execution-plan.md) · [云 GPU 试部署](cloud-pilot.md)

## 2. 三条输入与演示路线

| 操作 | 输入与流程 | 交付证据 |
| --- | --- | --- |
| **公开实拍 RGB** | 冻结公开多视角原图，运行点云、相机注册和高斯优化，导出 PLY 与轻量浏览资产。同一批输入在本机和云端复跑。 | 原图清单、注册与训练日志、从原图生成的 3DGS、留出画面和分段计时。预制公开资产作为查看器对照。 |
| **自录真实 MP4** | 用户离线提供原片。选择有实际位移、相邻重叠且清晰的关键帧，检查注册，再在本机或云端生成 3DGS。演示前准备好资产。 | 原片、关键帧清单、注册摘要、优化日志、生成资产及实际覆盖范围。 |
| **内嵌虚拟仿真** | 在工作台内摆放目标和移动小球，球体相机随位姿更新并生成新 RGB，以新图实际生成点云和 3DGS。 | 展示球体和展品移动后画面更新，再固定布景采集多个视角。补拍后对照点云和原图，在高斯场景中回看背面标记。 |

虚拟展品可以在开始扫描前重新摆放。采集中若改变展品位置或布景，另建扫描批次，保持每次多视角输入的场景一致。已有 3DGS 资产可直接加载。实景重建要准备多个位置的清晰共视画面，固定物体、光线和焦段，重点检查侧面、背面及中间机位能否注册到同一场景。 [COLMAP 采集与重建教程](https://colmap.github.io/tutorial.html) · [高斯资产格式](https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/)

## 3. 视觉路线与验收

- **点云。** DA3-BASE 从已确认的一张或多张 RGB 图估计深度和相机参数，导出彩色点云。补拍后查看新的批次，并用对应原图核实新增表面。做点云叠加或量测前，先统一坐标和尺度。 [DA3 论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/e4cd50120b6d7e8daff1749d6bbaa889-Abstract-Conference.html) · [DA3-BASE 模型卡](https://huggingface.co/depth-anything/DA3-BASE)
- **3DGS 重建。** 以 COLMAP + Brush 为当前基线，用确认后的同批原图求解位姿和优化高斯，保存注册摘要、完整版 PLY 及经实测的 SOG 展示资产。用同素材、同留出视角检查背面标记、细边、纹理和遮挡交界，分别测记注册、优化和导出时间。 [3DGS 原论文](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/) · [Brush v0.3.0](https://github.com/ArthurBrussee/brush/releases/tag/v0.3.0)
- **3DGS 展示。** 查看器加载准备好的公开场景或刚生成的高斯资产，可围绕展品移动视点，或在拍摄覆盖充分的室内区域浏览。记录加载到首次可交互的时间，以及拖动和缩放时的流畅度。若输入只有已拼接的 360° 全景图，可先在固定站点环看。做可移动视点的真实场景重建仍需有位移和重叠的多视角素材。 [SuperSplat Viewer](https://developer.playcanvas.com/user-manual/supersplat/viewer/)
- **质量与速度。** 先检查清晰度、拍摄覆盖与注册情况，再用同一场景同一视角比较完整与轻量资产。有明确锯齿或闪烁问题再试 Mip-Splatting。需要表面网格或量测时，可试 2DGS 并对照已知尺寸。 [Mip-Splatting](https://github.com/autonomousvision/mip-splatting) · [2DGS](https://surfsplatting.github.io/)

## 4. 现有证据

公开实拍素材来自 DA3 官方示例中的 DL3DV 玩具陈列区。以下为本机 RTX 4060 Laptop 试跑结果，工作台整合、个人导入素材和比赛演示电脑仍需实测。

| 验证项 | 已看到的结果 |
| --- | --- |
| 点云 | 公开样例单图、8 图、16 图处理并导出的中位数约为 0.16、0.81、1.65 秒。 |
| 虚拟相机 | 4 个虚拟机位生成不同 RGB，已跑通本机提交推理和取回点云。 |
| 3DGS | 公开 32 图全部注册。两轮以各自配置复跑，从注册到导出约 2–4 分钟，输出的高斯资产已在本机浏览。 |
| 轻量浏览资产 | 后续复跑输出约 24.55 MiB PLY，可压成约 1.89 MiB SOG。压缩时长与浏览加载单独记录。 |

输入、配置、质量结果和计时口径见[公开样例实测记录](../experiments/public-sample-benchmark.md)。

本轮需要交付可操作的仿真取景样件、三条路线的重建产物、云 GPU 同批对照和自有域名预览地址。自录素材重建、工作台完整流程、云 GPU 与域名加载表现待实测。

## 5. 项目资料

- [执行方案](execution-plan.md)记录本轮实现与验收。[云 GPU 试部署](cloud-pilot.md)记录服务器、环境和域名验证步骤。
- [平台架构](platform-architecture.md)与[实施指南](implementation-guide.md)记录作业分工、数据关系和技术入口。
- [参赛与交付清单](../competition/submission-checklist.md)记录赛事原通知要求与当前证据项。
- [球形机器人空间视觉技术调研](../research/spherical-robot-spatial-vision.md)与[4C 人工智能应用国奖作品调研](../research/4c-award-review.md)记录技术路线与竞赛案例。
- [团队 GitHub 仓库](https://github.com/Azure-d-source/spherical-robot-spatial-vision)用于同步项目文档和开发成果。
