# DEVLOG — 文献研读 Agent 开发记录

## 2026-09-07 — S0：环境探测、MinerU smoke test 与 bbox viewer

### 范围与环境

S0 只验证解析链路，不实现数据库、FastAPI、正式 React、翻译、RAG 或报告。真实运行环境为 Windows 10、Conda `paper-agent`、Python 3.11.16、MinerU 3.4.5 和原生 CPU `pipeline`。基础 Anaconda Python 3.13 与 `py` launcher 的 Python 3.14 均不是 MinerU 运行环境。

MinerU pipeline 模型已缓存到本机 ModelScope 目录，配置位于 `%USERPROFILE%\mineru.json`。后续阶段沿用该环境与缓存，不重复安装或下载。Docker、WSL2、GPU/VLM 路线未使用。

### S0 真实结果

- 论文：*Deep Residual Learning for Image Recognition*，arXiv:1512.03385，CVPR 2016。
- 本地文件：`spike/papers/resnet_1512.03385.pdf`，SHA-256 `1e0651b6810ecba34a3dbc5b5b0209226f889004607c1f203540a48d64e5a93a`。
- 命令：`mineru -p spike/papers/resnet_1512.03385.pdf -o spike/out -b pipeline`。
- 12 页解析完成，v1 content list 共 177 个有序块。
- 类型：text 128、table 15、chart 9、page_footnote 6、page_number 12、image 3、equation 2、list 1、aside_text 1。
- `spike/parse_bench.py` 校验结构、页序、bbox、类型、figure/table/caption；`spike/bbox_viewer/generate_viewer.py` 生成逐页可视化。
- `spike/qwen_compare.py` 只保留后置接口占位，不发起网络请求。

PDF、解析输出、页面图片、日志、数据库、模型和虚拟环境均只保留本地并由 `.gitignore` 排除。

## 2026-09-07 — S1：解析流水线、SQLite、FastAPI 与 LLM 基础设施

### 用户批准与阶段边界

用户明确批准开始 S1，并裁定：普通表按 `tech-plan.md §3` 完整建立；sqlite-vec 在 S1 完成加载自检和虚表初始化；业务只做到 S1，不进入前端、翻译、Embedding、RAG、问答或报告。允许 FastAPI `BackgroundTasks`，禁止开发过程启动隐藏 shell/系统后台任务。本轮不 commit、不 push。

### 依赖变更

安装前通过 pip dry-run 确认 Python 3.11 兼容，随后只在现有 Conda `paper-agent` 环境安装并固定：

- `SQLAlchemy==2.0.43`：ORM、连接与事务。
- `litellm==1.77.7`：统一 LLM provider 调用。
- `sqlite-vec==0.1.6`：SQLite 向量扩展与虚表。
- `pytest==8.4.1`：测试。

安装后复核 MinerU 3.4.5、torch 2.14.0、torchvision 0.29.0 未变化；`sqlite_vec.load()` 与 `SELECT vec_version()` 返回 `v0.1.6`。

### 实现摘要

- 新增 Parser Protocol 和应用自有 `ParseResult`/Block/Figure/diagnostics 数据结构。
- MinerU CLI 使用参数数组与 `shell=False` 调用，固定 480 秒超时，捕获 exit code/stdout/stderr，识别常见 OOM 特征并保存原始错误。
- Postprocess 过滤页码/页眉/页脚等块，校验 0..1000 bbox，生成连续阅读顺序，识别公式不可翻译状态，并正规化 Figure/Table。
- Caption 仅在独立 bbox 可靠时生成 caption Block；否则保留 caption 文本、原始 source index/type/field、parent bbox 和诊断。
- SQLAlchemy 建立 `papers`、`blocks`、`translations`、`glossary_terms`、`figures`、`messages`、`report_sections`、`proposal_cards`、`llm_calls`、`meta`，与 `tech-plan.md §3` 一致；初始化幂等，schema version 为 1。
- 初始化 sqlite-vec 虚表 `vec_blocks`、`vec_figures`，均含 `paper_id partition key`；扩展或虚表失败时健康状态降级，普通表和 S1 API 继续可用。
- Paper 状态机固定为 `uploaded → parsing → parsed | parse_failed`；retry 仅接受 `parse_failed`。应用重启会把遗留 `parsing` 显式恢复为 `parse_failed`。
- 新增健康、上传、列表、详情、Block、Figure 和 retry API。
- 新增 LiteLLM 基础封装：task/provider 路由、环境变量 key、60 秒超时、一次 transport retry、原始异常 cause、`llm_calls`、结构化输出校验失败后的单次修正重试。测试只使用 fake client。

### 自动化测试

命令：

```powershell
conda activate paper-agent
python -m pytest
```

最终结果：30 项通过。覆盖数据库完整表/字段、幂等初始化、向量分区键、sqlite-vec 扩展加载与虚表初始化两类降级、遗留状态恢复、Parser 超时/非零退出/OOM/输出错误、caption bbox 规则、Block 顺序、无 caption 表格响应、Paper 状态与 retry、API、LLM transport retry、调用日志、图片消息格式和 Pydantic 结构化重试。没有真实 LLM 收费调用。

