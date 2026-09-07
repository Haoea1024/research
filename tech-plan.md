# 文献研读 Agent — MVP 技术实施方案

> 对应范围见 [mvp-plan.md](mvp-plan.md)，产品设计见 [paper-reading-agent-design.md](paper-reading-agent-design.md)。本文回答"具体怎么写代码"。

## 1. 技术栈总览

| 层 | 选型 | 版本策略 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI + uvicorn | requirements.txt 全量锁版本 |
| 数据库 | SQLite（WAL 模式）+ sqlite-vec 扩展（≥0.1.6，需 partition key 特性） | 单文件 `data/app.db`；Windows wheel 在 setup 脚本锁定验证过的版本（该扩展在 Windows 有 DLL 加载失败实录，自检失败时给出 VC++ Redistributable 诊断） |
| ORM/校验 | SQLAlchemy 2.0 + Pydantic v2 | 结构化输出校验也统一用 Pydantic |
| LLM 接入 | LiteLLM（Router 模式） | 任务→模型路由读 `config.yaml` |
| PDF 解析 | MinerU 3.x（独立服务化，见 §5） | 版本锁在 Docker 镜像 tag（mineru/torch/vllm 在容器内，vllm 无法原生跑 Windows）；后端 requirements 只锁 HTTP client 依赖；**环境前提：宿主机 NVIDIA 驱动需支持 CUDA 12.8+，spike 第一步先查驱动版本** |
| Embedding | bge-m3（FlagEmbedding，**默认 CPU**——MinerU 的 vllm 预分配独占显存，不与其抢 GPU）；可切 Voyage API | 路由表中作为一个 provider；入库 embed 显式 `max_length=512` + 批量编码（默认 8192 会把 CPU 耗时放大一个量级），嫌慢可换 ONNX int8 |
| 前端 | React 18 + TypeScript + Vite + Tailwind + zustand | |
| PDF 渲染 | pdfjs-dist（canvas 渲染 + 自绘 bbox overlay 层） | |
| 公式渲染 | KaTeX（右侧译文流中的 LaTeX 块） | |
| 流式通信 | SSE（sse-starlette；前端 fetch + ReadableStream） | |
| 长任务 | FastAPI BackgroundTasks + 进程内优先级队列 | 无 celery/redis |

## 2. 仓库结构（monorepo）

```
paper-agent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                 # FastAPI 装配、CORS、启动自检（key/base_url 校验、sqlite-vec 加载）
│  │  ├─ config.py               # config.yaml + .env 加载，Pydantic Settings
│  │  ├─ db.py                   # engine、WAL、sqlite-vec 注册、建表迁移
│  │  ├─ models.py               # SQLAlchemy 表模型
│  │  ├─ llm/
│  │  │  ├─ client.py            # llm.call(task, ...) 统一入口（路由/重试/超时/成本记录/缓存探测）
│  │  │  ├─ structured.py        # call_structured(task, schema)：Pydantic 校验→失败带错误重试1次→降级
│  │  │  ├─ schemas.py           # AnchoredAnswer/Glossary/FigureCard/ProposalCard/CheckVerdict...
│  │  │  └─ prompts/             # 每任务一个 .md 模板（jinja2），版本入 git
│  │  ├─ parsing/
│  │  │  ├─ base.py              # Parser Protocol: parse(pdf_path) -> ParseResult(list[Block], figures)
│  │  │  ├─ mineru_client.py     # 唯一实现：HTTP 调 MinerU 服务（或 CLI subprocess 兜底）
│  │  │  └─ postprocess.py       # discarded 过滤、公式字体/字符正则兜底、bbox 归一化、阅读顺序编号
│  │  ├─ translate/
│  │  │  ├─ glossary.py          # 术语表生成/存取/CSV 导出
│  │  │  └─ pipeline.py          # 优先级队列、分块翻译、语言漂移校验、SSE 事件源
│  │  ├─ figures/cards.py        # 图表卡片：视觉描述 + 表格 HTML 转录
│  │  ├─ rag/
│  │  │  ├─ index.py             # 分块 embedding 入库、两路检索（文本块/图表卡片）
│  │  │  └─ qa.py                # 候选集组装、受限锚点问答、可信度信号、拒答
│  │  ├─ report/
│  │  │  ├─ sections.py          # 八段懒生成、段间上下文链、对话感知
│  │  │  └─ improve.py           # 三层改进方向 + pairwise 选优 + 具体性检查器
│  │  └─ api/                    # papers.py / reader.py / chat.py / report.py 路由
│  ├─ spike/
│  │  ├─ parse_bench.py          # S0：断言式解析验收（可回归）
│  │  └─ assertions/*.yaml       # 每篇论文的断言（块序/图注配对……）
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/
│  └─ src/
│     ├─ reader/                 # PdfPane(pdf.js+overlay) / TransPane(块流) / SyncController
│     ├─ chat/                   # 问答侧栏、锚点渲染、可信度警示
│     ├─ report/                 # 八段手风琴、提案卡、故事线
│     ├─ stores/                 # zustand: paperStore/readerStore/chatStore
│     └─ api/                    # 类型化 client + SSE 封装
├─ config.yaml  /  .env.example
├─ docker/mineru/                # MinerU 服务 Dockerfile + compose（WSL2 GPU）
└─ scripts/setup.py              # 权重下载（带镜像源）、sqlite-vec 安装、环境自检
```

