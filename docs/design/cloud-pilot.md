# SplatForge · 灵境智绘云端试跑手册

2026 年 11 月 23 日 · 面向受限空间的仿生蛇形 3DGS 与多维空间视觉仿真工作台

开发机和云 GPU 并行验证。同批有序 RGB 文件能在两端使用同一组视觉作业，云端产物可回到同一个浏览器查看。先用真实公开照片完成云端计算，再将已确认的参数迁移到虚拟蛇形机器人和用户提供的一段真实视频。预制公开 SOG 单独验证网页浏览与域名交付。[执行方案](execution-plan.md) · [视觉工具运行说明](../../src/README.md) · [本机实测](../experiments/public-sample-benchmark.md)

## 1. 主机环境与验收门槛

| 项目 | 起始配置或验证条件 |
| --- | --- |
| 开发机 | 已用 RTX 4060 Laptop 8 GB 跑通 DA3、COLMAP、Brush 与 SOG。开发机保留离线查看入口及同批素材，复测与云端对照。 |
| 云机 | 先按单张 RTX 4090 24 GB、8 vCPU、32 GB 主机内存、100 GB 持久 SSD 估算。RTX 5090 32 GB 用于显存压力、租用条件或桌面到小室内增量验证。工作负载先串行，按峰值决定是否加卡。 |
| GPU 与工具链 | Brush v0.3.0、PyCOLMAP 4.2.1、SplatTransform 3.12.0 为对照版本。Linux 使用对应平台的 Brush 与独立显卡的无桌面 Vulkan。DA3 使用同一源码、权重修订和兼容 PyTorch/CUDA。5090 需实测 Blackwell 兼容性。 |
| 运行条件 | 队伍确认可用实例、预算、持久盘和访问方式后再启动云试跑。若套餐标示 RTX 4090 32 GB，以实例 `nvidia-smi` 的实测设备和显存登记。 |