测试有两条来自依赖内部的弃用告警：Starlette `TestClient` 对 httpx 旧式 app shortcut 的使用，以及 anyio `BlockingPortal` alias；不影响 S1 结果，未为消除第三方告警而升级已固定依赖。

### 真实 ResNet 全链路验收

使用 S0 已验证的同一文件，不重新下载。启动 FastAPI 后上传，观察到状态依次为：

`uploaded → parsing → parsed`

随后成功查询 blocks 与 figures。`/api/health` 显示 SQLite/WAL/foreign keys/schema v1 正常、sqlite-vec `v0.1.6` 正常、MinerU CLI 可解析；LLM 因默认没有配置任务而显示 `not_configured`，未发起调用。

| 指标 | 实测值 |
|---|---:|
| Paper ID | `0e82764a-ae5a-4f8a-a212-e2896ee50702` |
| 最终状态 | `parsed` |
| MinerU 子进程耗时 | 172.516 秒 |
| MinerU 原始 Block | 177 |
| 应用 Block | 165 |
| 过滤 Block | 12（page_number） |
| Figure Block | 12 |
| Table Block | 15 |
| Figure/Table 记录合计 | 27 |
| 独立 caption 配对 | 0 |
| 无独立 bbox 的内嵌 caption | 20 |
| 公式不可翻译 | 2 |
| 无效 bbox | 0 |
| order_idx 连续 | 是 |

Caption 配对数为 0 不是丢失：本样本 20 个 caption 都嵌在 MinerU Figure/Table 字段中，但没有可靠的独立 caption bbox。实现没有用父块 bbox 伪造 caption Block，而是在 Figure 数据和 `parse_diagnostics.json` 中保留文本与原始字段追踪。

### 与设计文档的差异和待后续事项

- `mvp-plan.md` 把 S1 简写为 Parser/MinerU 实现；本轮根据用户追加裁定，同时完成了原计划中必要的 SQLite/FastAPI/LLM 地基，但没有提前实现任何后续业务。
- `tech-plan.md` 描述了完整未来 API 与业务流水线；S1 只暴露论文、解析、健康和 retry 接口，其余端点仍未实现。
- `paper-reading-agent-design.md` 的完整产品形态包含前端、翻译、检索、问答和报告；当前都仍是后续阶段。
- `tech-plan.md` 的状态示例没有完整表达本轮固定的 `uploaded` 起点和 retry 约束；实际实现以用户本轮裁定为准。
- MinerU 当前样本没有独立 caption bbox，因此不能满足未来“每个 caption 都是可定位独立 Block”的理想形态；已显式诊断，留待后续解析策略处理。
- FastAPI `BackgroundTasks` 不是持久任务队列；S1 通过启动恢复和 retry 保证失败可见，不引入 Celery/Redis。

### S1 结论

S1 代码、自动化测试和真实 ResNet 全链路验收均已完成，并已由用户确认通过。S1 工作尚未 commit/push。

## 2026-09-07 — S2：pdf.js 对照阅读器与双向同步

### 用户批准与阶段边界

用户批准进入 S2：只实现 React/Vite 阅读器骨架、pdf.js 原文、多页按需渲染、bbox overlay、右侧 Block 虚拟列表、基础双向同步滚动和 hover 双向高亮。右侧使用英文 `content_md`；不实现真实翻译、glossary、SSE、viewport priority queue、Embedding、RAG、问答、报告、图表视觉模型或其他 S3-S6 功能。S1 的 MinerU/postprocess 未修改，没有重新下载 PDF 或重跑 MinerU。本轮不 commit、不 push。

### 依赖与安装

在 `frontend/` 新增 npm 工程并生成 `package-lock.json`。`package.json` 的 22 个直接依赖全部使用精确版本，无 `^` 或 `~`：

- 运行时：`react==18.3.1`、`react-dom==18.3.1`、`pdfjs-dist==6.3.289`、`zustand==5.0.15`、`react-virtuoso==4.18.13`、`katex==0.18.7`、`tailwindcss==4.3.3`。
- 开发与测试：`vite==8.2.2`、`typescript==5.9.3`、`vitest==5.0.0`、`@playwright/test==1.63.0`、`@vitejs/plugin-react==6.1.1`、`@tailwindcss/vite==4.3.3`、Testing Library、jsdom 和对应类型包的锁定版本。

安装时设置 `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`，没有下载浏览器；E2E 使用机器现有 Chrome。`npm audit` 结果为 0 vulnerabilities。未安装、升级或重装任何 Python、MinerU、torch 或 torchvision 依赖。

### 实现摘要

