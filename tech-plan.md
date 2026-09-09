# 文献研读 Agent — MVP 技术实施方案

> **2026-09 阅读器形态修订**：S3 后新增 S3.5。默认 Reader 由“左 PDF + 右 Block 卡片流”调整为“左原 PDF + 右 HTML/CSS 中文版式页”；现有 Block 流保留为 `structured` 辅助视图。右侧只复刻版式骨架并允许中文 local reflow，不生成译文 PDF。S4 Figure/Table Card 是数据/详情层，不替代正文原位图表；S5/S6 统一通过 Block/Figure anchor 回跳版式 Reader。

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
│     ├─ reader/                 # PdfPane / LayoutTransPane(中文版式页) / StructuredBlockPane / LayoutEngine / SyncController
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

**S3.5 布局数据不新增业务主表**：中文版式页的 `column / layout_group / x_ratio / width_ratio / span` 由 `blocks.page + bbox + order_idx + type` 在前端/确定性 layout service 中派生，不作为新的事实源持久化。这样布局算法可迭代，而 Block/Translation/Anchor 身份不迁移。

S4 起图表 provenance 必须分层：现有 MinerU `caption/image_path/table_html/page/bbox` 永远是 parser-derived；未来 `vision_desc/vision_table_*` 只能写 vision-derived 字段，不能覆盖 parser 字段。

## 4. API 契约（REST + SSE）

