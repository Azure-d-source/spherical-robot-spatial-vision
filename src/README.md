# 源码布局

视觉阶段以独立命令行作业读写本地文件。各作业记录冻结的输入、工具参数及产物，供现有查看器和后续工作台使用。

| 目录 | 阶段与职责 |
| --- | --- |
| `workers/` | 本阶段建设。DA3 多视角点云与按需深度图，COLMAP、Brush 及高斯资产导出。 |
| `web/` | 工作台集成阶段。球体与展品摆放、球载相机、点云和高斯查看。 |
| `api/` | 工作台集成阶段确认服务接口。管理场景、布景版本、照片批次、作业和产物。 |
| `edge/` | 实体球接入阶段。设备拍照、缓存和传输。 |

文件交接与验收依据见 [系统架构](../docs/design/platform-architecture.md)和[实施指南](../docs/design/implementation-guide.md)。

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