- 新增 `GET /api/papers/{paper_id}/pdf`：只按 Paper ID 查询数据库记录，通过 `FileResponse` 返回真实文件；不存在的 Paper 或磁盘文件显式 404，不接收任意路径，也不暴露绝对 `pdf_path`。真实 pdf.js 请求使用 200 响应即可工作，因此没有自行实现 Range/206。
- 新增 React 18 + TypeScript + Vite 前端，`ViewMode` 类型预留 `side-by-side | translation-only`，但 UI 只开放 `side-by-side`。
- pdf.js worker 通过 Vite URL 构建；所有 12 个页面先建立带元数据尺寸的 page shell，再由 IntersectionObserver 按需渲染。
- 每页只维护一个有效 ready promise 和 RenderTask。跳转未渲染页时等待 `RenderTask.promise`，随后等待 React layout effect 确认 overlay DOM 已提交；没有用 `setTimeout`、固定延时或产品轮询猜测就绪时机。卸载会取消 observer、RenderTask 和引用。
- Canvas backing store 按 DPR 放大，CSS viewport 和 bbox 都不乘 DPR。bbox 使用 MinerU 0..1000 坐标换算成页面 CSS 百分比定位，没有为缺失 caption bbox 造框。
- 右侧 `react-virtuoso` 按 `order_idx` 排序并建立 `block.id → Virtuoso index` 映射；跳转不假设未显示 Block 有 DOM 节点。
- Zustand 只保存 `hoverBlockId`、`activeBlockId`、viewMode 和同步 generation/owner/target；RenderTask、canvas、DOM ref、observer 和 page registry 都留在组件内部。
- 同步使用统一 35% 视口参考线。generation token 使旧的异步页面跳转失效；目标收敛后保持来源侧所有权，直到用户在另一侧 wheel/pointer/touch 主动接管，避免尾随 scroll 事件形成反向回声。没有固定时间锁，`scrollend` 也不是正确性依赖。
- hover 只更新视觉状态，不触发滚动；同一 `block.id` 的左侧 bbox 与右侧 BlockCard 同时高亮。
- 公式通过 KaTeX 输出；唯一的 `dangerouslySetInnerHTML` 只承载 KaTeX 生成结果。Figure/Table 使用 caption/文本或明确占位，不新增图片端点，不渲染原始 `table_html`。

### 实现中发现并修正的问题

- 初版未渲染页跳转只等待 pdf.js RenderTask，promise 可能早于 React overlay DOM 提交完成，导致首次取不到目标 bbox。修正为 RenderTask 完成后再等待由 `useLayoutEffect` 解析的 overlay commit promise，仍不使用时间猜测。
- 初版同步在目标首次收敛时立即释放所有权，重复快速验收暴露出尾随 scroll 事件可能反向成为新来源。修正为收敛后保留当前来源所有权，用户在目标侧输入时立即通过新 generation 接管。
- 原始 Table 文本可能很大并影响虚拟列表测量。S2 改为只显示 caption 或明确占位，既保持阶段边界，也避免渲染未处理的 HTML。
- 浏览器 console 曾出现缺失 favicon 的 404，已改为内联 SVG favicon；最终 E2E console/page error 均为空。
- 开发期 HMR 销毁 PDF document 时，页面元数据预取的 `getPage()` rejection 曾产生 `Transport destroyed` 日志；现已显式捕获并增加卸载/拒绝回归测试。

### 自动化测试和构建

最终结果：

| 检查 | 结果 |
|---|---:|
| 后端 pytest | 32 passed |
| 后端第三方弃用告警 | 2（沿用 S1 已接受告警） |
| `pip check` | No broken requirements |
| 前端 Vitest | 7 files / 15 tests passed |
| 真实 Chrome Playwright E2E | 连续 3 次 / 3 次通过 |
| `npm audit` | 0 vulnerabilities |
| TypeScript + Vite production build | 通过 |

前端测试覆盖 API client、bbox 换算、35% 活跃块选择、Zustand generation、BlockCard hover/KaTeX/Table 安全占位、单页唯一 RenderTask/ready promise/清理、overlay commit 时序，以及同步 ID 映射和旧异步 generation 失效。

production build 主 JS 约 906.30 kB（gzip 276.40 kB），pdf.worker 约 1,265.41 kB；Vite 给出大于 500 kB 的 chunk 告警。S2 功能不受影响，代码分包和加载优化不在本阶段范围。

### 真实 ResNet 浏览器验收

沿用 S1 已存在的 Paper `0e82764a-ae5a-4f8a-a212-e2896ee50702`：12 页、165 个应用 Block、12 个 Figure、15 个 Table。没有重新解析。

- 首屏正确显示论文标题、PDF 第 1 页和右侧 `order_idx` Block 流；页面 3-12 初始保持“准备中”，证明按需渲染生效。
- 实际跳转到最后一页后，第 12 页经 RenderTask 完成并出现 12 个 bbox；PDF 滚动位置超过 12,000 CSS px。
- 抽查 title #0、普通正文 #7、formula #40、Figure #57、Table #67：对应 overlay 均可见，位于所属 PDF page shell 内；hover 时左右恰有两个相同 `block.id` 的高亮元素。
- 左侧滚动曾观测到 active `[35, 35]`，右侧滚动曾观测到 active `[18, 18]`，证明两方向均能驱动对应侧。
- 连续/快速滚动、跨未渲染页跳转和用户中途在 PDF 侧接管后，旧 generation 未覆盖新位置；稳定性 E2E 连续三次通过，未观察到明显抖动、无限回环或未处理 console/page exception。
- 本机 Chrome 可视化复核中，正文 #7 的左侧 bbox 与右侧卡片同时高亮，实际读取到两个元素的 `data-block-id` 完全相同。

### 与三份设计文档的差异和待后续事项