```
POST /api/papers                     # multipart 上传 → {paper_id}；后台触发解析
GET  /api/papers                     # 列表（含状态）
GET  /api/papers/{id}                # 状态/元数据/错误
GET  /api/papers/{id}/blocks         # 全部块（阅读器初始化用）
GET  /api/papers/{id}/figures        # 图表/card 数据；parser 数据即使 vision pending 也可返回
GET  /api/figures/{figure_id}/image   # 按 ID 安全返回裁切图，不向前端暴露绝对 image_path
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

S3.5 不要求新增布局 REST API：`blocks + translations + figures` 已足够渲染中文版式页。问答/报告返回的 anchor 继续是稳定 Block/Figure ID，前端统一解析为 Reader 导航目标。

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
- **Glossary 是 Paper/Run 级准备步骤**：抽 title/abstract/标题块 + 本地候选术语，受 `glossary.max_source_chars` 上限约束；`per-paper lock → lock 内二次查询 → exactly one generation`。已有 glossary 直接 DB hit；生成失败则 Run fail-fast，后续 batch 不再隐式重试，也不为尚未调用 translate 的 Block 创建 failed Translation。
- **队列**：单 worker 优先级队列支持 `retranslate > visible viewport > next screen > scoped normal > whole-paper background`；viewport 只上报可见 Block ID，下一屏由服务端按 `order_idx` 推导。batch 默认 3-5 个相邻目标块，带术语表命中子集 + 前后各 1 块 context-only。
- **内容分类**：empty/whitespace、URL/email、纯 HTML、arXiv/脚注元数据等明确 `skipped`，不进入 translate、不创建 failed row；Formula/Figure/Table 继续按 `is_translatable` 规则排除。
- **结构化结果**：batch 输出按 Block ID 做 per-block validation；有效 sibling 可立即 partial commit。只对无效 ID 做一次 structured correction，仍无效的目标才写 `failed`，不能让一个空输出拖死整个 batch。
- **语言漂移**：中文比例阈值默认 0.4；URL、邮箱、HTML tag、标点/数字/空白/LaTeX 等噪声从 denominator 排除。只对漂移 Block 精准重试一次。
- **幂等**：`done` 与 `failed` 都是普通 `submit()` 的持久缓存终态；普通范围重交不自动重试 failed。只有显式 `/retranslate` 才重新收费。旧成功重译采用“成功后替换、失败保留旧译文”的安全语义。
- **调用重试**：LiteLLM/OpenAI client 内部 `num_retries=0`，只保留项目层可审计的 task-level timeout/retry；glossary 与 translate 可有独立配置。
- **SSE**：`block/progress/error/finished`；Run-level glossary failure 使用全局 error，不伪装成 Block 翻译失败；SQLite 是 done/failed/skipped 的权威状态，SSE 只是实时层。

### 5.4 图表卡片（S4A/S4B，详情层而非排版层）

**S4A（不依赖真实视觉模型）**：
- Figure/Table 只要 parser 数据存在即视为 Card 基础数据可用：`image crop + caption + page/bbox + nearby_block_ids`；Table 额外保留 MinerU 原始 `table_html`。
- 对 `table_html` 做**确定性** HTML→cell JSON，形成 `parser_table_json`（row/column、header、rowspan/colspan、cell text 等）。它属于 parser-derived 数据，不调用 LLM。
- Reader 主体中的 Figure/Table 仍在版式页原位展示；Card 的 description、结构化细节、状态和重试入口放在点击后的 drawer/popover。
- Card 状态与 vision 状态解耦：parser 数据 ready 时 Card 可读；另维护 `vision_status` / `embedding_status`，不能因为 vision pending/failed 把 caption/image/table_html 一并判不可用。
- fake vision client 先跑通结构化 schema、缓存、失败重试和旧成功结果保护。

**S4B（真实视觉模型，需单独批准）**：
- 输入 = 裁切原图 + **图注原文 + 同页最近前/后有效 text Block**；缺失则为空，不跨页伪造上下文。
- Figure 输出 `vision_desc` 等 vision-derived 字段；Table 的视觉转录写 `vision_table_md/vision_table_json`，**不得覆盖** MinerU `table_html` 或 `parser_table_json`。
- provenance 分离：`source_hash` 只描述图像/caption/nearby parser 输入；`generator_fingerprint` 单独描述 vision model、prompt version、generation config。
- 刷新遵循“旧成功保护”：新生成成功后原子替换；刷新失败保留旧成功 Card，并记录 refresh error；首次生成失败才进入 failed。
- 每卡独立任务，可精准 retry；真实 provider、Base URL、model ID、图片协议不在代码中猜测，走现有 LiteLLM task route。

### 5.5 Embedding / 检索基础与问答边界（S4 → S5）

**S4A embedding/index 基础**：
- bge-m3 只生成 dense 1024 维向量，项目级 `max_length=512`；正文 payload 默认只带最近 section heading + `content_md`，不对每个正文重复拼 paper title。短标题可按确定性规则补 paper title。
- Block 入索引先复用内容分类器排除 empty/URL/email/HTML/meta；`title` 非空即可，普通 text 的最小长度通过 `embedding.min_text_chars` 配置（初始值由真实 ResNet 统计验证，不把预计候选数写死）。
- 进程级 lazy singleton；首次加载用 lock，CPU inference 额外用 semaphore=1，避免多个 `to_thread()` 同时抢 CPU/RAM。运行时不得隐式联网下载模型；配置应指向明确本地模型目录/固定 revision。
- `embedding_records`（S4 schema upgrade）记录 `source_hash` 与 `model_fingerprint`，两者分离。refresh 先 encode+校验新 vector，再事务性替换旧 vec；刷新失败不得先删旧成功向量。
- Figure/Table 的初始向量可由 parser-derived Card 生成：Figure=`caption+nearby text`；Table=`caption+parser_table_json normalized text+nearby text`。若文本不足则记录 `insufficient_text`，等 vision 内容成功后触发 refresh。
- sqlite-vec 查询必须在 KNN 内使用 `paper_id` partition filter；S4 实现内部 `embed_query()/search_blocks()/search_figures()` 并做中英跨语言召回 smoke，但暂不冻结正式产品级 search HTTP contract。

**S5 问答**：
- 查询流程：`embed(question)` → 文本/图表两路召回 → 合并去重成**编号候选集**（含 block 摘要与 figure 卡片）→ 若命中 figure，附裁切原图 → `call_structured(qa, AnsweredWithAnchors)`；schema 中 `claims[].anchor_ids` 只允许候选集编号，服务端映射回稳定 Block/Figure ID 并丢弃非法值 → top1 相似度低于阈值时 `confidence=low` 并在 prompt 中强化拒答许可。qa prompt 固定附术语表命中子集。
- 划选提问：左 PDF 或右中文版式上的选择最终都转换为 `selected_block_ids`，直接作为候选集前排，不走检索；选中 figure/table 时附裁切原图。
- 前端来源锚点不跳“卡片编号”，统一调用 `navigateToAnchor(anchor)`：左 PDF 定位 page+bbox，右 `layout` 视图定位对应中文 Block/Figure，并同步高亮；`structured` 模式也能定位同一 ID。

### 5.6 精读与改进方向（report/）
- 每段一个 prompt 模板，输入 = 缓存全文前缀 + 相关图表卡片（④⑥）+ 已生成段的 `summary` 列表 + （可选）对话摘要。输出 schema：`{content_md, anchors, summary}`，锚点同样走受限候选集（该段检索 top-16 作候选）；前端点击 anchor 统一回跳版式 Reader（左 PDF bbox + 右中文版式对应块/图表）。**s6（实验与消融）模板内置"复现风险审查"固定 checklist：benchmark 选择恰当性 / 数据泄漏嫌疑 / 指标误用 / post-hoc 挑结果**——实现时不可省略。
- 三层改进方向：第一层（枚举→三角色 checklist 批评→修订，**结果存 `proposal_cards` idx=0/kind=axes**）→ 第二层提案卡（Pydantic：question/why_now/mvp_experiment/feasibility/info_gaps/risk_planB）→ 第三层每卡故事线生成 3 候选 → pairwise 两两比较（3 次 `compare` 调用）取胜者 → 具体性检查器（规则：须含 ≥1 数据集名 + ≥1 模块/指标名；再过 haiku checklist）不合格段落打回重生成（最多 1 轮）。

### 5.7 阅读器前端（frontend/reader/）— S3.5 版式翻译 Reader

- **PdfPane 保持 S2 实现不动**：pdfjs-dist 按页 canvas 自绘 + 每页绝对定位 overlay；bbox 从 0-1000 换算到页面 CSS viewport。page-ready 使用 `page.render()` 返回的 `RenderTask.promise`，目标页未渲染时 await 后再画框。不要为了中文版式 Reader 重写 PdfPane、bbox 语义或 DPR 逻辑。

- **LayoutEngine（确定性、无 LLM）**：输入 `page/bbox/order_idx/type`，派生：
  ```text
  column          -- left | right | full | unknown
  layout_group    -- 同列/同跨栏组
  x_ratio
  width_ratio
  span
  ```
  横向 bbox 用于列归属、位置和宽度；纵向 y 主要用于排序与原始间距提示。无法可靠判定时以 `order_idx` 保证阅读顺序，不伪造高精度布局。

- **LayoutTransPane（默认 `viewMode=layout`）**：
  - 按原 PDF 页建立对应的 HTML page shell；尽量保持同样宽高比、页边距与单双栏骨架。
  - title/text/caption/formula/figure/table 仍绑定原 `block.id`。
  - 中文 text 不设置原 bbox 固定高度，允许内容自然撑高；同一 layout group 内后续 Block 顺次下移（local reflow）。禁止为了“一页像素对一页”极端缩字号。
  - Figure 在原列/跨栏位置显示 crop；Table 优先显示安全的 parser 结构；caption 在对应位置显示译文/原文 fallback。
  - page shell 可以因中文 reflow 局部增高；同步以 Block anchor 为准，不使用左右像素滚动比例。
  - pending/failed/skipped 的展示复用 S3 状态：pending 可英文 fallback，failed 显式错误/重试，skipped 保留原文及 skip reason。

- **StructuredBlockPane（保留现有实现）**：现有 react-virtuoso Block 流不删除，改为 `viewMode=structured`。它继续承担 block id/type/status、原文展开、重译、错误诊断等精细操作。不要把它作为默认论文阅读形态。

- **viewMode**：
  ```text
  layout       -- 默认：原 PDF + 中文版式页
  structured   -- 辅助：原 PDF + Block 流
  ```
  未来 `translation-only` 等模式可再扩展，不在 S3.5 实现。

- **SyncController 只依赖稳定身份**：
  - 左→右：IntersectionObserver/当前可见 bbox 得到主 `block.id` → `LayoutTransPane/StructuredBlockPane.scrollToBlock(id)`；
  - 右→左：右侧可见主 Block → PdfPane `scrollTo(page)` → page ready 后高亮 bbox；
  - hover 使用共享 `hoverBlockId`；
  - 程序化滚动使用 generation/token + user takeover 机制防回环，不能退化成简单固定 200ms 锁；
  - 中文高度变化只影响右侧 DOM，不改变 anchor 身份。

- **统一 AnchorNavigator**：S5 QA、S6 report、Figure/Table 详情都只提交 `block_id/figure_id`，由 navigator 查实体后同时定位左 PDF 与右版式页。引用不通过正文短语模糊匹配。

- **Figure/Table 详情层**：正文原位对象可点击打开 drawer/popover，展示 parser 数据、vision description、表格结构、状态/重试和相关上下文；关闭后阅读位置不变。AI Card 不插入正文流造成布局跳变。

- **视口翻译优先级**：可见 Block 集合来自当前 active 右侧视图；变化时 debounce 后 POST `/viewport`。`layout` 与 `structured` 都上报同一 Block ID 集合。

- **S3.5 不改变翻译/解析业务语义**：不改 glossary、Translation cache、MinerU、Figure crop、Block ID、page/bbox；只是增加新的 renderer 与共享导航层。

## 6. 跨切面

- **配置**：`config.yaml`（路由表/阈值/解析服务 URL）+ `.env`（key）。启动自检：key 有效性（1 次最小调用）、解析服务连通（MinerU `/health`）、sqlite-vec 加载（失败时输出 VC++ Redistributable/自编译 DLL 两条诊断路径——Windows 加载失败有社区实录，此项列入 S0/S1 验收）、embedding 模型可用、孤儿 `parsing` 状态回收，结果落 `/api/health`，前端启动页展示。
- **错误与状态**：所有长任务在对应表上有 `status/error` 字段；SSE 通道有 `error` 事件；前端所有异步卡片三态（loading/失败+原始错误码/重试按钮）。
- **测试**：spike 断言集（S0 建立，S7 回归）；单测覆盖 postprocess 正则、优先级队列、漂移校验、锚点校验映射；S3.5 增加双栏/跨栏 layout 推导、中文长短 reflow、Figure/Table 原位、`layout↔structured↔PDF` 同一 block 导航、快速滚动 user takeover 与无回环 E2E；prompt 变更用 3 篇固定论文的“金样例”人工 diff。
- **实现顺序**：严格按 mvp-plan §三 的 `S0→S1→S2→S3→S3.5→S4A→S4B→S5→S6→S7`；S3.5 只改展示层，S4A 先本地数据/embedding/fake vision，真实视觉在 S4B 单独 gate。

## 7. 已知风险的技术对策映射

| 风险（mvp-plan §六） | 本方案对策 |
|---|---|
| R1 解析质量 | §5.1 服务化+锁版本+postprocess 兜底；spike/parse_bench.py 断言化；bbox_viewer 常驻；S3.5 额外用 bbox/order 验证单双栏与跨栏 layout 推导，不允许布局算法改写 Block 事实 |
| R2 锚点可靠性 | §5.2 call_structured + §5.5 受限候选集 + 服务端校验；拒答计正确 |
| Windows 部署 | MinerU 走 WSL2/Docker HTTP 服务（异步 /tasks API），主应用纯 Windows Python；无 GPU 时 pipeline 后端兜底；CUDA 驱动版本 spike 第一步核查 |
| sqlite-vec Windows DLL 加载失败 | setup 锁验证过的 wheel + 启动自检 + 诊断指引（S0/S1 验收项） |
| 成本失控 | 路由表分档 + prompt caching（注意 5 分钟 TTL 口径）+ 全量持久化缓存 + llm_calls 成本日志 |
