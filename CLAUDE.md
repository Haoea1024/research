# CLAUDE.md — 工作约定（任何会话开始先读这里）

> 当前开发状态：S3.5 / S3.5.1 已稳定合入 main；当前分支 `s3.6-hybrid-translation` 正在完成 S3.6A Hybrid Translation Infrastructure。只允许 fake/mock，不得调用真实 LLM/Translation API、进入 S4 或 commit/push，除非用户另行授权。

## 0. 必读文档

开始工作前按以下顺序完整阅读：

1. `README.md`
2. `DEVLOG.md`
3. `paper-reading-agent-design.md`
4. `mvp-plan.md`
5. `tech-plan.md`

产品范围以 `mvp-plan.md` 为准，技术实现细节以 `tech-plan.md` 为准；二者冲突时，范围问题优先 `mvp-plan.md`，实现问题优先 `tech-plan.md`，并明确记录待确认事项。`tech-plan.md §3` 是数据库 schema 的权威定义。

## 1. 当前阶段

- S0 已完成。
- S1 已由用户验收通过。
- S2 已由用户验收通过，S0-S2 checkpoint `07c2693` 已 push 到 `origin/main`。
- S3 Translation 已完成最终 fake/mock 与真实验收：Paratera `DeepSeek-V4-Pro-0813` glossary 40 项已持久化，ResNet 第 1 页最终为 13 done、4 skipped、0 failed，同范围复验 0 次新 LLM 调用；Chrome 双向同步/hover 通过且 console/page exception 为 0。未经新授权不得继续真实调用、调用 Flash 或进入 S4。
- S3.5 / S3.5.1 已完成：最终 ResNet API eligibility 为 121 done、0 failed、15 skipped；全文幂等复验产生 0 次 glossary、translate 和 HTTP 调用。Abstract、Figure 3 mixed-column、inline KaTeX、`<sup>` 与 Reader 零自动翻译调用均通过 Chrome 回归。
- S3.6A 已实现厂商无关 provider/router、request-scoped token protection、共享最终校验、按 Block 质量 fallback、provider outage circuit/run failure、source hash cache provenance、provider/LLM 业务审计及只读 benchmark seam；默认 strategy 仍为 llm。真实 provider 选择和 A/B 留到 S3.6B，caption 表/API/UI 留到 S3.6C。
- 不得提前实现 Embedding、RAG、问答、Figure Card、视觉模型、报告或其他 S4-S6 业务。

## 2. S1 已批准范围

- Parser Protocol、MinerU CLI parser 和解析结果 postprocess。
- SQLite 完整普通表 schema、幂等初始化、sqlite-vec 自检及虚表初始化。
- Paper 上传、解析状态机、失败重试与查询接口。
- FastAPI 后端地基和 S1 API。
- `llm.call` 与 `call_structured` 基础封装。
- 配置、依赖锁定、测试和文档同步。

S1 未实现前端、翻译、Embedding、RAG、问答、报告或 Qwen3-VL 产品代码，也未引入 Celery、Redis、Qdrant、Postgres、Alembic 等未批准技术。

## 2.1 S2 已批准范围

- React 18 + TypeScript + Vite 前端骨架。
- pdf.js 左侧原始 PDF、多页按需渲染和 bbox overlay。
- `react-virtuoso` 右侧 Block 流，展示英文 `content_md`；Figure/Table 只显示现有 caption、文本或占位。
- 以 `block.id` 为身份的左右同步滚动、generation token 防回环、目标位置收敛和用户主动接管。
- `hoverBlockId` 双向高亮，且与 `activeBlockId` 分离。
- `ViewMode = side-by-side | translation-only` 类型预留，但只开放 `side-by-side`。
- 使用 S1 API 获取 Paper/Block/Figure，并新增按 Paper ID 返回真实文件的 PDF endpoint。

S2 禁止真实翻译、glossary、SSE、viewport priority queue、Embedding、RAG、问答、报告、视觉模型和 S3-S6 产品能力。除非发现阻塞性解析 bug，否则不得修改 S1 MinerU/postprocess。

## 2.2 S3 已完成范围