- `mvp-plan.md` 对 S2 的目标与本轮一致；本轮按追加裁定使用 `react-virtuoso` 和 Zustand，并把 35% 参考线、generation token、目标收敛、用户接管具体化。
- `tech-plan.md` 提及完整未来翻译/数据流；S2 右栏只展示英文原文，不调用 LLM，不实现 SSE/缓存/翻译状态。
- `paper-reading-agent-design.md` 的最终形态包含图表卡片、翻译、问答与报告；S2 的 Figure/Table 只是安全占位，不新增裁切图片 endpoint 或视觉能力。
- 为满足浏览器读取原始 PDF，S2 按用户裁定新增了设计文档未明确列出的 `/api/papers/{paper_id}/pdf`；实现仍保持 Paper ID 查库与路径不外泄。
- Caption 缺失独立 bbox 的既有情况保持不变；S2 不伪造 caption overlay，也未修改 Parser。
- 当前主 bundle/worker 较大，保留为已知性能问题；viewport priority queue、代码分包和更细粒度渲染优化均未提前实现。

### S2 结论

S2 代码、前后端测试、production build 和真实 ResNet Chrome 验收均已完成，并已由用户确认通过。

## 2026-09-07 — S3：结构化术语与分块翻译流水线

### 阶段启动与 checkpoint

- S0、S1、S2 均已由用户验收通过。
- 编码前安全检查未发现 `.env`、API key、token、密码、PDF、数据库、模型权重、MinerU 生成物、日志、上传文件或不应提交的绝对运行路径。
- 后端 32 tests、前端 15 tests、production build 和 staged diff check 均通过。
- 已创建并 push checkpoint：`07c2693 feat: complete S0-S2 paper reading foundation`，分支 `main`，remote `origin`。
- S3 当前只获批编码与 fake/mock 验收；禁止真实收费 LLM 调用，暂不 commit/push，也不进入 S4-S6。

### 依赖与 schema

- 安装前 dry-run 确认 `sse-starlette==3.4.10` 所需 Starlette/anyio 与当前 FastAPI 0.141.1、Starlette 1.6.0、anyio 4.15.1 兼容；`Jinja2==3.1.6` 已满足。
- 仅在 Conda `paper-agent` 安装并锁定 `sse-starlette==3.4.10`、`Jinja2==3.1.6`，使用 `--no-deps`，`pip check` 为 `No broken requirements`；未升级任何既有 Python/MinerU 依赖，未新增 npm 包。
- `translations` 幂等增加 `error TEXT`，保留 `zh_text NOT NULL`；schema version 从 1 升为 2，可在无 Alembic 情况下幂等升级既有数据库。

### fake/mock 实现结果

- glossary 使用严格 Pydantic `source,target` 结构，按 paper/version 持久化，支持 UTF-8 BOM CSV。并发请求执行“查询 → per-paper lock → 再查询 → 调用”，测试证明只生成一次。
- 翻译范围支持 1-based pages、block_ids 和交集；非本 Paper ID 返回 422，所有入口统一过滤 `is_translatable=1`。
- 常规 batch size 4，按 `order_idx` 邻近且跨度不超过 3 组批；小 scope、viewport 或重译允许 1–2，不把远距离块拼批。
- prompt 使用 Jinja/StrictUndefined 模板，携带标题、目标块、前后各 1 个 context-only Block 和局部命中 glossary；返回 ID 的“不少、不多、不重复、不为空”进入 Pydantic 校验并享有一次结构化纠错重试。
- Run 与真实 Block work item 分离。重叠 Run 订阅同一个 work item，fake 测试中两个 Run 均 finished，而 glossary 和 translate 各只调用一次。
- 队列为单 worker + heapq + asyncio.Condition；generation lazy invalidation 支持 viewport 插队。当前 viewport 为 0、后端推导下一屏为 1、scope 为 2、全文为 3、单块重译为 -1；已发出的调用不取消。
- done/failed 以 SQLite 为权威。done 再次提交直接 cached，不收费；失败保存 `zh_text=""` 与原始 error。已有 done 的单块重译直到成功才原子替换，失败时数据库旧译文和原 error=NULL 均保持不变；单块重译不生成/更新 glossary。
- 中文比例按 CJK/(CJK+Latin) 计算，忽略数字、标点、空白和 LaTeX 命令。低于 config 0.4 时只重译失败 Block 一次，第二次仍低则持久化 `LANGUAGE_DRIFT` failed。
- SSE 实现 block/progress/error/finished、单调 live event ID 和每 Run 256 条 ring buffer。断线不取消 worker；注册订阅早于快照输出，避免 snapshot/subscription 丢事件窗口；重连可由 SQLite/Run snapshot 恢复后继续接收 live event。
- 前端保留 S2 Reader/PdfPane/SyncController 与 `block.id` 身份，只新增翻译 store/API/SSE reader、中文优先、英文展开、pending/queued/translating/done/failed、错误诊断和重译按钮。Figure/Table/Formula 阶段边界保持不变。

### fake/mock 验收

| 检查 | 结果 |
|---|---:|
| 后端 pytest | 48 passed（含真实调用前的错误脱敏与 cached token 日志回归） |
| 后端第三方弃用告警 | 2（既有已接受告警） |
| 前端 Vitest | 9 files / 23 tests passed |
| TypeScript + Vite production build | 通过 |
| Chrome E2E | 2 passed（真实 ResNet Reader + fake S3 SSE） |
| 真实收费 LLM 调用 | 0 |