## 3. 数据库 Schema（SQLite）

```sql
CREATE TABLE papers (
  id TEXT PRIMARY KEY,            -- uuid
  title TEXT, authors TEXT, year INTEGER,
  pdf_path TEXT NOT NULL,
  status TEXT NOT NULL,           -- uploaded|parsing|parsed|parse_failed
  parser TEXT, parser_version TEXT,
  error TEXT,                     -- 失败时的原始错误
  created_at TEXT
);
CREATE TABLE blocks (
  id TEXT PRIMARY KEY,            -- {paper_id}:{order_idx}
  paper_id TEXT NOT NULL,
  order_idx INTEGER NOT NULL,     -- 阅读顺序
  page INTEGER NOT NULL,
  bbox TEXT NOT NULL,             -- json [x0,y0,x1,y1] 归一化 0-1000
  type TEXT NOT NULL,             -- text|title|formula|figure|table|caption
  content_md TEXT,                -- 文本/markdown；公式为 latex
  confidence REAL,                -- 可空
  is_translatable INTEGER NOT NULL DEFAULT 1  -- 公式兜底/图表块置 0
);
CREATE TABLE translations (
  block_id TEXT PRIMARY KEY,
  zh_text TEXT NOT NULL,
  glossary_version INTEGER NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,           -- done|failed
  updated_at TEXT
);
CREATE TABLE glossary_terms (
  paper_id TEXT, source TEXT, target TEXT, version INTEGER,
  PRIMARY KEY (paper_id, source, version)
);
CREATE TABLE figures (
  id TEXT PRIMARY KEY,
  paper_id TEXT, block_id TEXT,   -- 对应 figure/table 块
  caption_block_id TEXT,
  image_path TEXT NOT NULL,
  vision_desc TEXT,               -- 图表卡片描述
  table_html TEXT,                -- 表格结构化转录（仅 table）
  model TEXT, status TEXT,        -- pending|done|failed
  error TEXT                      -- 失败原因，可单卡重试
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, paper_id TEXT,
  role TEXT, content TEXT,
  anchors TEXT,                   -- json [block_id...]
  confidence TEXT,                -- ok|low|refused
  created_at TEXT
);
CREATE TABLE report_sections (
  paper_id TEXT, section TEXT,    -- s1..s8
  content_md TEXT, anchors TEXT, summary TEXT,  -- summary 供段间上下文链
  dialog_aware INTEGER, model TEXT, status TEXT,
  PRIMARY KEY (paper_id, section)
);
CREATE TABLE proposal_cards (
  paper_id TEXT, idx INTEGER,     -- idx=0 固定存第一层"可改动点枚举"结果（kind=axes），idx>=1 为提案卡
  kind TEXT NOT NULL,             -- axes | card
  card_json TEXT,                 -- axes: 三轴枚举+批评修订全量；card: ProposalCard（含故事线、可行性、缺口清单）
  status TEXT, model TEXT, error TEXT,   -- 三层生成是最长 LLM 任务链，失败可见可重试
  PRIMARY KEY (paper_id, idx)
);
CREATE TABLE llm_calls (          -- 成本日志（§5.2 落点）
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task TEXT, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cache_read_tokens INTEGER,
  cost REAL, latency_ms INTEGER, created_at TEXT
);
-- 向量：sqlite-vec 虚表，embedding 维度 1024 (bge-m3)
-- paper_id 必须是 partition key：否则 KNN 作用于全库所有论文，多篇入库后
-- "top-8 再按前缀过滤"可能剩 0 条，命中率随论文数增长而劣化（需 sqlite-vec ≥0.1.6）
CREATE VIRTUAL TABLE vec_blocks  USING vec0(block_id TEXT PRIMARY KEY, paper_id TEXT partition key, embedding float[1024]);
CREATE VIRTUAL TABLE vec_figures USING vec0(figure_id TEXT PRIMARY KEY, paper_id TEXT partition key, embedding float[1024]);
-- embedding 模型戳放 meta 表，换模型整库重建
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);  -- embedding_model / schema_version ...
```