- 结构化 `source,target,version` glossary 持久化与 CSV 导出；生成使用 per-paper async lock 和锁内二次查询。
- 只对 `is_translatable=1` Block 翻译；支持 1-based `pages`、`block_ids` 及二者交集。
- 常规 batch size 4，优先连续/邻近 Block；附带前后各一块上下文、论文标题和命中 glossary 子集。
- Run 与 Block work item 分离；重叠 Run 订阅同一真实任务，完成后各自 progress/finished。
- 单 worker、`heapq`、`asyncio.Condition` 与 generation lazy invalidation；优先级为重译 -1、当前 viewport 0、下一屏 1、scope 2、全文 3。
- SQLite done/failed 缓存与幂等续跑；翻译表保留 `error TEXT` 并增加 source/provider/route/validation provenance，`llm_calls` 增加业务关联字段，非 LLM provider attempt 使用独立审计表；schema version 4，无 Alembic。
- 中文字符比例阈值 0.4，忽略数字、标点、空白和 LaTeX 控制命令；漂移只单块自动重译一次。
- SSE 至少包含 block/progress/error/finished，使用有限 ring buffer；断线不取消 worker，重连先恢复权威快照再订阅事件。
- Reader 保持原 `block.id` 同步身份，增加中文优先、英文 fallback、五态展示与单块重译入口；未重写 PdfPane/SyncController。
- S3 已配置 Paratera OpenAI-compatible 路由，glossary/translate 均为 `DeepSeek-V4-Pro-0813`。最小 smoke、glossary-only、第一页 baseline、pipeline 修复和受控真实复验均已完成；没有实现 S4-S6 能力。
- glossary 在每个 Run 建立 Block work item 前只准备一次；失败时 Run fail-fast、Block 保持 pending。输入上限 14,000 字符，ResNet 候选输入实测 5,507 字符；glossary 为 180 秒/0 transport retry，translate 为 60 秒/1 retry。

## 3. 固定实现裁定

### S3.5 Reader 裁定

- 默认视图是 `PDF + LayoutTranslationView`，`StructuredBlockView` 必须保留为辅助/调试视图；两者共享原始 `block.id`、翻译状态和同步控制，不复制业务状态。
- 页面列、full-width、media row、confidence 和 diagnostics 都是 parser `page/bbox/type/order_idx` 的确定性前端派生，不持久化、不成为 anchor，也不调用 LLM。
- bbox 不可靠时优先 `fallback-flow`。中文允许在列内自然 reflow 和延长页面，禁止写回 PDF、强塞原 bbox、裁切或重叠译文。
- Figure/Table 正文流仅使用 ID-based 安全图片端点和 parser caption；不得注入 raw `table_html`。表格确定性结构化留到 S4A。
- 双栏证据可包含稳定落在单列、不跨 gutter 的 Figure/Table；左右列必须独立 reflow。marginalia 必须同时满足靠边、高窄及与正文列低重叠，`title` 不能仅因窄 bbox 被归入边注。
- Structured/Layout 共用 mixed-content renderer；行内数学交给 KaTeX，`<sup>` 只做安全白名单解析，其他 HTML 保持转义。
- `REFERENCE_LIST` 与 `MALFORMED_FRAGMENT` 为确定性 skipped reason；历史 Translation 行不在 UI eligibility 读取时删除。全文翻译必须显示预计目标数并经用户明确确认。
- Caption 翻译留到 S3.6：以 `figure_id` 为键保存 `caption_source/caption_zh/caption_model/caption_status`，anchor 仍为 `figure_id → block_id`；不得伪造独立 caption bbox。
- Layout/Structured 切换属于本地 position restore，必须以 active `block.id` 收敛并沿用 generation/user-takeover 语义，不能触发 PDF 往返同步。