后端测试覆盖 schema v1→v2、glossary 并发锁/CSV、batch、scope、缓存、重叠 Run、viewport 优先级、漂移重试/失败、SSE 断线重连、单块重译旧缓存保护和完整 API fake 链路。Chrome fake SSE 验证点击“开始/继续翻译”后中文替换英文、原文可展开、progress 更新；真实 ResNet Reader 回归仍覆盖 12 页、bbox、公式、Figure/Table 和同步滚动。

### 第一次真实试译前置状态

- `config.yaml` 当前 `llm.providers`/`llm.tasks` 仍为空，因此 glossary provider/model、translate provider/model、base_url 和 key 环境变量尚未确定；不会意外产生真实调用。
- 既有 ResNet 数据只读统计：12 页、136 个可翻译 Block（114 text + 22 title）、49,313 个源字符；12 Figure、15 Table、2 Formula 均不发送给翻译模型。
- 按当前局部连续 batch 算法，全文预计 39 次 translate 调用，加 1 次 glossary，共约 40 次；若触发语言漂移，每个失败 Block额外最多 1 次。
- 粗略 token 预算：glossary 输入约 7.5k–10k；全部翻译含重复上下文/局部术语约 25k–40k input tokens，约 15k–25k output tokens。实际 tokenizer、prompt 命中和译文长度会改变结果。
- 在 provider/base_url 与具体计价未确认前，无法给出可信货币费用；费用公式为各模型 input/output token 分别乘对应单价。用户先前提到的 `DeepSeek-V4-Pro-0813`（glossary）与 `DeepSeek-V4-Flash`（translate）仍只是待确认路由，不写入业务代码、不视为调用授权。

### 与设计文档的差异和当前限制

- 依用户裁定不新增 `translation_runs`；Run、订阅和 SSE ring buffer 在内存中，进程重启不恢复原 scope，但 SQLite done/failed 仍保留，重新提交只处理未完成块。
- `tech-plan.md` 的示意流程没有定义重叠 Run 去重和重译旧缓存保护；本轮按追加裁定实现为共享 Block work item 和成功后原子替换。
- `paper-reading-agent-design.md` 描述完整最终产品；S3 未实现 Embedding/RAG/问答/视觉卡片/报告，也未修改 MinerU、bbox 和同步架构。
- 当前单 worker 以成本幂等和可预测插队为先；不会取消已发模型调用，新 viewport 在当前调用结束后优先。
- production build 仍有 S2 已接受的大 chunk 告警，本轮不新增依赖或做无关分包。

### S3 fake/mock 结论

S3 获批的 fake/mock 全链路已完成，没有真实 LLM 调用。按约定在第一次真实 ResNet 试译前停止，等待用户确认运行时 provider/model/base_url/key 环境变量、试译页数和费用。

## 2026-09-08 — S3 第一次真实调用：smoke 通过，第一页 baseline 因 glossary 超时停止

### 运行时配置与安全边界

- 平台为 Paratera，OpenAI-compatible Chat Completions，应用 Base URL 为 `https://llmapi.paratera.com/v1`。
- glossary/translate 均路由到实际 model ID `DeepSeek-V4-Pro-0813`；LiteLLM 使用 `openai/DeepSeek-V4-Pro-0813` 协议前缀。
- key 只从 `PAPER_AGENT_API_KEY` 读取；本文档、配置、源码和输出均未记录真实值。
- 调用前新增 Bearer/API key/token 错误脱敏，并补充 OpenAI `prompt_tokens_details.cached_tokens` 日志读取。

### 最小真实 smoke

- 只执行 1 个 HTTP 请求；smoke 内存配置关闭 transport retry、`max_tokens=32`，并用 guard 禁止结构化校验发出第二个网络请求。
- 结果成功：Base URL、Bearer 认证、model ID、LiteLLM `openai/` 路由、Chat Completions 响应和 Pydantic 结构化解析兼容。
- structured-output retry 为 0；96 input tokens、55 output tokens、cache read 0、latency 15,260 ms。
- LiteLLM 未识别自定义模型价格，`cost=NULL`；按平台单价计算 smoke `estimated_cost=¥0.002349`。

### ResNet 第 1 页失败与停止原因

- scope 校验为 `pages=[1]`、17 个可翻译 Block；没有扩大到其他页面。
- 第一个 batch 在生成论文 glossary 时，两个 HTTP 尝试（初次 + 既有一次 transport retry）均返回脱敏后的 `APITimeoutError - Request timed out`，没有产生 glossary、translate 成功记录或 token usage。
- Block order 0–3 已持久化为 `failed`，`zh_text=""`，错误为脱敏后的 glossary timeout；glossary_terms 仍为 0。
- worker 随后处理下一 batch，因为 glossary 尚不存在而错误地再次发起 glossary。发现后立即终止进程；该第三个请求在途时被中断，没有继续等待或提交后续 batch。
- 实际 translate 调用为 0；structured-output retry 和 language-drift retry 均为 0；真实中文 UI 验收与同 scope 零调用 cache 验收无法进行。
- 成功响应可计算成本只有 smoke 的 ¥0.002349。超时/中断请求没有 token usage，是否计费及金额未知，不能伪造 estimated cost。

