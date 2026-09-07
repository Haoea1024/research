# CLAUDE.md — 工作约定（任何会话开始先读这里）

## 0. 必读三份文档（顺序固定，先于一切动作）

1. `paper-reading-agent-design.md` — 产品与架构设计
2. `mvp-plan.md` — 初步阶段（MVP）范围与验收
3. `tech-plan.md` — 具体技术实施方案（**§3 schema 为准**）

读完三份、并核对本文件「当前阶段状态」之后，才能动手写代码。

## 1. 阶段纪律（硬约束）

- **严格按 S0 → S7 顺序推进**（见 mvp-plan §三）。当前阶段见本文件 §5。
- **未经用户明确确认，禁止进入下一阶段**，也不得提前做下一阶段的工作。
- **不得更换技术栈**：MinerU / FastAPI / SQLite / React+pdf.js / LiteLLM / bge-m3 等选型已定，换任意一项都需用户显式批准。
- **不得做 MVP 范围外的功能**（组会工作台、BM25/rerank、意图判别、联网搜索、Zotero 等一律推迟；见 mvp-plan §二）。
- **禁止静默吞错**：任何 LLM 结构化输出校验失败、解析失败、翻译漂移、依赖加载失败都必须显式落 `status/error` 字段或日志，绝不悄悄丢弃或假装成功。
- **阶段完成前必须实跑验证**：每个阶段的验收项（mvp-plan §七对应条目）必须用真实数据跑出可复现的证据（命令 + 输出 + 截图/日志），不能只写代码说"应该能跑"。

## 2. 关键架构决策（不要推翻）

- **不做"重建译文 PDF"**：左侧 pdf.js 原样渲染 + 右侧 HTML 译文流。绕开 pdf2zh/BabelDOC 写回 PDF 的整类坑。
- **锚点走"结构化字段 + 受限候选集 + 严格校验"**，禁止"LLM 复述原文再模糊匹配"（kotaemon 路线）与答案内联标记（ragflow 路线）。
- **LLM 排序一律 pairwise / checklist，禁止直接打 1-10 分**。
- **业务代码不写模型名**，全部走 `llm.call(task, ...)` 路由表（config.yaml）。
- **tech-plan §3 的 SQLite schema 是权威**，字段以此为准。

## 3. S0 范围裁决（本轮生效，不可越界）

- **S0 只做**：环境探测、确定 MinerU 部署形态、选 1 篇公开 CV 论文、跑通 MinerU 解析并落盘、跑通独立 bbox viewer（page / bbox / block type / order_idx / figure / table / caption 可人工查看）。
- **S0 不做**：数据库（含 sqlite-vec 业务层）、FastAPI 产品代码、正式 React、翻译、RAG、八段精读、三层改进、10 篇 corpus、GROBID/marker/Qdrant/任务队列。sqlite-vec 仅环境探测。
- **样本节奏 1→3→10，本轮只 1 篇**；论文以计算机视觉为主，选公开典型 CCF-A CV 论文。
- **Qwen3-VL 是后置留底**：缺 key 只留 `spike/qwen_compare.py` 接口，DEVLOG 标 blocked。
- **禁止安装软件或改系统配置**（WSL2/Docker 后端/驱动/CUDA toolkit/Windows 功能等系统级变更）。普通包冲突/路径/命令/小 bug 自行修；确需用户手动安装、管理员权限、重启、API key 或架构决策时，**暂停并汇报**。
- 第三方 MinerU 的版本/镜像/API/Swagger 以当前官方资料与实机为准，差异记入 DEVLOG。

## 4. 工程纪律

- 每个关键步骤更新 `DEVLOG.md`（时间戳 + 做了什么 + 命令 + 验证 + 阻塞）。
- bbox viewer 放 `spike/bbox_viewer/`；解析验收断言脚本放 `spike/parse_bench.py`。
- 不提交密钥、不把 `.env` 入 git；模型权重/大文件不入库。

## 5. 当前阶段状态

- **阶段**：S0 已完成，等待用户确认后才能进入 S1。
- **实测部署形态**：原生 Windows CPU `pipeline` 后端；运行环境为 Conda `paper-agent`（Python 3.11.16，MinerU 3.4.5）。基础 `python` 命令是 Anaconda Python 3.13.5，`py` launcher 默认是 Python 3.14.7，二者都不是本次 MinerU 的运行环境。
- **S0 证据**：ResNet（CVPR 2016）12 页解析为 177 个块；`spike/parse_bench.py` 和 `spike/bbox_viewer/` 已验收。生成物仅保留本机并由 `.gitignore` 排除。
- **后置阻塞**：GPU/vllm 需要 WSL2/Docker/显存路线决策；Qwen3-VL 仅保留无网络调用的 `spike/qwen_compare.py` stub。