## 4. API 契约（REST + SSE）

```
POST /api/papers                     # multipart 上传 → {paper_id}；后台触发解析
GET  /api/papers                     # 列表（含状态）
GET  /api/papers/{id}                # 状态/元数据/错误
GET  /api/papers/{id}/blocks         # 全部块（阅读器初始化用）
GET  /api/papers/{id}/figures        # 图表卡片
GET  /api/papers/{id}/glossary?format=json|csv

POST /api/papers/{id}/translate      # body: {pages?: [..], block_ids?: [..]} 启动/补翻
GET  /api/papers/{id}/translate/stream           # SSE：翻译事件流
POST /api/papers/{id}/viewport       # body: {visible_block_ids} → 调整优先级队列
POST /api/blocks/{block_id}/retranslate

POST /api/papers/{id}/chat           # body: {question, selected_block_ids?} → SSE
GET  /api/papers/{id}/messages

POST /api/papers/{id}/report/{section}?dialog_aware=0|1   # 生成某段 → SSE
GET  /api/papers/{id}/report
POST /api/papers/{id}/proposals      # 三层改进方向（含 pairwise 与检查器）→ SSE 进度
GET  /api/papers/{id}/proposals      # 返回第一层可改动点(idx=0) + 全部提案卡
GET  /api/health                     # 启动自检结果（key/模型/解析服务连通性）
```

**SSE 事件约定**（翻译流为例）：
```
event: block        data: {"block_id":"...","zh_text":"...","status":"done"}
event: progress     data: {"done":37,"total":210}
event: error        data: {"block_id":"...","code":"LLM_TIMEOUT","message":"..."}
event: finished     data: {}
```
问答/报告流：`token`（增量文本）、`anchors`（末尾一次性下发校验后的锚点数组）、`confidence`、`error`、`finished`。锚点在服务端校验完再下发，前端不解析正文中的标记。

## 5. 关键模块实现

### 5.1 解析（parsing/）
- **部署形态**：MinerU 独立服务化，`docker/mineru` 用官方镜像 + `--profile api`（Windows 下经 WSL2 + GPU 直通运行），走 **3.0 官方异步 API**：`POST /tasks` 提交 → `GET /tasks/{id}` 轮询 → `GET /tasks/{id}/result` 取 `content_list.json` + 图片（不用同步 `/file_parse` 扛长连接；结果默认仅保留 24h，拿到立即落盘）；`GET /health` 接入启动自检。字段细节以服务 `/docs`（Swagger）实测为准，列入 spike 清单。客户端总超时 **8 分钟/篇**（给验收 1"上传后 10 分钟可读"留 2 分钟首屏翻译预算），docker compose 设 `mem_limit`。若无 GPU/WSL2，同一 Parser 接口切 MinerU pipeline 后端 CLI subprocess（速度慢、精度略降；捕获 OOM/崩溃并落 `parse_failed`）。**S0 spike 的第一件事就是在目标机器上确定部署形态（先查 NVIDIA 驱动 CUDA 版本）。**
- **孤儿状态恢复**：启动自检时把 `status='parsing'` 且无活跃任务的 paper 置为 `parse_failed`（可重试），避免进程崩溃后永远卡在解析中。
- **postprocess 流水**：① 丢 `discarded_blocks`；② bbox 归一化并与页尺寸绑定；③ 公式兜底：对 text 块跑字体名正则（`CM.*|.*Ital|MS.*` 等）与字符正则（运算符/希腊字母密度阈值），命中则 `is_translatable=0`；④ 生成 `order_idx` 与 block id；⑤ figure/table 块与最近 caption 块配对（MinerU 自带配对优先，缺失时按"同页、bbox 相邻、caption 型块"启发式补），配对结果进 spike 断言。
- **Parser Protocol**：`parse(pdf_path) -> ParseResult`；MinerU 是唯一实现，Qwen3-VL 降级只在 spike 脚本里比对，不进产品代码。