### 暴露的 pipeline 问题

- glossary 当前在每个 batch 内 `ensure()`；首次生成失败不会形成共享失败状态，导致后续 batch 再次尝试，违背每篇/每 Run 单次 glossary 生成与调用数约束。
- 下一次真实授权前需要先改为 glossary 的 Run/paper 级共享准备步骤：只调用一次；成功后所有 batch 复用，失败则整个 Run fail-fast，禁止逐 batch 重试。
- Paratera 上该 30,000 字符 glossary prompt 未能在现有 60 秒内完成。需要用户决定是提高 timeout、缩小 glossary source，或采取其他单一方案；不得自行猜测并重复调用。
- `llm_calls` 当前只记录成功响应，因此两个 timeout 与一个被中断请求没有行记录；Translation error 保留了脱敏原始诊断。若要求失败 HTTP attempt 也进入 `llm_calls`，需要另行设计 schema/日志语义。

### 当前结论

最小 API smoke 通过，但 ResNet 第 1 页最高质量 baseline 未完成。已停止所有真实调用；不进入第二页、全文、Flash A/B 或 S4，等待用户裁定 glossary fail-fast 修复和 timeout/source 范围策略。

## 2026-09-08 — S3 glossary fail-fast 修复（仅 fake/mock）

### 生命周期与输入收敛

- glossary 从 batch 内提升为 Translation Run 的共享前置 gate。Run 先保持 Block `pending`，执行一次 `ensure_glossary`；成功后才建立/订阅 Block work item，所有 batch 只读取已持久化 glossary。
- 同一 Paper 缺 glossary 的重叠 Run 继续使用 per-paper async lock 与锁内二次查询，fake 并发测试中 glossary LLM 总调用为 1；已有 glossary 时为 0。
- glossary 失败只产生一次全局 `GLOSSARY_PREPARATION_FAILED` error，随后 `finished(status=failed)`；没有进入 translate 的 Block 不创建 `Translation(status=failed)` 行，UI 保持 pending/英文 fallback 并显示页面级可重启提示。
- glossary source 改为标题、摘要、章节标题、本地抽取的高频专名、缩写及模型/模块/数据集候选。配置为 `glossary.max_source_chars=14000`，只在完整 Block/候选项边界截断。
- ResNet 165 Block 实测候选 source 为 5,507 字符、114 个条目：1 个 Paper title、22 个 heading、2 个 abstract Block、89 个候选项；原先请求约 30,000 字符。

### LLM 配置与失败审计

- task route 支持最小 timeout/retry override：glossary 180 秒、0 transport retry；translate 60 秒、1 transport retry。
- SQLite schema version 升为 3；`llm_calls` 幂等增加 `status` 与 `error`。成功记录为 `success`；失败 attempt 为 `timeout/error`，usage 不可得时 token/cost 保持 NULL，错误在落库前脱敏。
- fake timeout 审计示例：`task=glossary`、`model=openai/DeepSeek-V4-Pro-0813`、`tokens_in=NULL`、`tokens_out=NULL`、`cost=NULL`、`status=timeout`、`error=APITimeoutError: ...`（认证信息已脱敏）。

### 精准清理与回归

- 仅清理 Paper `0e82764a-ae5a-4f8a-a212-e2896ee50702` 下本次污染的 4 行 Translation：`0e82764a-ae5a-4f8a-a212-e2896ee50702:0`、`:1`、`:2`、`:3`。
- 删除前逐项确认 Block 属于该 Paper、Translation 为 `status=failed`、`zh_text=""` 且 error 来自本次 glossary timeout；事务删除恰好 4 行，删除后上述 ID 剩余 0 行。未删除其他 Paper、Block、glossary、LLM audit 或解析数据。
- fake Case A-F 均覆盖：成功一次准备服务多个 batch；timeout 为 glossary 1/translate 0/Block failed rows 0；两个 batch 不重复生成；重叠 Run 共用一次生成；已有 glossary 0 调用；task-level 180/0 与 60/1 生效。

| 检查 | 结果 |
|---|---:|
| 后端 pytest | 55 passed |
| 后端第三方弃用告警 | 2（既有已接受告警） |
| 前端 Vitest | 9 files / 24 tests passed |
| TypeScript + Vite production build | 通过 |
| `git diff --check` | 通过（仅 Git 的 CRLF 提示） |
| 新增真实 LLM 请求 | 0 |

下一次 glossary 真实调用预计约 5,507 个 source 字符，连同 prompt 约 1.5k–2k input tokens；实际以 API usage 为准。本次不 commit、不 push、不进入 S4，等待用户重新授权。

## 2026-09-08 — ResNet glossary-only 真实验收

