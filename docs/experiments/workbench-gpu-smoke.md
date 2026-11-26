# P3 本机 GPU 工作台冒烟

2026 年 11 月 24 日 · Windows · RTX 4060 Laptop GPU 8 GB · NVIDIA 驱动 621.24

用同一套 FastAPI 和 React 工作台完成公开样例的上传、批次确认、提交、自动轮询和浏览器下载。三项作业均用真实执行器。每项从独立 Worker 进程起跑，所有作业使用同一个隔离数据目录。

## 环境与输入

- API、DA3 和 3DGS 运行在三个独立 Python 环境中，本次均基于 Python 3.12.15。DA3 使用 PyTorch 2.14.0+cu126、NumPy 1.26.4、源码 `3d835ec1a5802d64a8b8b15f817a1ab54809bfe4` 和 DA3-BASE 权重修订 `f4a6c9b3c95e41c82048423d3493a81ec3fa810e`。权重 SHA-256 为 `e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5`。
- 3DGS 环境使用 PyCOLMAP 4.2.1、Pillow 13.0.0、Brush 0.3.0 和 SplatTransform 3.12.0。Brush 二进制核对了发行版 SHA-256。SplatTransform 检出的 GPU 0 为 RTX 4060 Laptop。COLMAP 使用 CPU 特征和匹配，Brush 与 SOG 导出使用 GPU。
- 输入是 DA3 演示空间固定修订 `cfa6140634d538a5a3609178ae7a9fdc3e91a514` 的 32 张 DL3DV PNG。按文件名排序，逐图校验哈希。单图取 `frame_00029.png`，四图取 `00029 → 00038 → 00049 → 00054`，3DGS 使用全部 32 张。输入哈希清单以 UTF-8 保存，每行为“小写 SHA-256、两个空格、原始文件名”，使用 LF 并保留末尾换行。清单 SHA-256 为 `e381e651793996a0e99394fb611e514c5738287617e0e306c34377d5a99a91c5`。

[公开样例来源与视觉基准](public-sample-benchmark.md) · [固定权重](https://huggingface.co/depth-anything/DA3-BASE/tree/f4a6c9b3c95e41c82048423d3493a81ec3fa810e) · [Brush 0.3.0](https://github.com/ArthurBrussee/brush/releases/tag/v0.3.0)

## 启动与复现

在仓库根目录执行。替换示例路径，确保两个终端使用同一 `SPATIAL_DATA_DIR`。测试所用端口为 18463。

~~~powershell
# 终端 1，API 与工作台
$env:SPATIAL_DATA_DIR = 'D:\orbitforge-smoke\runtime'
npm --prefix src/web ci
npm --prefix src/web run build
.\.venv\Scripts\python.exe -m uvicorn src.api.main:create_app --factory --host 127.0.0.1 --port 18463
~~~

~~~powershell
# 终端 2，真实 Worker
$env:SPATIAL_DATA_DIR = 'D:\orbitforge-smoke\runtime'
$env:ORBIT_DA3_PY = 'D:\orbitforge-smoke\da3\Scripts\python.exe'
$env:ORBIT_DA3_MODEL = 'D:\orbitforge-smoke\DA3-BASE'
$env:ORBIT_GS_PY = 'D:\orbitforge-smoke\gs\Scripts\python.exe'
$env:ORBIT_BRUSH = 'D:\orbitforge-smoke\brush\brush_app.exe'
$env:ORBIT_SOG_CLI = 'D:\orbitforge-smoke\sog\node_modules\@playcanvas\splat-transform\bin\cli.mjs'
$env:PYTHONPATH = 'D:\orbitforge-smoke\Depth-Anything-3\src'
$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
.\.venv\Scripts\python.exe -m src.workers.runner --api-url http://127.0.0.1:18463
~~~

打开本机工作台，通过界面上传冻结样例。按采集顺序确认 1、4、32 张三个批次。单图与四图分别提交默认 `depth/v1` 和 `fusion/v1`，3DGS 选择「公开 32 图验收」即 `splat/public-32-v1`。保持页面可见并等待自动轮询展示产物。为复现下面的单项耗时，可先提交再启动只领取一项任务的 Worker，在命令末尾加 `--once`。

## 实测结果

端到端时间从工作台点击提交算到该批次的结果区第一次可见。包括领取、进程启动、计算、发布和最多约一轮网页轮询。表中不计首次上传和资产下载，各任务各测一次。文件大小均为字节。

| 作业 | 端到端 | 计算与产物 |
| --- | ---: | --- |
| `depth/v1`，1 图 | 14.160 秒 | 84,027 点。DA3 推理与导出 1.285 秒。GLB 1,345,652，JPG 90,525，清单 993。 |
| `fusion/v1`，4 图 | 11.097 秒 | 200,000 点。DA3 推理与导出 0.911 秒。GLB 3,201,232，四张 JPG 分别 91,004、92,399、89,314、85,667，清单 1,859。 |
| `splat/public-32-v1`，32 图、400 步 | 56.645 秒 | 注册 32/32，4,932 个高斯。准备 3.151 秒，COLMAP 38.053 秒，Brush 与 PLY 导出 11.210 秒，SOG 2.968 秒。PLY 1,165,501，SOG 88,736，清单 5,534。 |

Edge 自动轮询展示了三个批次的完成状态与下载链接。下载后核对 GLB 点数和清单、解码全部五张 JPEG、读取 PLY 高斯数并与 SOG 的 `meta.json` 核对。每个发布清单的有序输入 SHA-256 均与冻结样例一致。

停止 API 后用同一个数据目录重新启动。工作台刷新后可切换至三个原始批次，任务状态、32/32 注册覆盖和全部 12 个下载链接均可恢复。逐文件复取的 SHA-256 与重启前一致。进程树回收另在 Windows 上用测试子进程验证。