### 5.2 LLM 封装（llm/）
- `llm.call(task, messages, images=None, stream=False)`：读路由表→LiteLLM 调用→统一超时 60s→失败一次指数退避重试→记录 tokens/cost/cache 命中到 `llm_calls` 表。Anthropic 走 prompt caching：论文全文（blocks 拼接，带 block id 标注）作为带 `cache_control` 的前缀 system 块，qa/report 任务复用（LiteLLM 支持块级 cache_control 透传，对不支持的 provider 自动剥离——即天然满足能力探测降级）。注意 Anthropic 缓存 TTL 默认 5 分钟，问答间隔超过 5 分钟会重新计 cache write（1.25 倍价），成本估算按此口径。
- `call_structured(task, schema: type[BaseModel])`：要求 JSON 输出→`model_validate_json`→ValidationError 时把错误信息附回重试 1 次→仍失败抛 `StructuredOutputError`，调用方降级（如"未能锚定"标注），**绝不静默吞掉**。
- prompt 模板 jinja2 `.md` 文件，模板名=任务名，git 管理即版本管理。

### 5.3 翻译（translate/）
- 首轮：抽 title/abstract/标题块 + 高频专名 → `glossary` 任务产出术语表（结构化 `[{source,target}]`，入表，version=1）。
- 队列：`heapq` 优先级 = (0 if in_viewport else 1, order_idx)；`/viewport` 上报即时重排；单 worker 协程消费（避免并发打爆限速），每批 3-5 块携带术语表命中子集 + 前后各 1 块上下文。
- 落库前校验：中文字符占比 < 0.4 且原文非公式 → 自动重译一次；仍失败标 `failed`。
- 幂等：`translations` 表即缓存，重启后 `status != done` 的块重新入队。

### 5.4 图表卡片（figures/cards.py）
- 输入 = 裁切原图 + **图注块原文 + 图所在页的前后相邻 text 块**（防图注过短/图文不同页导致检索漏召回）；表格额外要求输出 HTML 结构化转录存 `table_html`。
- 每卡独立任务，失败落 `figures.status='failed'` + `error`，可单卡重试。

### 5.5 问答（rag/）
- 索引：解析完成后后台把 text 块（title+正文，过滤 <30 字符碎块）与图表卡片（desc+caption+table_html 文本化）各自 embed 入两张 vec 表（`max_length=512`，批量编码，KNN 查询带 `paper_id` 分区）。
- 查询流程：`embed(question)` → 两路各取 top-8 → 合并去重成**编号候选集**（含 block 摘要与 figure 卡片）→ 若命中 figure，附裁切原图 → `call_structured(qa, AnsweredWithAnchors)`，schema 中 `claims[].anchor_ids` 只允许候选集编号，服务端映射回 block_id 并丢弃非法值 → top1 相似度低于阈值时 `confidence=low` 并在 prompt 中强化拒答许可。qa prompt 固定附**术语表命中子集**（中文提问 ↔ 英文原文的术语对齐靠它）。
- 划选提问：`selected_block_ids` 直接作为候选集前排，不走检索；**选中块为 figure/table 时附裁切原图**。