- 严格使用 `DeepSeek-V4-Pro-0813`、180 秒 timeout、0 transport retry；没有实例化 TranslationManager，也没有创建 translate run。
- 真实 glossary 业务调用 1 次、HTTP attempt 1 次、structured retry 0、transport retry 0，状态 success。
- 实际 latency 107,247 ms；input 1,684 tokens、output 8,223 tokens、cached input 0。LiteLLM cost 为空；按平台公开单价计算 `estimated_cost=¥0.237177`，不是平台账单。
- 结构化输出通过并持久化 40 个 glossary term，全部 version 1；source/target 空值 0，按大小写与空白规范化后的重复 source 0。
- 使用会在 cache miss 时立即抛错的本地 guard 再次执行 `ensure_glossary`，成功从 SQLite 返回 40 项，证明后续为 0 LLM cache path。
- Page 1 Translation 行 0，全库 Translation 行 0；真实 translate business calls 和 HTTP attempts 均为 0。
- 术语整体覆盖残差学习、网络结构、CV 任务、检测架构、缩写和数据集。待人工复核项包括 `Building Block → 基本构建块`、`Highway Networks → 高速网络`、`R-CNN → R-CNN（区域卷积神经网络）`、`Shortcut Connections → 捷径连接`、`VLAD → 局部聚合描述符向量`，以及 COCO/MS COCO 的粒度一致性。
- 本轮没有再次发送 glossary、没有翻译任何 Block、没有 commit/push，也没有进入 S4。

## 2026-09-08 — ResNet 第 1 页 V4-Pro translate baseline

### 授权范围与调用审计

- 调用前通过只读 cache guard 确认 glossary 40 项且全部 version 1；第一页 17 个 `is_translatable=1` Block、已有 Translation 0。验收客户端禁止 glossary task，因此新增 glossary business call/HTTP attempt 均为 0。
- 生产配置保持 translate 60 秒 timeout、1 次 transport retry。实际为 5 个正常 batch、1 次 structured correction、3 次 language-drift retry，共 9 个 translate business calls/HTTP attempts；transport retry 0。
- 总 usage：8,354 input tokens、18,363 output tokens、cached input 0；API 调用累计 latency 521,765 ms。LiteLLM cost 均为空，按平台单价估算 `estimated_cost=¥0.570987`。
- 每个 HTTP attempt 的 `(latency_ms, input, output, visible Chinese chars)`：`(13484,571,405,25)`、`(54815,1063,4253,388)`、`(38260,383,2652,29)`、`(17961,1219,1338,448)`、`(114250,1036,4015,501)`、`(43528,2276,574,501)`、`(57418,708,1168,148)`、`(163233,588,2938,51)`、`(18816,510,1020,110)`。多次 output token 远高于可见译文，推测平台 usage 包含隐藏推理 token；这里只记录现象，不修改 reasoning 参数。

### 数据库终态与质量观察

- 17 个目标全部产生权威 Translation 行：12 done、5 failed、cached 0。12 个 done 均为 glossary version 1、`openai/DeepSeek-V4-Pro-0813`、error NULL；5 个 failed 均为 `zh_text=""` 且保留脱敏错误。
- Block 0、7、8、9、10 等译文正确命中 Deep/Residual Learning、Residual Network、ImageNet、ILSVRC、CIFAR-10、COCO、Image Classification 等 glossary 项。未观察到这些成功块内的明显术语漂移。
- Block 13 原文为空但 `is_translatable=1`。模型对其返回空译文，严格 schema 两次均拒绝，导致同 batch 的 13–16 四个目标整体 failed；其中 14–16 的模型可见译文没有被部分落库。
- Block 18 是 URL/脚注，language drift 重译后仍因大量拉丁 URL 使中文比例为 0.0132，最终 failed。这是内容类型过滤与 ratio denominator 的误判，不是普通正文译文漂移。
- 未覆盖的 `degradation problem` 和 `identity mapping` 所在 Block 15/16 因同 batch 空块结构化失败，无法评价真实译法；第一页没有可评价的 shortcut connections/building block 正文样本。
- 因当前普通 submit 会把 failed 行重新排队，而用户明确禁止把 failed 自动重试纳入缓存测试，本次没有提交第二个 `pages=[1]` 请求。done cache 路径的 fake 测试仍通过，但“同范围含 failed 为 0 新调用”尚不成立，属于待修复幂等问题。

### 浏览器与回归

- 使用本机 Chrome channel 打开真实 ResNet Reader；真实中文为右栏主体，英文详情正常，failed Block 显示英文 fallback、错误状态和显式重试入口。
- 真实中文改变 Block 高度后，hover、左→右、右→左、未渲染页跳转、快速滚动与用户接管仍通过；console error 与 page exception 均为 0。未修改 S2 同步架构。
- 首次 E2E 因测试在 hover 同步后点击已被虚拟列表移出的旧第 0 Block 而超时；移除该测试定位假设后真实 Reader 用例 1/1 通过。产品页面没有对应异常。
- 完整回归：后端 55 passed（2 条既有第三方告警）、前端 24 passed、production build 通过；Vite 大 chunk 告警保持已接受状态。
- 本轮未翻译第 2–12 页、未调用 Flash、未修改 glossary、未 commit/push，也未进入 S4。

## 2026-09-08 — 第一页 baseline pipeline 修复（仅 fake/mock）

### Block eligibility 与缓存

