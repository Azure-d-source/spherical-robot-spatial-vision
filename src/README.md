# 源码目录

当前保留模块入口约定。首版应用代码随原型转入联调后纳入此目录。

| 计划目录 | 负责内容 |
| --- | --- |
| `edge/` | 球形机器人拍照、设备状态、上传重试 |
| `api/` | 场景、目标、照片、批次、任务和产物接口 |
| `workers/` | DA3 深度和点云、COLMAP 注册和 Brush 3DGS |
| `web/` | 网页工作台、虚拟相机、点云和高斯查看器 |

模块之间按[平台架构](../docs/design/platform-architecture.md)和[实施指南](../docs/design/implementation-guide.md)对接。
