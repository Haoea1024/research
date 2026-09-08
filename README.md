# Paper Reading Agent

面向计算机视觉论文的本地文献研读 Agent。项目目标是把 PDF 解析、双语阅读、结构化精读、证据定位和问答串成一条可验证的工作流。

> 当前状态：**S0、S1、S2 已验收并 push；S3 Translation 已完成最终 fake/mock 与真实验收。** Paratera `DeepSeek-V4-Pro-0813` 已完成 glossary 和 ResNet 第 1 页受控翻译：40 个术语持久化缓存，第一页为 13 done、4 skipped、0 failed，同范围重复提交产生 0 次新 LLM 调用。未进入第二页、全文、Flash A/B 或 S4。

## 当前能力

- 统一 Parser 协议：`parse(pdf_path) -> ParseResult`，业务层不依赖 MinerU 原始 JSON。
- Windows 原生 CPU MinerU CLI pipeline；记录超时、exit code、stdout/stderr、OOM 诊断和原始错误。
- MinerU 结果正规化为连续 `order_idx` 的 Block；caption 没有可靠独立 bbox 时保留 diagnostics，不伪造 bbox。
- SQLite 普通表、sqlite-vec 自检与虚表幂等初始化；sqlite-vec 失败不会阻止基础功能启动。
- FastAPI 论文上传、状态查询、Block/Figure 查询、失败重试和按 Paper ID 获取 PDF。
- LiteLLM 基础设施：任务路由、60 秒超时、一次重试、错误透传、调用日志和 Pydantic 结构化校验；S3 glossary/translate prompt 使用版本化 Jinja 模板。
- React 18 + TypeScript + Vite 阅读器，只开放 `side-by-side` 模式。
- pdf.js 多页按需渲染；每页以唯一 `RenderTask.promise` 为就绪依据，DPR 只用于 canvas backing store。
- bbox 按页面 CSS viewport 换算；右侧 `react-virtuoso` 按 `order_idx` 展示 165 个 Block。
- 左右同步以 `block.id` 为唯一身份，使用 35% 参考线、generation token、目标收敛与用户主动接管防止回环；hover 与 active 状态分离。
- Figure/Table 在 S2 仅显示 caption/文本或明确占位，不加载裁切图片，不渲染原始 `table_html`。
- 每篇论文结构化持久化 `source,target,version` glossary，可导出 UTF-8 BOM CSV；并发生成使用 per-paper async lock 双重检查。
- 翻译只处理 `is_translatable=1` Block，按局部连续块常规 batch 4，并携带前后各 1 Block、标题和命中术语子集。
- 单 worker `heapq + asyncio.Condition` 队列支持单块重译、当前 viewport、下一屏、scope 与全文优先级；重叠 Run 订阅同一 Block work item。
- SQLite `translations` 是 done/failed 权威缓存；SSE 提供 block/progress/error/finished 实时事件和断线重连快照。
- 中文字符比例阈值为 0.4；漂移时只重译该 Block 一次，仍失败则保存原始诊断并显示英文 fallback。
- 右栏按原 `block.id` 展示 pending/queued/translating/done/failed/skipped；done 优先中文，英文原文可展开，失败可单块重译，空白和元数据类 Block 明确跳过。

## 环境与安装

后端沿用已验证的 Conda 环境，不要重新安装 MinerU、torch、torchvision，也不要重新下载模型：

```powershell
conda activate paper-agent
pip install -r backend/requirements.txt
```

关键后端版本：Python 3.11.16、MinerU 3.4.5、SQLAlchemy 2.0.43、LiteLLM 1.77.7、sqlite-vec 0.1.6、sse-starlette 3.4.10、Jinja2 3.1.6、pytest 8.4.1。MinerU 环境的完整已验证版本见 `requirements-mineru.txt`。

前端使用 Node.js/npm，所有依赖均为精确版本，锁文件为 `frontend/package-lock.json`：

```powershell
cd frontend
npm ci
```

核心前端版本：React 18.3.1、Vite 8.2.2、TypeScript 5.9.3、pdfjs-dist 6.3.289、react-virtuoso 4.18.13、Zustand 5.0.15、KaTeX 0.18.7、Vitest 5.0.0、Playwright 1.63.0。Playwright 使用机器现有 Chrome，不下载浏览器。

如需配置 LLM，复制 `.env.example` 为 `.env`，在环境变量中放 API key，并在 `config.yaml` 配置 task/provider 路由。默认不会产生真实收费调用。

## 启动与测试