- 新增确定性 eligibility：空/纯空白为 `EMPTY_CONTENT`；纯 HTML、URL 脚注、联系邮箱和 arXiv 文档元数据分别标为明确 `skipped`。Skipped Block 不入队、不调用模型、不新建 Translation failed 行，API/SSE/UI 保留英文并显示 skip reason。
- language ratio 在计数前移除 URL、email 和 HTML 标签，普通中文附带长 URL 不再被大量拉丁字符误判。
- 普通范围 submit 现在同时缓存 done 和 failed；failed 不再自动重新收费。只有显式 `/retranslate` 会建立新 work item。真实 ResNet 的本地 guard 复验为 done 10、failed 3、skipped 4，0 pending/queued/translating、LLM 调用 0；历史 baseline 行未删除。

### Batch partial commit

- translate batch 改为逐项验证 `block_id`、非空 `zh_text`、重复与缺失；首轮有效 sibling 保留，仅对无效 ID执行一次结构化纠错。
- 纠错后仍无效的 Block 单独写 failed，其他有效 Block 正常 done；额外 ID 永不落库。纠错 transport 失败也不会破坏首轮已验证译文。
- fake batch 验证同一批一个有效、一个持续空输出时最终为 1 done/1 failed，而不是整个 batch 失败。

### Timeout 定位

- 本地检查 `litellm==1.77.7` 源码确认 OpenAI-compatible client 默认带内部 retry；此前只传 `timeout=60`，项目外层 retry 与 LiteLLM 内层 retry 叠加，可解释约 163 秒墙钟调用。
- 每次调用现显式传 `num_retries=0`，由 LiteLLM 映射为 OpenAI client `max_retries=0`；仅保留项目 LLMClient 的 task-level 外层 retry。fake timeout 测试确认 translate 两个外层 attempt 都为 60 秒参数且 `num_retries=0`，glossary 仍为单 attempt 180 秒。

### 回归结果

| 检查 | 结果 |
|---|---:|
| 后端 pytest | 60 passed |
| 前端 Vitest | 9 files / 25 tests passed |
| production build | 通过 |
| 第三方弃用告警 | 2（既有已接受） |
| 新真实 LLM 请求 | 0 |

覆盖 empty Block、URL/email/HTML/document metadata、ratio noise、batch partial failure、failed cache、explicit retranslate、timeout/内部 retry、overlap run、SSE 与既有完整 API fake 链路。本轮未删除真实 baseline 历史行、未 commit/push、未调用 Flash，也未进入 S4。

## 2026-09-08 — ResNet 第 1 页受控 Pro 修复验收

- 调用前确认 glossary version 1、40 项；真实 glossary business call/HTTP attempt 均为 0。
- 历史 failed 行中，Block `:13` 与 `:18` 已分别归类为 `EMPTY_CONTENT` 和 `URL_METADATA`，未重译。仅显式重译第 1 页有效正文 Block `:14`、`:15`、`:16`。
- 三个 Block 均一次成功：translate business call 3、HTTP attempt 3、structured/transport/language-drift retry 均为 0；latency 分别为 8,760 / 7,717 / 8,206 ms。
- usage 合计为 input 1,849、output 1,545、cached input 0；按 Paratera 单价估算 `estimated_cost=¥0.058356`，LiteLLM cost 仍为空。可见译文长度分别为 179 / 147 / 177 字符。
- 三条 Translation 均为 `done`、glossary version 1、model `openai/DeepSeek-V4-Pro-0813`、error NULL。`degradation problem` 译为“退化问题”，`identity mapping` 稳定译为“恒等映射”。
- 随后普通提交 `pages=[1]`，得到 done 13、skipped 4、failed 0；新增 glossary/translate business call 与 HTTP attempt 均为 0。
- Chrome 人工实测确认中文主体、4 个英文 fallback/skip reason、Block 16 hover 双向高亮、左右同步、快速滚动与用户接管正常，console error 为 0。
- 同步更新真实 Reader E2E 的旧 failed 断言并加入 4 个 skipped 检查；Chrome E2E 2 passed，测试同时捕获 page exception 与 console error，均为 0。
- 本轮未翻译第 2–12 页、未调用 Flash、未修改 reasoning、未 commit/push，也未进入 S4。

### S3 最终清理与回归

- 删除前再次确认 `0e82764a-ae5a-4f8a-a212-e2896ee50702:13` 与 `:18` 均属于指定 ResNet 第 1 页、旧 Translation 为 failed、`zh_text=""`，且当前分别归类为 `EMPTY_CONTENT` 与 `URL_METADATA`，不是成功译文。
- 单事务仅删除上述两个 Translation 主键。全库 Translation 从 17 降为 15；Glossary 40、Block 165、LLM audit 14 均未变化，两条目标记录删除后均不存在。
- 最终 ResNet 第 1 页权威状态为 13 done、4 skipped、0 failed；glossary 为 version 1、40 项，重复 `pages=[1]` 为 0 次新 LLM 调用。
- 最终无模型回归：后端 60 passed（2 条既有第三方弃用告警）、前端 Vitest 9 files/25 tests、production build、Chrome E2E 2 tests、`pip check` 与 `git diff --check` 均通过。
- S3 Translation 状态为 COMPLETE。本次收尾没有真实 LLM 请求，没有进入 S4。