### 5.6 精读与改进方向（report/）
- 每段一个 prompt 模板，输入 = 缓存全文前缀 + 相关图表卡片（④⑥）+ 已生成段的 `summary` 列表 + （可选）对话摘要。输出 schema：`{content_md, anchors, summary}`，锚点同样走受限候选集（该段检索 top-16 作候选）。**s6（实验与消融）模板内置"复现风险审查"固定 checklist：benchmark 选择恰当性 / 数据泄漏嫌疑 / 指标误用 / post-hoc 挑结果**——实现时不可省略。
- 三层改进方向：第一层（枚举→三角色 checklist 批评→修订，**结果存 `proposal_cards` idx=0/kind=axes**）→ 第二层提案卡（Pydantic：question/why_now/mvp_experiment/feasibility/info_gaps/risk_planB）→ 第三层每卡故事线生成 3 候选 → pairwise 两两比较（3 次 `compare` 调用）取胜者 → 具体性检查器（规则：须含 ≥1 数据集名 + ≥1 模块/指标名；再过 haiku checklist）不合格段落打回重生成（最多 1 轮）。

### 5.7 阅读器前端（frontend/reader/）
- PdfPane：pdfjs-dist 按页 canvas 自绘渲染 + 每页一个绝对定位 overlay div，块高亮画在 overlay（bbox 从 0-1000 归一化换算页实际尺寸）。**渲染就绪信号：自绘模式下没有 `pagerendered` 事件（它属于 pdf_viewer 组件的 EventBus），用 `page.render()` 返回的 `RenderTask.promise` 维护 per-page ready promise，跳转未渲染页时 await 后再画框**。低置信块（`blocks.confidence` 低于阈值）在 overlay 上加弱提示样式。
- TransPane：虚拟列表（react-virtuoso）渲染译文块，KaTeX 渲染公式块，figure 块内嵌 `<img>` + 翻译图注。readerStore 含 `viewMode` 枚举（`side-by-side | translation-only`），TransPane 按枚举分支渲染，MVP 只实现 side-by-side（枚举位为推迟的"纯译文全宽"留接口）。翻译/报告等产出若 `model` 字段与当前路由不一致，UI 角标提示"由旧模型生成"，提供重刷入口。
- SyncController：IntersectionObserver 取左侧可见页/块 → 计算主块 → TransPane scrollTo；反向同理；悬停用共享 `hoverBlockId` store 双向高亮；滚动同步加 200ms 防抖 + "正在程序化滚动"互斥锁防回环。
- 视口上报：可见块集合变化时 debounce 500ms POST `/viewport`。

## 6. 跨切面

- **配置**：`config.yaml`（路由表/阈值/解析服务 URL）+ `.env`（key）。启动自检：key 有效性（1 次最小调用）、解析服务连通（MinerU `/health`）、sqlite-vec 加载（失败时输出 VC++ Redistributable/自编译 DLL 两条诊断路径——Windows 加载失败有社区实录，此项列入 S0/S1 验收）、embedding 模型可用、孤儿 `parsing` 状态回收，结果落 `/api/health`，前端启动页展示。
- **错误与状态**：所有长任务在对应表上有 `status/error` 字段；SSE 通道有 `error` 事件；前端所有异步卡片三态（loading/失败+原始错误码/重试按钮）。
- **测试**：spike 断言集（S0 建立，S7 回归）；单测覆盖 postprocess 正则、优先级队列、漂移校验、锚点校验映射；prompt 变更用 3 篇固定论文的"金样例"人工 diff。
- **实现顺序**：严格按 mvp-plan §三 的 S0→S7；每步的验收即 mvp-plan §七 对应条目。

## 7. 已知风险的技术对策映射

| 风险（mvp-plan §六） | 本方案对策 |
|---|---|
| R1 解析质量 | §5.1 服务化+锁版本+postprocess 兜底；spike/parse_bench.py 断言化；bbox_viewer 常驻 |
| R2 锚点可靠性 | §5.2 call_structured + §5.4 受限候选集 + 服务端校验；拒答计正确 |
| Windows 部署 | MinerU 走 WSL2/Docker HTTP 服务（异步 /tasks API），主应用纯 Windows Python；无 GPU 时 pipeline 后端兜底；CUDA 驱动版本 spike 第一步核查 |
| sqlite-vec Windows DLL 加载失败 | setup 锁验证过的 wheel + 启动自检 + 诊断指引（S0/S1 验收项） |
| 成本失控 | 路由表分档 + prompt caching（注意 5 分钟 TTL 口径）+ 全量持久化缓存 + llm_calls 成本日志 |
