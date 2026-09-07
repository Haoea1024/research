# CLAUDE.md — 工作约定（任何会话开始先读这里）

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
- S2 已编码并用真实 ResNet PDF 在本机 Chrome 完成验收，当前等待用户确认。
- 未经用户明确确认，不得进入 S3，也不得提前实现真实翻译、Embedding、RAG、问答、报告或其他 S3-S6 业务。

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

## 3. 固定实现裁定

- Parser 保持统一抽象：`parse(pdf_path) -> ParseResult`；业务层不得依赖 MinerU CLI 原始输出格式。
- MinerU 使用现有 Conda `paper-agent` 环境、已有模型缓存和 Windows 原生 CPU `pipeline`；不得重复安装 MinerU、重新下载模型或调整 WSL2、Docker、CUDA、驱动和系统配置。
- Paper 状态严格为 `uploaded → parsing → parsed | parse_failed`。上传文件成功落盘并建 Paper 后返回 `uploaded`，后台解析实际开始时切换为 `parsing`。
- Retry 仅允许 `parse_failed → parsing`，`parsing` 或 `parsed` 重复触发必须返回 409。
- MinerU 子进程超时 480 秒，记录 exit code、stdout、stderr、OOM 特征与原始错误；任何失败都不得静默吞掉。
- Caption 只有在具备可靠 page/bbox、保持阅读顺序并可追溯原字段时才正规化为独立 Block；不得伪造 bbox。否则保留 Figure caption 与 diagnostics。
- SQLite 不使用 migration framework；初始化必须幂等。sqlite-vec 加载失败不得阻止普通表、Paper、Parser 和 FastAPI 启动，健康接口必须展示原始诊断。
- LLM 层只提供 task 路由、环境变量 key、60 秒超时、一次重试、错误透传、`llm_calls` 和 Pydantic 结构化校验；不得提前添加业务 prompt。测试只用 fake/mock client，不发起收费调用。
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
- 未经明确授权不得 commit 或 push。当前 S1/S2 工作仍保持未提交状态。

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