24 GB 与 32 GB 是 NVIDIA 对相应标准卡的规格。云端时延和吞吐量由实际运行记录确定。[RTX 4090](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4090/) · [RTX 5090](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5090/) · [PyTorch Blackwell 支持](https://pytorch.org/blog/pytorch-2-7/) · [Brush v0.3.0](https://github.com/ArthurBrussee/brush/releases/tag/v0.3.0)

在已授权 Linux 云机的 Bash 中执行。将示例路径替换为实际的持久盘、仓库和工具路径。每台机器部署与命令相符的依赖。DA3 源码与权重修订从[公开实测](../experiments/public-sample-benchmark.md)取值，权重预下载到本端。两条命令使用独立 Python 环境时分别设置可执行文件。

```bash
set -euo pipefail
export SPLATFORGE_REPO="$PWD"
export SPLATFORGE_TRIAL=/mnt/splatforge/trials/dl3dv-first
export SPLATFORGE_RGB=/mnt/splatforge/inputs/dl3dv-rgb32
export SPLATFORGE_BRUSH=/mnt/splatforge/tools/brush_app
export SPLATFORGE_SOG_CLI=/mnt/splatforge/tools/node_modules/@playcanvas/splat-transform/bin/cli.mjs
export SPLATFORGE_DA3_MODEL=/mnt/splatforge/models/DA3-BASE
export SPLATFORGE_GS_PY=python
export SPLATFORGE_DA3_PY=python
export SPLATFORGE_SOG_GPU=0
mkdir -p "$SPLATFORGE_TRIAL/evidence"

git -C "$SPLATFORGE_REPO" rev-parse HEAD | tee "$SPLATFORGE_TRIAL/evidence/commit.txt"
cat /etc/os-release > "$SPLATFORGE_TRIAL/evidence/os-release.txt"
lscpu > "$SPLATFORGE_TRIAL/evidence/cpu.txt"
free -h > "$SPLATFORGE_TRIAL/evidence/ram.txt"
df -h "$SPLATFORGE_TRIAL" > "$SPLATFORGE_TRIAL/evidence/disk.txt"
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv \
  | tee "$SPLATFORGE_TRIAL/evidence/gpu.txt"
vulkaninfo --summary > "$SPLATFORGE_TRIAL/evidence/vulkan.txt"
"$SPLATFORGE_BRUSH" --version | tee "$SPLATFORGE_TRIAL/evidence/brush.txt"
"$SPLATFORGE_BRUSH" --help > "$SPLATFORGE_TRIAL/evidence/brush-options.txt"
node --version | tee "$SPLATFORGE_TRIAL/evidence/node.txt"
node "$SPLATFORGE_SOG_CLI" --list-gpus | tee "$SPLATFORGE_TRIAL/evidence/sog-gpus.txt"
"$SPLATFORGE_GS_PY" -m pip freeze > "$SPLATFORGE_TRIAL/evidence/gs-packages.txt"
"$SPLATFORGE_DA3_PY" -m pip freeze > "$SPLATFORGE_TRIAL/evidence/da3-packages.txt"
"$SPLATFORGE_GS_PY" -c 'import PIL, pycolmap; print(PIL.__version__, pycolmap.__version__)'
"$SPLATFORGE_DA3_PY" -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(), torch.cuda.get_device_capability(), torch.zeros(1, device="cuda").item())' \
  | tee "$SPLATFORGE_TRIAL/evidence/torch-cuda.txt"
```

确认 Vulkan 与 SplatTransform 列表识别 NVIDIA 设备，再选择 SOG GPU 编号。若云镜像只通过 CUDA 探针，先补齐 Vulkan 并明确记录当前失败阶段。若改用 CUDA 重建方案，将其列为另一路对照。镜像、锁定依赖、权重和工具包先落持久盘，查看器需要的静态依赖也提前备齐。

## 2. 真实公开 RGB 冒烟

准备公开基准的 32 张原图，保留原始、按采集顺序编号的文件名。把 `photo-order.txt` 和哈希表一起同步到开发机与云机。首轮 400 步用来证实两个阶段可计算，并检查真实 PLY/SOG 的格式、文件尺寸和浏览。画质见后续固定留出试验。[公开原图来源与复现记录](../experiments/public-sample-benchmark.md)

开发机已在 `data/cloud-pilot/dl3dv-first/` 冻结首轮输入。`rgb32/` 内是固定修订的 32 张原始 PNG，`evidence/` 内有照片顺序、SHA-256 和来源记录。另一个环境可以从相同修订准备，并按下列命令验证。

```bash
# 仅在制作首份输入包时生成一次，云机复用已冻结的两个清单。
(
  cd "$SPLATFORGE_RGB"
  find . -maxdepth 1 -type f -iname '*.png' -printf '%f\n' | LC_ALL=C sort \
    > "$SPLATFORGE_TRIAL/evidence/photo-order.txt"
  while IFS= read -r name; do sha256sum -- "$name"; done \
    < "$SPLATFORGE_TRIAL/evidence/photo-order.txt" > "$SPLATFORGE_TRIAL/evidence/input.sha256"
)

# 每台机器复跑时执行这里及后续命令。
(cd "$SPLATFORGE_RGB" && sha256sum -c "$SPLATFORGE_TRIAL/evidence/input.sha256")
mapfile -t photo_names < "$SPLATFORGE_TRIAL/evidence/photo-order.txt"
test "${#photo_names[@]}" -eq 32
photos=()
for name in "${photo_names[@]}"; do photos+=("$SPLATFORGE_RGB/$name"); done

printf '%s\n' 'long_edge=1200' 'brush_steps=400' 'max_splats=300000' \
  'camera=SIMPLE_RADIAL,shared' 'matching=CPU_SIFT,exhaustive' \
  'da3_process_res=504' 'da3_max_points=200000' > "$SPLATFORGE_TRIAL/evidence/smoke.params"
(
  cd "$SPLATFORGE_TRIAL/evidence"
  sha256sum photo-order.txt input.sha256 smoke.params > smoke-input-config.sha256
)
HF_HUB_OFFLINE=1 "$SPLATFORGE_DA3_PY" "$SPLATFORGE_REPO/src/workers/point_cloud.py" \
  --model-dir "$SPLATFORGE_DA3_MODEL" --device cuda --process-res 504 --max-points 200000 \
  --output-dir "$SPLATFORGE_TRIAL/point-4" "${photos[@]:0:4}" \
  2>&1 | tee "$SPLATFORGE_TRIAL/evidence/point-4.log"
HF_HUB_OFFLINE=1 "$SPLATFORGE_DA3_PY" "$SPLATFORGE_REPO/src/workers/point_cloud.py" \
  --model-dir "$SPLATFORGE_DA3_MODEL" --device cuda --process-res 504 --max-points 200000 \
  --output-dir "$SPLATFORGE_TRIAL/point-8" "${photos[@]:0:8}" \
  2>&1 | tee "$SPLATFORGE_TRIAL/evidence/point-8.log"
"$SPLATFORGE_GS_PY" "$SPLATFORGE_REPO/src/workers/reconstruct_gaussians.py" \
  --brush-exe "$SPLATFORGE_BRUSH" --splat-transform-cli "$SPLATFORGE_SOG_CLI" --sog-gpu "$SPLATFORGE_SOG_GPU" \
  --long-edge 1200 --steps 400 --max-splats 300000 --output-dir "$SPLATFORGE_TRIAL/gs-400" \
  "${photos[@]}" 2>&1 | tee "$SPLATFORGE_TRIAL/evidence/gs-400.log"
```

输出目录须是新目录。双端对照时分别记录机器及运行号。可另开窗口执行 `nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv --loop-ms=500` 并保存输出，记录空闲值和作业期间采样峰值。烟测成功需要点云可打开、32 张公开图在同一组件注册，PLY 和 SOG 均可加载且报告的高斯数量一致。异常时记录 `blocked` 或 `failed`、失败阶段和日志。

开发机已完成 32/32 注册和 400 步产物导出。该轮准备 11.71 秒、注册 49.80 秒、Brush 及 PLY 导出 11.33 秒、SOG 2.31 秒。云端的上述结果均待试跑。[本机作业基准](../experiments/public-sample-benchmark.md#本地视觉作业试跑)

## 3. 固定留出视角和参数调优

烟测 CLI 默认使用全部已注册照片，并保存准备后的 `images/` 与 `sparse/0`。以下比较采用同一套冻结的 COLMAP 结果，通过 Brush 的留出参数单独训练。先查 400 步输出的留出图文件名并保存清单，核对与注册表一致。随后各轮须保持留出图相同。用于背面可辨识验收的关键表面还要有已注册训练图提供覆盖。留出图参与配准并从高斯优化中留出，报告时保留这项口径。

```bash
test -f "$SPLATFORGE_TRIAL/gs-400/sparse/0/images.bin"
printf '%s\n' 'seed=42' 'long_edge=1200' 'max_splats=300000' \
  'eval_split_every=8' 'schedule=400,2000,8000' > "$SPLATFORGE_TRIAL/evidence/brush-eval.params"
(
  cd "$SPLATFORGE_TRIAL/gs-400"
  sha256sum sparse/0/cameras.bin sparse/0/images.bin sparse/0/points3D.bin images/*.png
) > "$SPLATFORGE_TRIAL/evidence/brush-eval-input.sha256"
sha256sum "$SPLATFORGE_TRIAL/evidence/brush-eval.params" > "$SPLATFORGE_TRIAL/evidence/brush-eval-config.sha256"

run_holdout_eval() {
  local steps="$1"
  local eval_dir="$SPLATFORGE_TRIAL/eval-$steps"
  mkdir "$eval_dir"
  /usr/bin/time -p "$SPLATFORGE_BRUSH" "$SPLATFORGE_TRIAL/gs-400" \
    --seed 42 --max-resolution 1200 --max-splats 300000 \
    --eval-split-every 8 --eval-every "$steps" --eval-save-to-disk \
    --total-steps "$steps" --export-every "$steps" --export-path "$eval_dir" \
    2>&1 | tee "$eval_dir/brush.log"
  test -s "$eval_dir/export_$steps.ply"
  find "$eval_dir" -type f -name '*.png' -printf '%f\n' | LC_ALL=C sort > "$eval_dir/holdout.txt"
  test "$(wc -l < "$eval_dir/holdout.txt")" -eq 4
  diff -u "$SPLATFORGE_TRIAL/eval-400/holdout.txt" "$eval_dir/holdout.txt"
}
run_holdout_eval 400
```

核对 400 步图像与留出列表后，在同一 Bash 会话执行后续轮次。

```bash
run_holdout_eval 2000
run_holdout_eval 8000
```

开发机和云机用相同的准备后图像和注册结果比较 GPU 优化时间。比较全链路时还要分别记录各端的准备和注册耗时。不同步数独立优化，种子相同也不保证跨 GPU 逐像素复现。

- 同机位对比量化结果可记录 PSNR、SSIM，写清真值、评测实现与图像尺寸。若工具未在无桌面运行日志输出指标，保留原图和导出渲染用于后续计算。每轮同时核对目标边缘、背面或角落的连续性。
- 用同一浏览器和视角检查 SOG 文件体积、到首帧、首次可操作与连续移动帧间隔。导出、首次下载与持续渲染分开计时。浏览看起来清楚的程度和几何精度需要各自的证据。
- 建议 400 步用于联调、2,000 步作为低成本预览候选、8,000 步作为完整画质候选。最终选择由固定留出视角及耗时决定。需要全部照片生成发布资产时，另跑最终全量版并沿用选定配置。

## 4. 虚拟蛇形机器人、自有视频与预制公开资产

| 路径 | 输入和首轮取样 | 检查结果 |
| --- | --- | --- |
| 虚拟蛇形机器人 | 蛇形本体移动、蛇头相机随低机位与抬头动作更新位姿，从实际渲染画面保存有序 RGB。先选少量邻近视角，再补至约 24–40 张有效图，包含正面、两个侧面、背面和过渡位。移动或增删展品后新建场景布局快照及 RGB 批次。 | 对照布局编号、首次点云和补拍点云，检查新增背面。真值相机位姿可用于诊断。重建默认读取 RGB。 |
| 用户提供的一段真实视频 | 先选静止小场景的连续短片段，如书桌和相邻角落。保持单镜头固定焦段，镜头平移或绕拍并保留相邻共视。预试 1 或 2 帧/秒，再按清晰度、重叠和覆盖挑出约 24–40 张。 | 抽帧和注册达标后才提高训练步数，记录缺景和补拍需求。真实视频及派生产物按用户明确提供的使用范围存放。 |
| 预制公开 SOG | 下载已有重建成果并登记来源、版本和许可。云端和本地独立加载。 | 记录视角移动、网页启动和资产传输。此路用于验证查看器与交付。 |
| 公开原始 RGB | 以第 2 节的公开 32 图为真实计算基准。以后可用同样规则选择公开室内序列。 | 记录从图像、注册、优化到 SOG 和浏览的完整证据。 |

视频抽帧示例。先由提供者明确文件及可用范围。将保留帧放到独立目录，冻结真实顺序和哈希，复用相同的 400 步入口。长边或默认抽帧率改变时建立新的参数记录。

```bash
export SPLATFORGE_VIDEO=/mnt/splatforge/inputs/scene.mp4
"$SPLATFORGE_GS_PY" "$SPLATFORGE_REPO/src/workers/extract_frames.py" "$SPLATFORGE_VIDEO" \
  --start 0 --duration 12 --fps 2 --max-frames 24 \
  --output-dir "$SPLATFORGE_TRIAL/video-candidates"
```

同一镜头单点转头所得全景适合固定视点浏览。需要漫游的场景 3DGS 应当有多位置、相互重叠的取景。双鱼眼、全景视频先核对投影和标定条件。扫描范围根据实际观察覆盖验收。

## 5. 自有域名分阶段交付

1. **本机打开。** 用已稳定的开发机打开由真实公开照片重建的 SOG 和一份预制公开 SOG。独立保留单文件演示以便离线验证。
2. **云静态试放。** 创建静态页输出目录，用选定的全量 PLY 生成拆分查看页。将 `SPLATFORGE_PUBLISH_PLY` 设为该 PLY 的实际路径后执行 `node "$SPLATFORGE_SOG_CLI" -g "$SPLATFORGE_SOG_GPU" --unbundled "$SPLATFORGE_PUBLISH_PLY" "$SPLATFORGE_TRIAL/site/index.html"`。用持久静态空间提供相对路径资源，HTML、JS、CSS 开启 gzip 或 Brotli，已压缩的 SOG 单独计大小。先发布已核准的公开演示。临时 GPU 作业进程继续由内部运行环境访问。
3. **域名预发布。** 队伍确认已有域名、可用子域、DNS 指向和 HTTPS 证书后再切换。打开浏览器实际查看一次冷载和热载，核对相对资源、HTTP 状态、压缩头和值得保留的结果版本。释放试用 GPU 实例后，静态演示仍应可独立加载。
4. **端云连通。** 先人工把同一文件批次送至云端运行和回收资产。接接口后单独验收一次从虚拟蛇形机器人采集、批次提交、作业完成到域名下查看结果。实体蛇形机器人接入随后用相同 RGB 与批次约定复测。

## 6. 每轮交付记录

| 证据 | 最少内容 |
| --- | --- |
| 运行记录 | 运行号、日期、来源和场景布局、机器或实例镜像、GPU 与驱动、仓库提交、工具和权重版本。 |
| 输入和配置 | 有序照片及 SHA-256，视频保留抽帧参数和入选列表，执行参数、参数哈希、留出清单与种子。 |
| 计算指标 | 注册率、组件数、关键机位、高斯数、显存采样峰值。分别列准备、注册、优化导出、压缩时间。 |
| 显示指标 | PLY 与 SOG 文件尺寸、加载条件、到首帧、首次可操作、连续移动帧间隔及截图。列清楚本地、模拟网络或真实域名。 |
| 状态 | `planned`、`running`、`passed`、`failed` 或 `blocked`。附清单、日志、产物路径、失败阶段和下一轮只改变的参数。 |

首轮云实例、真实网络和自有域名的性能填入实测后再写入项目完成情况。开发机的测量值作为对照。[架构](platform-architecture.md) · [实施指南](implementation-guide.md)
