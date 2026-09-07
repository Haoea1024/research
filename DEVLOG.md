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

S2 代码、前后端测试、production build 和真实 ResNet Chrome 验收均已完成，等待用户确认。尚未 commit/push，也未进入 S3。
