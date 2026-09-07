# DEVLOG — 文献研读 Agent 开发记录

## 2026-09-07 — S0：环境探测、MinerU smoke test 与 bbox viewer

### 范围

本轮只验证解析链路，不进入数据库、FastAPI、正式 React、翻译、RAG 或报告生成。样本节奏为 1→3→10，本轮仅使用 1 篇论文。

### 实测环境

| 项目 | 实测结果 | S0 结论 |
|---|---|---|
| OS | Windows 10 Pro 19045 | 原生 Windows 路线 |
| CPU / RAM | Intel i7-9700（8 核）/ 31.9 GB | CPU pipeline 可用 |
| GPU | RTX 2080 8 GB，驱动 595.95 | 本轮未使用 GPU |
| 基础 `python` | `C:\ProgramData\anaconda3\python.exe`，Python 3.13.5 | 不是 MinerU 运行环境 |
| `py` launcher | `C:\Python314\python.exe`，Python 3.14.7 | 不满足 MinerU 3.4.5 的 `<3.14` 元数据约束 |
| MinerU 环境 | Conda `paper-agent`，Python 3.11.16 | 本轮实际运行环境 |
| MinerU / torch / six | 3.4.5 / 2.14.0 / 1.17.0 | 实机 `pip show` 验证 |
| Docker | Desktop 29.7.2 已安装，探测时 daemon 未运行 | 本轮不用 Docker |
| WSL2 / Hyper-V | 未发现可用发行版/相关服务 | GPU 容器路线后置 |

MinerU 3.4.5 的 PyPI metadata 声明 Python `>=3.10,<3.14`。本文不再把未实测的 Windows/ray 兼容性或性能宣传当成已验证事实。

### 已发生的安装与下载

早期自动化会话在收到暂停前已经把任务放入后台，因此实际发生了以下用户级变更：

- 创建 Conda 环境 `%USERPROFILE%\.conda\envs\paper-agent`。
- 安装 `mineru[pipeline]==3.4.5` 及依赖；首次缺少 `six` 后补装 1.17.0。
- Hugging Face 模型下载因 `ChunkedEncodingError` 中断，随后从 ModelScope 下载 pipeline 模型。
- 模型位于 `%USERPROFILE%\.cache\modelscope\models\OpenDataLab--PDF-Extract-Kit-1.0\snapshots\master`。
- MinerU 配置写入 `%USERPROFILE%\mineru.json`。

这些环境和模型按用户决定保留；后续不重复下载。项目内 `.venv` 未用于最终解析。

### MinerU smoke test

- 论文：*Deep Residual Learning for Image Recognition*，arXiv:1512.03385，CVPR 2016。
- 本地 PDF：`spike/papers/resnet_1512.03385.pdf`，819,383 bytes，PDF 1.5。
- SHA-256：`1e0651b6810ecba34a3dbc5b5b0209226f889004607c1f203540a48d64e5a93a`。
- 命令：`mineru -p spike/papers/resnet_1512.03385.pdf -o spike/out -b pipeline`（在 Conda `paper-agent` 环境中运行）。
- 结果：12/12 页完成，输出在 `spike/out/resnet_1512.03385/auto/`；包含 Markdown、v1/v2 content list、middle/model JSON、layout/span/origin PDF 和 29 张裁剪图。
- 初次 Hugging Face 下载失败记录在 `.mineru_run.log`；切换已缓存的 ModelScope 模型后成功。日志和生成物不提交 Git。

### 实测 v1 content list

- 顶层为扁平列表，共 177 个块；没有显式 `order_idx`，列表下标作为阅读顺序。
- 页码 `page_idx` 单调不减；所有块具有 `type`、`page_idx` 和四坐标 `bbox`。
- 类型分布：text 128、table 15、chart 9、page_footnote 6、page_number 12、image 3、equation 2、list 1、aside_text 1。
- bbox 是相对页面的 0–1000 坐标；这是本样本输出的实测结构，不外推为所有 MinerU 版本的永久契约。

### bbox viewer 与自动验收

- `spike/bbox_viewer/generate_viewer.py` 生成静态 HTML 和逐页 PNG。
- Viewer 支持 12 页导航、类型过滤、bbox、列表下标 `order_idx`、figure/chart/table 与 caption 展示；已在 Chrome 本地打开验证。
- `spike/parse_bench.py` 对真实 content list 校验顶层结构、页码顺序、bbox、类型、figure/table/caption，并输出 JSON 摘要；失败返回非零退出码。
- `spike/qwen_compare.py` 是后置接口占位：缺少 key 或实现时明确返回 `BLOCKED`，不发起网络请求。

### Git 内容策略

提交需求文档、工作约定、验收脚本、viewer 生成器与复现说明。以下内容仅保留本机：虚拟环境、日志、模型权重、论文 PDF、MinerU 输出、viewer 生成的 HTML/页面 PNG。

### 阶段结论与阻塞

- S0 的单篇 MinerU 解析、结构验收和 bbox 可视化已完成。
- sqlite-vec 在 S0 仅保留为后续环境探测项，没有业务层或数据库实现。
- Qwen3-VL 对比因没有已批准的 API key 和实现范围而 blocked。
- GPU/vllm 路线需要 WSL2/Docker/显存方面的架构决策，当前不影响 CPU pipeline。
- 未经用户确认不得进入 S1。

## 2026-09-07 — 项目入口文档

- 新增根目录 `README.md`，汇总项目定位、S0 实测结果、S0→S7 路线、复现命令、目录结构和当前阻塞项。
- 将 README 同步列为工程纪律：阶段、功能、目录、依赖、命令、架构决策或阻塞变化时，必须在同一次提交中更新 README。