- Parser 保持统一抽象：`parse(pdf_path) -> ParseResult`；业务层不得依赖 MinerU CLI 原始输出格式。
- MinerU 使用现有 Conda `paper-agent` 环境、已有模型缓存和 Windows 原生 CPU `pipeline`；不得重复安装 MinerU、重新下载模型或调整 WSL2、Docker、CUDA、驱动和系统配置。
- Paper 状态严格为 `uploaded → parsing → parsed | parse_failed`。上传文件成功落盘并建 Paper 后返回 `uploaded`，后台解析实际开始时切换为 `parsing`。
- Retry 仅允许 `parse_failed → parsing`，`parsing` 或 `parsed` 重复触发必须返回 409。
- MinerU 子进程超时 480 秒，记录 exit code、stdout、stderr、OOM 特征与原始错误；任何失败都不得静默吞掉。
- Caption 只有在具备可靠 page/bbox、保持阅读顺序并可追溯原字段时才正规化为独立 Block；不得伪造 bbox。否则保留 Figure caption 与 diagnostics。
- SQLite 不使用 migration framework；初始化必须幂等。sqlite-vec 加载失败不得阻止普通表、Paper、Parser 和 FastAPI 启动，健康接口必须展示原始诊断。
- LLM 层提供 task 路由、环境变量 key、task-level timeout/retry、错误透传、成功/失败 `llm_calls` 审计和 Pydantic 结构化校验；glossary 为 180 秒/0 transport retry，translate 为 60 秒/1 retry。
- 产品代码允许 FastAPI `BackgroundTasks`；开发过程禁止私自启动 shell 或系统级隐藏后台任务。
- PDF endpoint 必须通过 Paper ID 查数据库获取文件，不接受前端本地路径，不暴露绝对 `pdf_path`；先使用 Starlette `FileResponse`，不自行实现 Range 服务器。
- bbox 坐标基于页面 CSS viewport，不乘 `devicePixelRatio`；DPR 仅影响 canvas backing store。
- 页面就绪只信任对应 `RenderTask.promise`；每页只保留一个有效 render/ready promise。卸载时取消 RenderTask、observer 和引用，不使用固定延时或轮询猜测渲染时机。
- 同步参考线统一由 35% 常量配置。同步所有权在目标收敛后保持到用户主动接管，避免尾随 scroll 事件反向回声；wheel/pointer/touch 会立即使旧 generation 失效，不使用固定时间锁。
- `order_idx` 只用于映射 Virtuoso index；同步身份始终为 `block.id`，不得依赖文本或未渲染 DOM。
- RenderTask、canvas、DOM ref、observer 等运行时对象只存组件 registry，不进入 Zustand。
- 不直接渲染 MinerU 原始 `table_html`；当前唯一 `dangerouslySetInnerHTML` 用于 KaTeX 库生成的公式 HTML。

## 4. 工程纪律

- 工作目录限于本仓库 `D:\research\paper-agent`，不得修改 `D:\research` 下其他目录，包括 `.tmp`。
- 未经批准不得切换技术栈或扩大产品范围。
- 新增 Python 包前先列出包名、固定版本和用途并等待批准。
- 不提交密钥和 `.env`；不提交 PDF、模型、数据库、日志、上传文件、解析生成物或虚拟环境。
- 阶段完成前必须用真实数据跑出可复现证据，不能只以单测或“应该能运行”代替。
- 阶段、功能、目录、依赖、命令、架构或阻塞变化时同步更新 `README.md`；实测证据同步更新 `DEVLOG.md`。
- S0-S2 已按用户授权完成 checkpoint 和 push。S3 已完整验收，并获批创建单次 checkpoint 与 push；后续仍须按用户授权决定 Git 操作。

## 5. 当前实测基线

- Windows 10，Conda `paper-agent`，Python 3.11.16。
- MinerU 3.4.5，Windows 原生 CPU `pipeline`。
- S0 ResNet 样本：`spike/papers/resnet_1512.03385.pdf`，不重新下载。
- S1 最新结果：最终 `parsed`，MinerU 172.516 秒，原始 177 Block，应用 165 Block，12 Figure、15 Table、过滤 12、公式不可翻译 2、无效 bbox 0、order 连续。
- 20 个内嵌 caption 均无可靠独立 bbox，因此 caption Block 配对为 0，已记录 diagnostics。
- S1 验收基线：30 项通过；S2 增加 PDF endpoint 测试后后端共 32 项通过，仍有 2 条已接受的第三方依赖弃用告警。
- S2 前端：15 项 Vitest 单元/组件测试通过，Vite production build 通过，npm audit 为 0 vulnerabilities。
- S2 真实 Chrome E2E 使用既有 Paper ID `0e82764a-ae5a-4f8a-a212-e2896ee50702`，稳定性复测 3/3 通过；覆盖 12 页、165 Block、公式、Figure、Table、未渲染页跳转、双向连续/快速滚动、hover 和用户接管，console/page error 为 0。
- S2 未重新下载 PDF、未重跑 MinerU、未下载 Playwright 浏览器，也未进入 S3。
- S3 最终回归：后端 60 tests、前端 25 tests、production build、Chrome E2E 2 tests 和 `pip check` 均通过。真实验收结束后不得继续发起 LLM 请求。
