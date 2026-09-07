# Paper Reading Agent

面向计算机视觉论文的本地文献研读 Agent。项目目标是把 PDF 解析、双语阅读、结构化精读、证据定位和问答串成一条可验证的工作流。

> 当前状态：**S1 已验收；S2 已完成编码与本地真实浏览器验收，等待用户确认。** 当前具备论文导入解析、SQLite 持久化、基础 LLM 封装，以及 pdf.js 左右对照阅读、bbox overlay、Block 虚拟列表、双向同步滚动和双向 hover 高亮。真实翻译、Embedding、RAG、问答和报告尚未实现，也未进入 S3。

## 当前能力

- 统一 Parser 协议：`parse(pdf_path) -> ParseResult`，业务层不依赖 MinerU 原始 JSON。
- Windows 原生 CPU MinerU CLI pipeline；记录超时、exit code、stdout/stderr、OOM 诊断和原始错误。
- MinerU 结果正规化为连续 `order_idx` 的 Block；caption 没有可靠独立 bbox 时保留 diagnostics，不伪造 bbox。
- SQLite 普通表、sqlite-vec 自检与虚表幂等初始化；sqlite-vec 失败不会阻止基础功能启动。
- FastAPI 论文上传、状态查询、Block/Figure 查询、失败重试和按 Paper ID 获取 PDF。
- LiteLLM 基础设施：任务路由、60 秒超时、一次重试、错误透传、调用日志和 Pydantic 结构化校验；尚无业务 prompt。
- React 18 + TypeScript + Vite 阅读器，只开放 `side-by-side` 模式。
- pdf.js 多页按需渲染；每页以唯一 `RenderTask.promise` 为就绪依据，DPR 只用于 canvas backing store。
- bbox 按页面 CSS viewport 换算；右侧 `react-virtuoso` 按 `order_idx` 展示 165 个 Block。
- 左右同步以 `block.id` 为唯一身份，使用 35% 参考线、generation token、目标收敛与用户主动接管防止回环；hover 与 active 状态分离。
- Figure/Table 在 S2 仅显示 caption/文本或明确占位，不加载裁切图片，不渲染原始 `table_html`。

## 环境与安装

后端沿用已验证的 Conda 环境，不要重新安装 MinerU、torch、torchvision，也不要重新下载模型：

```powershell
conda activate paper-agent
pip install -r backend/requirements.txt
```

关键后端版本：Python 3.11.16、MinerU 3.4.5、SQLAlchemy 2.0.43、LiteLLM 1.77.7、sqlite-vec 0.1.6、pytest 8.4.1。MinerU 环境的完整已验证版本见 `requirements-mineru.txt`。

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

## 实测基线

使用 S0/S1 已存在的同一篇 12 页 ResNet PDF 和解析数据完成 S2 验收，没有重新下载 PDF 或重跑 MinerU。

| 指标 | 结果 |
|---|---:|
| Paper ID | `0e82764a-ae5a-4f8a-a212-e2896ee50702` |
| 应用 Block | 165 |
| Figure / Table | 12 / 15 |
| PDF 页数 | 12 |
| 后端测试 | 32 passed，2 条已接受第三方弃用告警 |
| 前端单元/组件测试 | 15 passed |
| 真实 Chrome E2E 稳定性复测 | 3/3 passed |
| npm audit | 0 vulnerabilities |
| production build | 通过 |

真实浏览器已检查标题、正文、公式、Figure、Table、首页/中间页/末页、未渲染页跳转、左右连续与快速滚动、hover 和用户中途接管。标题、正文、公式、Figure、Table 的 bbox 均能与同一 `block.id` 的右侧卡片成对高亮并落在对应 PDF 页面内；未观察到同步回环、明显抖动或未处理 console/page error。

## 阶段路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| S0 | 环境探测、MinerU 解析与 bbox 验证 | 已完成 |
| S1 | Parser、postprocess、SQLite、FastAPI、LLM 基础封装 | 已验收 |
| S2 | pdf.js 对照阅读器骨架与同步滚动 | 已实现并实测，待确认 |
| S3 | 翻译流水线、缓存、SSE 与阅读器交互 | 未开始 |
| S4 | Embedding 入库与图表卡片流水线 | 未开始 |
| S5 | RAG 问答、证据锚定、跳转与划选提问 | 未开始 |
| S6 | 八段精读、对话感知与三层改进方向 | 未开始 |
| S7 | 真实论文全流程回归验收与 prompt 打磨 | 未开始 |

详细产品范围以 [mvp-plan.md](mvp-plan.md) 为准，技术实现以 [tech-plan.md](tech-plan.md) 为准，开发纪律与阶段边界见 [CLAUDE.md](CLAUDE.md)，实测证据见 [DEVLOG.md](DEVLOG.md)。

## 目录

```text
.
├── backend/
│   ├── app/                    # FastAPI、数据库、Parser、LLM 与服务层
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
- S2 右栏展示英文 `content_md`，没有翻译；Figure/Table 仅为占位。
- 当前 production 主 JS 约 906 kB、PDF worker 约 1.27 MB，Vite 会给出大 chunk 告警；S2 未做代码分包与性能优化。
- 同步参考线是 MVP 的 35% 固定策略；尚未实现 viewport priority queue。

## 文档同步规则

后续每次阶段状态、功能、目录、依赖、运行命令、架构决策或阻塞发生变化时，都应在同一次修改中同步更新本 README；实测证据同步写入 `DEVLOG.md`，开发纪律或阶段边界变化同步写入 `CLAUDE.md`。
