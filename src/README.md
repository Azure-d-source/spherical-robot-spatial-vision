# 源码目录

从仓库根目录按 [本地启动说明](../README.md#本地启动工作台) 运行，再打开工作台创建第一个场景。

| 模块 | 当前职责 |
| --- | --- |
| [api/](api/) | FastAPI 接收场景、照片、拍摄批次和计算任务，SQLite 保存元数据，磁盘保存原图。启动后可在 `/docs` 调试接口。 |
| [web/](web/) | React 工作台用于录入场景和机位、上传并选择原图、冻结批次和查看任务。 |
| `edge/`（规划中） | 球形机器人拍照、设备回执与上传重试。 |
| `workers/`（规划中） | 从队列领取作业，执行 DA3、COLMAP 或 Brush 并回传结果。 |

模块之间按[平台架构](../docs/design/platform-architecture.md)和[实施指南](../docs/design/implementation-guide.md)对接。

## 验证本地改动

在仓库根目录运行以下命令。后端测试使用临时数据库和照片目录，检查上传重试、场景隔离、批次顺序和作业去重。前端构建包含 TypeScript 类型检查。

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix src/web run build
```