分别启动后端和前端：

```powershell
conda activate paper-agent
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm run dev
```

打开 `http://127.0.0.1:5173/?paperId=<paper-id>`。后端 API 文档位于 `http://127.0.0.1:8000/docs`。

验证命令：

```powershell
conda run -n paper-agent python -m pytest
cd frontend
npm test -- --run
npm run build
npm run test:e2e
```

E2E 需要后端、前端正在运行，并需要 S1 已解析的 ResNet Paper 数据；配置使用本机 Chrome channel，不下载 Playwright 浏览器。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/health` | 数据库、sqlite-vec、MinerU 和 LLM 配置状态 |
| `POST` | `/api/papers` | 保存 PDF、创建 `uploaded` Paper，并安排后台解析 |
| `GET` | `/api/papers` | 论文列表 |
| `GET` | `/api/papers/{paper_id}` | 论文详情和解析状态 |
| `GET` | `/api/papers/{paper_id}/pdf` | 通过 Paper ID 返回数据库记录对应的 PDF，不暴露绝对路径 |
| `GET` | `/api/papers/{paper_id}/blocks` | 按阅读顺序返回正规化 Block |
| `GET` | `/api/papers/{paper_id}/figures` | 返回 Figure/Table 和 caption diagnostics |
| `POST` | `/api/papers/{paper_id}/retry` | 仅允许 `parse_failed → parsing`；其他状态返回 409 |
| `GET` | `/api/papers/{paper_id}/glossary` | 获取结构化 glossary；`?format=csv` 导出 CSV |
| `GET` | `/api/papers/{paper_id}/translations` | 获取所有可翻译 Block 的权威/运行时状态快照 |
| `POST` | `/api/papers/{paper_id}/translate` | 创建全文或 `pages`/`block_ids` 范围 Run；pages 为 1-based |
| `GET` | `/api/papers/{paper_id}/translate/stream?run_id=...` | SSE 快照、事件回放和实时状态 |
| `POST` | `/api/papers/{paper_id}/viewport` | 仅接收 `visible_block_ids`，提升当前与下一屏任务优先级 |
| `POST` | `/api/blocks/{block_id}/retranslate` | 单块最高优先级重译；失败不破坏旧成功译文 |

## 实测基线

使用 S0/S1 已存在的同一篇 12 页 ResNet PDF 和解析数据完成 S2 验收，没有重新下载 PDF 或重跑 MinerU。

| 指标 | 结果 |
|---|---:|
| Paper ID | `0e82764a-ae5a-4f8a-a212-e2896ee50702` |
| 应用 Block | 165 |
| Figure / Table | 12 / 15 |
| PDF 页数 | 12 |
| 后端测试 | 60 passed，2 条已接受第三方弃用告警 |
| 前端单元/组件测试 | 25 passed |
| Chrome E2E | 真实 S2 Reader + fake S3 SSE 共 2 passed |
| npm audit | 0 vulnerabilities |
| production build | 通过 |

真实浏览器已检查标题、正文、公式、Figure、Table、首页/中间页/末页、未渲染页跳转、左右连续与快速滚动、hover 和用户中途接管。标题、正文、公式、Figure、Table 的 bbox 均能与同一 `block.id` 的右侧卡片成对高亮并落在对应 PDF 页面内；未观察到同步回环、明显抖动或未处理 console/page error。

## 阶段路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| S0 | 环境探测、MinerU 解析与 bbox 验证 | 已完成 |
| S1 | Parser、postprocess、SQLite、FastAPI、LLM 基础封装 | 已验收 |
| S2 | pdf.js 对照阅读器骨架与同步滚动 | 已验收并 push |
| S3 | 翻译流水线、缓存、SSE 与阅读器交互 | **COMPLETE** |
| S4 | Embedding 入库与图表卡片流水线 | 未开始 |
| S5 | RAG 问答、证据锚定、跳转与划选提问 | 未开始 |
| S6 | 八段精读、对话感知与三层改进方向 | 未开始 |
| S7 | 真实论文全流程回归验收与 prompt 打磨 | 未开始 |

详细产品范围以 [mvp-plan.md](mvp-plan.md) 为准，技术实现以 [tech-plan.md](tech-plan.md) 为准，开发纪律与阶段边界见 [CLAUDE.md](CLAUDE.md)，实测证据见 [DEVLOG.md](DEVLOG.md)。

## 目录

```text
.
├── backend/
│   ├── app/                    # FastAPI、数据库、Parser、LLM、翻译队列与服务层
│   ├── tests/                  # 后端单元与 API 测试
│   └── requirements.txt        # 固定 Python 依赖
├── frontend/
│   ├── src/api/                # S1 API client 与类型
│   ├── src/reader/             # pdf.js、bbox、BlockPane 与同步控制
│   ├── src/stores/             # 可序列化阅读器状态
│   ├── tests/                  # 真实 ResNet Chrome E2E
│   ├── package.json
│   └── package-lock.json
├── spike/                      # S0 探索、验收脚本和本地样本
├── config.yaml                 # 非密钥配置与 LLM 路由
├── .env.example                # 密钥变量示例
├── requirements-mineru.txt
├── pytest.ini
├── CLAUDE.md
├── DEVLOG.md
├── paper-reading-agent-design.md
├── mvp-plan.md
└── tech-plan.md
```

## 已知限制

- FastAPI `BackgroundTasks` 不是持久任务队列；重启时遗留 `parsing` 会显式失败，之后可 retry。
- sqlite-vec 已初始化，但尚未写入 embedding；Embedding/RAG 仍不可用。
- 当前只验证 Windows 原生 CPU MinerU pipeline。
- 20 个内嵌 caption 没有可靠独立 bbox，因此不生成独立 caption Block。
- `config.yaml` 已配置 Paratera OpenAI-compatible 路由；真实 key 仅从被 Git 忽略的 `.env` 中读取。当前不具备新的真实调用授权。
- S3 Run 和 SSE ring buffer 仅在进程内；服务重启后 done/failed 缓存仍在，但原 scope 不自动恢复，需重新提交且只处理未完成 Block。
- 当前只有单 worker，已发出的模型调用不取消；新 viewport 在当前调用结束后插队。
- Figure/Table 仍为 S2 占位，不发送给翻译模型。
- glossary 是 Run 级前置 gate：缺失时每 Paper 在 async lock 下至多生成一次，失败则所有 Block 保持 pending，并发送页面级可重试错误；不会逐 batch 重试。
- glossary 输入只包含标题、摘要、章节标题及本地抽取的专名/缩写/模型模块数据集候选；`glossary.max_source_chars=14000`，按候选边界确定性截断。ResNet 实测输入为 5,507 字符。
- glossary 使用 180 秒、0 transport retry；translate 使用 60 秒、1 次 transport retry。`llm_calls` 同时审计成功和脱敏后的 timeout/error。
- 修复后 ResNet glossary-only 真实验收成功：1 次业务调用/1 次 HTTP、0 retry，生成并持久化 40 个 version 1 术语；第一页及全库 Translation 行仍为 0。
- ResNet 第 1 页初始真实 translate baseline：17 个目标中 12 done、5 failed；5 个正常 batch、1 次 structured correction、3 次 language-drift retry、0 transport retry，共 9 个 HTTP attempts，估算费用 ¥0.570987。没有新 glossary 调用；该结果用于暴露并修复 pipeline 语义问题。
- 第一页 baseline 暴露的问题已修复：空白与 URL/email/HTML/文档元数据明确标为 `skipped`；batch 使用 per-block validation 和部分提交；failed 普通 submit 直接命中持久缓存，只有显式 retranslate 才重新调用；language ratio 排除 URL/email/HTML 噪声。
- LiteLLM 调用显式传入 `num_retries=0`，关闭其默认内部重试，只保留项目外层可审计的 task retry。此前约 163 秒调用与“60 秒 × LiteLLM 默认内部重试”一致；当前 fake 测试确认每次外层 attempt 都禁用内部 retry。
- 受控 Pro 修复验收仅显式重译 3 个有效历史 failed 正文 Block：3 次业务调用/3 次 HTTP、0 retry，估算费用 ¥0.058356。最终第一页 13 done、4 skipped、0 failed；普通 `pages=[1]` 复验新增 LLM 调用为 0。Chrome 双向同步、hover、快速滚动与用户接管通过，console error/page exception 均为 0。
- 当前 production 主 JS 约 906 kB、PDF worker 约 1.27 MB，Vite 会给出大 chunk 告警；S2 未做代码分包与性能优化。
- 同步参考线仍是 MVP 的 35% 固定策略。

## 文档同步规则

后续每次阶段状态、功能、目录、依赖、运行命令、架构决策或阻塞发生变化时，都应在同一次修改中同步更新本 README；实测证据同步写入 `DEVLOG.md`，开发纪律或阶段边界变化同步写入 `CLAUDE.md`。
