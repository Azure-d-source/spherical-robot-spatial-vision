# 仿生蛇形机器人与空间视觉技术调研

2026 年 11 月 23 日 · 视觉基线、近年工作与后续部署

## 场景与核心问题

先用公开照片固定本机点云与 3DGS 基线，并用同批素材准备云 GPU 对照。在仿真桌面验证带背面标记的展品，移动虚拟蛇形机器人并通过低机位与抬头补拍，核对新增表面。用户视频抽帧后走同一条作业链路。扫描效果取决于相机位置、朝向、清晰度和覆盖。 [执行方案](../design/execution-plan.md) · [云端试验](../design/cloud-pilot.md)

## 蛇形平台如何采到可重建的照片

- **单目依然能做多视角。** 单目指每次由一台 RGB 相机取景。要获得与深度有关的视差，需要相机到不同位置观察同一静态场景。蛇头原地摆头俯仰有助于换取景方向，靠低姿蜿蜒位移获取新视差和遮挡后的新表面。[COLMAP 采集建议](https://colmap.github.io/tutorial.html)
- **用仿真与手机复核采集条件。** 仿真先选哑光、有纹理、带背面标记的对象，保证光线和布景稳定、相邻图之间有重叠。蛇形本体换位时保持布景固定，移动展品后另建版本。后续用手机自录小场景，检查关键方向是否注册及是否拍到目标表面。
- **接入实体蛇形机器人时验证“走到、看准、停稳”。** 在实际蛇头模组里复核镜头视野、结构遮挡、最低离地高度、抬头俯仰角与停稳抖动。低机位之外的覆盖来自蛇头抬升形成的高机位与俯角。运动停稳后首张清晰图的等待时间、不同朝向清晰率和有效机位可作为硬件取景指标。
- **同一批扫描保持物件静止。** 相机在布景周围移动。网页的虚拟相机同样移动机位。若在仿真中挪动物件来演示远近变化，另开一次观察任务。

## 三种输出的关系

| 功能 | 用什么输入 | 演示什么 | 判断标准 |
| --- | --- | --- | --- |
| 单图相对深度 | 一张 RGB，用 DA3-BASE 按需导出可视化 | 对照原图定位点云断层或纹理区域的深度异常 | 给色带加远近标签。距离数值需要尺度标定与实物复核。 |
| 多视角补扫和点云融合 | 首拍和已确认的新机位照片，一起运行 DA3-BASE | 旋转看各批次点云，核对新补拍的侧面、背面 | 从新点云指到对应原图。坐标和尺度统一后再叠加对比，抽样点数用于控制展示开销。 |
| 3DGS 实景重建 | 同一批原始 RGB，经 COLMAP 注册后用 Brush 训练 | 从桌面总览切到玩具近看，绕到实拍覆盖的背面 | 核对留出图、实物标记、边缘和首屏交互时间。几何精度另用已知尺寸样件验证。 |

**术语建议。** 对外称“点云补扫与多视角融合”。如果后续使用点云补全模型，单独标出模型推断的区域。3DGS 主讲多视角重建和实景浏览，团队成果落在设备取景、目标引导、数据传递、异步作业及真假输入共用平台。

## 相关工作与选择依据

| 工作 | 当前用法与验证条件 |
| --- | --- |
| [Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3) · [ICLR 2026 论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/e4cd50120b6d7e8daff1749d6bbaa889-Abstract-Conference.html) | 原型采用 BASE 估计深度和相机参数并导出点云。快速高斯变体可作预览对照，现有试跑有明显模糊。 |
| [COLMAP](https://colmap.github.io/) · [Brush](https://github.com/ArthurBrussee/brush) · [原始 3DGS](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/) | 当前验证的完整场景路线。决定质量前先看关键机位的注册、照片清晰度和遮挡覆盖，再调训练与输出。 |
| [2DGS](https://surfsplatting.github.io/) · [Mip-Splatting](https://github.com/autonomousvision/mip-splatting) | 2DGS 可作为表面重建和网格候选。Mip-Splatting 可用于多尺度渲染的锯齿、闪烁对照。采用哪个取决于当前误差类型。 |
| [SuperSplat Viewer](https://developer.playcanvas.com/user-manual/supersplat/viewer/) | 展示已生成的资产。用同一视角和浏览器对照完整、轻量版本，记录下载、首屏、帧率和画质。 |
| [PoinTr](https://github.com/yuxumin/PoinTr) · [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) | 分别代表预测残缺点云和从图像生成物体资产的扩展方向。实景展示以实拍背面为证据；生成道具可作为独立模式。 |

## 近年工作与适用范围

Kerbl 等人的 3DGS（SIGGRAPH 2023）用带颜色、形状和不透明度的三维高斯优化多视图外观，支持实时合成新视角。之后的工作分别改进相机注册、云端优化、网页传输、渲染帧率或表面几何。应按现场测到的瓶颈选择升级。 [3DGS 原论文和项目页](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/)

| 要解决的问题 | 近期工作与项目取舍 |
| --- | --- |
| 网页首屏和移动端浏览 | PlayCanvas SOG 将已训练的 PLY 转为较小的网页资产。桌面场景先对照同一份高斯的 PLY 和 SOG。场景扩大后可用 2026 年的 Streamed SOG 或 Spark 2.0，优先下载当前视野的低细节块。Speedy-Splat（CVPR 2025）从光栅化和剪枝改进渲染速度，其论文倍数基于作者的实现和数据。Mobile-GS（ICLR 2026）在手机 GPU 上验证渲染，后续 Flux-GS 提供移动端渲染实现。 [SOG](https://blog.playcanvas.com/playcanvas-open-sources-sog-format-for-gaussian-splatting/) · [Streamed SOG](https://blog.playcanvas.com/new-in-supersplat-webgpu-and-streaming-bring-huge-performance-wins/) · [Spark 2.0](https://worldlabs.ai/blog/spark-2.0) · [Speedy-Splat](https://speedysplat.github.io/) · [Mobile-GS](https://xiaobiaodu.github.io/mobile-gs-project/) · [Flux-GS](https://github.com/xiaobiaodu/Flux-GS) |
| 场景优化时间 | FastGS 和 Faster-GS（CVPR 2026）改进每个场景的 GS 优化，适合与 Brush 用同组已注册照片和留出视角对照。FastGS 的百秒结果对应论文配置。项目验收分别计相机注册、优化、导出和首次可拖动。 [FastGS](https://fastgs.github.io/) · [Faster-GS](https://arxiv.org/abs/2602.09999) |
| 单个物体与高质量表面 | 先用 COLMAP 注册整组照片，在 GS 场景内裁出玩具，检查边缘残留、贴纸和有照片覆盖的背面。如需要真实接触面或网格，用同批照片对照 COLMAP MVS 和 2DGS（SIGGRAPH 2024）。Sparse2DGS（CVPR 2025）用多视几何先验辅助稀疏视角下的表面重建。MeshSplatting（CVPR 2026）直接联合优化三角网格和外观。测几何时用已知尺寸做尺度对齐，再看长度误差、边缘和表面完整性。 [COLMAP](https://colmap.github.io/tutorial.html) · [2DGS](https://surfsplatting.github.io/) · [Sparse2DGS](https://github.com/Wuuu3511/Sparse2DGS) · [MeshSplatting](https://meshsplatting.github.io/) |
| 小范围到室内扫描 | 局部用 DA3-BASE 做单图和多图尺度未标定的彩色点云预览，并保留 COLMAP MVS 作离线几何对照。PlanarGS（NeurIPS 2025）适合对照室内无纹理墙面和地板。箱柜、走廊拐角或房间沿有重叠的轨迹采集，按观测范围输出资产。进一步扩大可借鉴 CityGaussian 的区域分块与细节层级，若需要连续视频建图，才单测 MASt3R-SLAM 等。需要有尺度的稠密几何时可走已标定 RGB-D 与 TSDF 融合。 [DA3](https://github.com/ByteDance-Seed/Depth-Anything-3) · [PlanarGS](https://planargs.github.io/) · [CityGaussian](https://dekuliutesla.github.io/citygs/) · [MASt3R-SLAM](https://github.com/rmurai0610/MASt3R-SLAM) · [Open3D TSDF](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html) |
| 真实全景 | 原地按方向取景可拼接单站全景。双鱼眼或全景相机可提供全景视频，移动到多个站点获得视差。Seam360GS（ICCV 2025）联合处理双鱼眼拼接畸变与标定。PFGS360（CVPR 2026）从未预先给位姿的真实全景视频联合估计位姿和高斯，作者实验用单张 RTX 4090。PanoGS（Web3D 2026）用少量实拍全景的深度先验和 TSDF 支撑重建，再输出网页资产。装上对应相机后才测试。 [Seam360GS](https://openaccess.thecvf.com/content/ICCV2025/html/Shin_Seam360GS_Seamless_360deg_Gaussian_Splatting_from_Real-World_Omnidirectional_Images_ICCV_2025_paper.html) · [PFGS360](https://arxiv.org/html/2603.23324v1#S4.SS1) · [PanoGS](https://albertojaspe.net/publications/2026-Web3D-PanoGS.html) |
| 全景生成 | PanSplat（CVPR 2025）从两张宽基线实拍全景前馈生成新视角，公开的 4K 模型推理说明要求至少 24 GB 显存，自采全景流程另有位姿估计。One2Scene（ICLR 2026）从单图生成全景锚点并扩展为可探索场景，适合仿真，预测画面应显示生成来源。 [PanSplat](https://github.com/chengzhag/PanSplat) · [One2Scene](https://proceedings.iclr.cc/paper_files/paper/2026/hash/9aaa0d7db14b9f0c2575a1761b1ab76e-Abstract-Conference.html) |

Cross3DGS（2026 年 11 月预印本）给出了手机端优化的参照。其手机流程借助 ARKit 或 ARCore 位姿先验，作者报告从视频抽帧到可浏览约 28–46 分钟。本项目先在本机优化场景，后续端云联调时再对照设备采集与服务器计算耗时。 [Cross3DGS](https://arxiv.org/html/2611.22240v1)

## 蛇端最值得做的视觉功能

**做目标导向补拍。** COVER（CVPR 2026）优先选择覆盖不足的几何。Auto3R（ECCV 2026）根据候选视角的不确定性决定下一拍，并在机械臂上实拍布玩具和电路板。蛇端可以先把展品周围分成 8–12 个可达方向，从 4–6 个有重叠的机位起步。网页优先提示还有重叠、又可能露出缺失表面的相邻机位或蛇头抬头角度。地面、桌边、超出关节转向能力的机位由操作者排除。相机移到新位置，停稳、拍摄、上传并返回清晰度和机位回执。用同一个目标、相同拍摄预算对照固定环路和补拍引导。记录关键视角注册率、背面贴纸可辨识、相同留出视角的目标区外观及从开拍到获得可用背面的时间。 [COVER](https://chengine.github.io/nbv_gym/) · [Auto3R](https://arxiv.org/html/2512.04528v1#S6)

ObjSplat（IEEE T-ASE 2026）把目标可见性和运动代价纳入规划，用表面高斯生成物体网格。其真机采用 RGB-D 机械臂与转台。项目可以借鉴按目标区域计算覆盖度，优先把补拍预算留给玩具本身和关键边缘。 [ObjSplat](https://li-yuetao.github.io/ObjSplat-page/)

**把蛇形运动和成像一起验证。** 先在蛇头模组上固定相机与舵机关节，核对结构遮挡、镜头高度、抬头俯仰角和清晰率。IMU 可以给停稳触发与姿态提示，相机位置由视觉注册估计。平地低机位穿行以侧面和背面仰拍为主，顶面用蛇头抬升后的俯角补拍，底面以实拍范围为准。若采用广角/鱼眼或行进中抓拍，再考虑支持非线性投影和滚动快门的 3DGUT。作为对比，文献中亦有采用四机载相机的[球形机器人全景视觉系统](https://doi.org/10.1017/S0263574724000043)。 [3DGUT](https://research.nvidia.com/labs/toronto-ai/3DGUT/)

## 本机基准与云试验规模估计

开发机用于复现，云 GPU 用于同批训练和扩大场景试验，自有域名用于资产分发。以下为试配估计，结果按云实例实测登记。 [云端试跑手册](../design/cloud-pilot.md)

| 位置 | 首轮配置与工作量估计 |
| --- | --- |
| 蛇形边缘端 | 一台单目 RGB，相机出 JPEG，板端控制多关节步态与蛇头抬头、停稳采集、缓存后上传、上传失败重传、有条件时做清晰度筛查。已有 STM32 精英版可先验证 FIFO 相机链路与舵机运动控制。如 VGA 室内样片注册或纹理不达标，再验证支持 JPEG 的 ESP32-S3（带 PSRAM）加 OV2640，或紧凑 Linux 板加 CSI 相机。实机联调前先测完整一圈的可用机位、供电和上传稳定性。 [正点原子资料中心](https://www.openedv.com/docs/build/html/index.html) · [Espressif 相机驱动](https://github.com/espressif/esp32-camera) |
| 云 GPU 试配 | 单任务、单张 RTX 4090 24 GB、8 vCPU、32 GB 内存、100 GB SSD 持久盘起步。DA3-BASE 加载预训练权重做推理，Brush 对每批场景照片优化高斯。先验证 CPU COLMAP、CUDA 推理和无桌面 Vulkan Brush。若镜像的 Vulkan 环境不可用，可测 CUDA 的 Splatfacto。NVIDIA 标准 4090 是 24 GB，5090 是 32 GB。云商标注 4090 32 GB 时，以实机规格和测试结果为准。5090 另外验证 Blackwell PyTorch 与 CUDA 扩展。 [4090](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4090/) · [5090](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5090/) · [PyTorch Blackwell 支持](https://pytorch.org/blog/pytorch-2-7/) · [Brush](https://github.com/ArthurBrussee/brush) |
| 桌面展品 | 24–40 张可用 JPEG，长边先用 1200–1600 px 试拍。按 0.15–0.45 MB/张估算全批约 3.6–18 MB。有效上行 5 Mb/s 对应纯传输约 6–29 秒，逐张上传可与换位重叠。点云 4–16 图分批预览，网页限点数。首轮云端估算目标为首次深度结果 5 秒内、8 张融合结果 10 秒内、冻结约 32 图到完整资产约 2–4 分钟，分别在实际网络和空闲队列条件下验证。 |
| 局部房间试验 | 从约 80–200 张带过渡视角的照片、单张 RTX 5090 32 GB、64 GB 内存和 200 GB SSD 试配，先按扫描区域拆作业。记录峰值显存、注册耗时和网页负载，再决定是否扩大。全景或单物体高精度追踪另按传感器和样点实测。 |
| 浏览器 | 点云先到，完整高斯就绪后加载压缩资产，保留原始高斯作画质对照。10 Mb/s 下先以首屏 4 MB 以内、冷加载首次可拖动 5 秒以内为测试目标，再记录同视角画质、帧间隔和手机兼容性。 |

估算以桌面静态展品起步，详见 [公开样例实测](../experiments/public-sample-benchmark.md)。公开样例在 RTX 4060 Laptop 8 GB 上已验证 32 张长边 1200 px 全注册约 22.55 秒，Brush 8,000 步加评估导出约 101.59 秒。相同公开序列的 900 px 轮次最大子模型注册 27 张。采集质量需要在实际蛇头结构、低机位距离和灯光下另测。云端计时分解为上行、排队、注册、推理或优化、导出、下载和网页首次可交互。

## 值得优先投入什么

先在公开照片上固定 DA3 点云与 COLMAP、Brush 的可重复基线，再让一个仿真展品的背面标记贯通「补拍原图、点云融合、3DGS 近看」。用同批素材和固定留出视角检查注册、遮挡和纹理。分别记录补拍后刷新、3DGS 重建、资产加载和浏览交互。 [公开样例实测](../experiments/public-sample-benchmark.md) · [本地实施指南](../design/implementation-guide.md)

竞赛汇报可聚焦仿真球换位采集、同一组照片生成的点云与 3DGS、公开与自有素材的来源。案例借鉴与获奖证据见 [4C 人工智能应用国奖作品调研](4c-award-review.md)。
