# Paper Reading Agent

面向计算机视觉论文的本地文献研读 Agent。项目目标是把 PDF 解析、双语阅读、结构化精读、证据定位和问答串成一条可验证的工作流。

> 当前状态：**S0 已完成，尚未进入 S1。** 目前仓库提供 MinerU 解析验证、自动验收脚本和 bbox 可视化工具，还不是可用的完整产品。

## 当前进展

### S0：解析验证 ✅

已用 CVPR 2016 论文 *Deep Residual Learning for Image Recognition* 完成真实 smoke test：

- MinerU 3.4.5 原生 Windows CPU `pipeline` 解析成功；
- 12 页 PDF 得到 177 个有序内容块；
- 包含 3 个 image、9 个 chart、15 个 table 和 20 个带 caption 的块；
- `parse_bench.py` 可检查页码顺序、bbox、类型、figure/table/caption，并在失败时返回非零退出码；
- bbox viewer 可逐页查看原始页面、内容框、块类型、阅读顺序、图表和 caption；
- Qwen3-VL 只保留后置接口，占位脚本不会发起 API 请求。

解析生成物、论文 PDF、模型权重、日志和虚拟环境只保留在本机，不提交 Git。

## 规划阶段

项目严格按以下顺序推进，未经确认不提前进入下一阶段：

| 阶段 | 内容 | 状态 |
|---|---|---|
| S0 | 环境探测、MinerU 解析与 bbox 验证 | 已完成 |
| S1 | 解析流水线：Parser 接口与 MinerU 实现 | 未开始 |
| S2 | 对照阅读器骨架：pdf.js、英文块流与同步滚动 | 未开始 |
| S3 | 翻译流水线、缓存、SSE 与阅读器交互 | 未开始 |
| S4 | Embedding 入库与图表卡片流水线 | 未开始 |
| S5 | RAG 问答、证据锚定、跳转与划选提问 | 未开始 |
| S6 | 八段精读、对话感知与三层改进方向 | 未开始 |
| S7 | 真实论文全流程回归验收与 prompt 打磨 | 未开始 |

详细范围与验收条件以 [mvp-plan.md](mvp-plan.md) 为准，具体实现方案以 [tech-plan.md](tech-plan.md) 为准。

## S0 本地复现

### 环境

本次验证使用：

- Windows 10；
- Conda 环境 `paper-agent`，Python 3.11.16；
- MinerU 3.4.5；
- CPU `pipeline` 后端。

已有本地环境可直接激活：

```powershell
conda activate paper-agent
```

### 1. 运行 MinerU

把待测 PDF 放入 `spike/papers/`，然后执行：

```powershell
mineru -p spike/papers/resnet_1512.03385.pdf -o spike/out -b pipeline
```

### 2. 验证解析结果

```powershell
python spike/parse_bench.py `
  spike/out/resnet_1512.03385/auto/resnet_1512.03385_content_list.json
```

通过时输出 JSON 摘要并返回退出码 `0`；结构、bbox、页码顺序或必要内容不合格时返回 `1`。

### 3. 生成 bbox viewer

```powershell
python spike/bbox_viewer/generate_viewer.py `
  --pdf spike/papers/resnet_1512.03385.pdf `
  --content spike/out/resnet_1512.03385/auto/resnet_1512.03385_content_list.json `
  --out spike/bbox_viewer
```

生成后用浏览器打开 `spike/bbox_viewer/index.html`。该页面是纯静态调试工具，不需要启动 Web 服务。

## 仓库结构

```text
.
├── README.md
├── CLAUDE.md                       # 阶段纪律与 Agent 工作约定
├── DEVLOG.md                       # 实机环境、命令、验证和阻塞记录
├── paper-reading-agent-design.md   # 产品与架构设计
├── mvp-plan.md                     # MVP 范围、顺序与验收标准
├── tech-plan.md                    # 具体技术实施方案
└── spike/
    ├── README.md                   # S0 复现细节
    ├── parse_bench.py              # MinerU content list 自动验收
    ├── qwen_compare.py             # Qwen3-VL 后置接口占位
    └── bbox_viewer/
        └── generate_viewer.py      # bbox 静态查看器生成器
```

## 关键技术约束

- `tech-plan.md` §3 的 SQLite schema 是后续实现的权威定义；
- 不重建译文 PDF，计划采用左侧 pdf.js 原文、右侧 HTML 译文流；
- 锚点采用结构化字段、受限候选集和严格校验；
- LLM 调用统一通过任务路由，业务代码不硬编码模型名；
- 失败必须显式记录和展示，不允许静默吞错；
- S0 不实现数据库、FastAPI 产品代码、正式 React、翻译或 RAG。

## 当前阻塞与后置事项

- GPU/vllm 路线需要后续决定 WSL2、Docker 和显存方案；
- Qwen3-VL 比较需要明确的实现阶段与经批准的 API key；
- sqlite-vec 在 S0 尚未接入业务层；
- 进入 S1 前需要用户明确确认。

## 文档同步规则

README 是项目当前状态的入口文档。以后每次更新项目时，如果发生下列任一变化，必须在同一次提交中同步更新本文件：

- 阶段开始、完成或验收状态变化；
- 新增、删除或重命名主要功能和目录；
- 安装步骤、启动命令、配置项或依赖版本变化；
- 技术架构、关键决策、限制或阻塞项变化；
- 可复现样本和实测结果变化。

同时更新 [DEVLOG.md](DEVLOG.md) 记录实测证据；若涉及开发纪律或阶段边界，再同步更新 [CLAUDE.md](CLAUDE.md)。

## 需求与设计文档

- [paper-reading-agent-design.md](paper-reading-agent-design.md)：产品目标和完整架构；
- [mvp-plan.md](mvp-plan.md)：MVP 边界、阶段顺序与验收；
- [tech-plan.md](tech-plan.md)：数据结构和技术实施方案；
- [DEVLOG.md](DEVLOG.md)：实机验证、差异与决策记录。
