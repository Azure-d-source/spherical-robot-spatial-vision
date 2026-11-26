# OrbitForge · 球迹视界

**球形机器人端云协同三维扫描系统**

从球载视角出发，把多视角照片变成可以走近、绕行和回看的三维场景。OrbitForge 将虚拟取景、真实照片与视频、预生成高斯场景接入同一个扫描工作台。开发机负责建立基线，云 GPU 承担重建试跑和参数对照，浏览器负责交互展示。

## 三条场景路线

| 场景 | 输入与流程 | 要交付的体验 |
| --- | --- | --- |
| **真实公开场景** | 固定一组公开多视角原图，实际运行 COLMAP 与 Brush，导出高斯 PLY 和 SOG。另加载一份标注来源的预生成公开室内资产。 | 浏览由团队重建的真实场景，对照公开资产的加载、轮廓与视角覆盖。 |
| **自己的视频** | 提前导入手机 MP4，抽取有视差和重叠的关键帧，用同一条重建流程在本机或云 GPU 运行。 | 打开事先重建的书桌或室内局部，从实际拍摄覆盖的区域连续移动视角。 |
| **仿真球扫描** | 在内嵌工作台摆放展品和虚拟球，球载相机跟随移动。沿实际机位保存 RGB，生成多视角点云和 3DGS。 | 从正面补到背面，用原图核对新增表面。挪动展品后，镜头与新一轮扫描随布局更新。 |

同批照片可分别生成**彩色点云**和**可漫游的 3DGS**。点云用于核对补拍覆盖，深度图按需用于诊断。浏览器实时渲染已加载的高斯资产，照片注册、场景优化和导出分别计时。

## 本机基准与云端试验

**已经跑通。** RTX 4060 Laptop 上，DA3-BASE 生成了单图与多图点云。公开 DL3DV 样例的 **32 张照片全部注册**，同一高斯资产从 **24.55 MiB PLY 压到 1.89 MiB SOG**。Edge 已验证拖动和移动视角。模拟 10 Mb/s 且启用 HTTP gzip 时，SOG 版本三次首帧中位数为 **2.58 秒**。仿真原型已生成不同机位的 RGB 并运行本机点云推理。 [完整实测与计时口径](docs/experiments/public-sample-benchmark.md)

**本轮工程重点。** 用同一公开批次对照训练步数和画质，准备在 RTX 4090 24 GB 或 RTX 5090 32 GB 上复跑。固定输入与留出视角，记录配准、耗时、显存和浏览性能。通过云机实测后，用已有域名交付可访问的浏览入口。自录视频和仿真工作台沿用同一套视觉产物格式。 [执行方案](docs/design/execution-plan.md) · [云 GPU 试跑与域名发布](docs/design/cloud-pilot.md)

## 开发入口

- [本地启动工作台](src/README.md#本地启动工作台) · [P3 本机 GPU 联调记录](docs/experiments/workbench-gpu-smoke.md)
- [视觉作业与运行命令](src/README.md#本地视觉作业) · [数据组织](data/README.md)
- [项目总览](docs/design/project-overview.md) · [系统架构](docs/design/platform-architecture.md) · [实施指南](docs/design/implementation-guide.md)
- [三维查看与虚拟取景](src/README.md#查看三维结果与虚拟取景)
- [技术调研](docs/research/spherical-robot-spatial-vision.md) · [参赛与交付清单](docs/competition/submission-checklist.md)
