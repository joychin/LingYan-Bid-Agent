# AGENTS.md

本仓库是灵燕智能（智能标书 Agent 桌面客户端，local-first）的 monorepo。
给在本仓库工作的 coding agent 的约定。

**事实来源分层**：

- 需求唯一事实来源 `tender-agent-mvp-prd.md`；Artifact/任务系统的设计与决策唯一事实
  来源 `artifact-system-design.md`（改动相关代码前必读）。**这两份文档不在当前工作树**
  （2026-09-09 开源整理时移出，删除提交 08b93c1；需要时从 git 历史取
  `git show 08b93c1^:<文件名>`，新 clone 里没有是正常的）。
- **历史决策档案：`docs/decision-log.md`**——全部已完成批次的动因、根因分析、被否方案
  与「明确不做」拍板的原始记录，按域分六章。**改相关代码前先查同域条目**（或全文 grep
  关键词），先弄清「为什么长这样、什么被否过」再动手。
- **新批次的记录写 decision-log，不再写本文件**——仅当批次改变了现行规则时，才同步
  改写本文件对应条目（本文件保持「现状规则速览」，体积上限几百行）。
- `docs/skill design/`（重构手册上/下 + `schemas/` 四个 JSON Schema）是证据包/skill
  体系的设计参考材料（自包含，面向新场景重建，非本仓现状的实现说明）；
  `docs/prototypes/` 放 HTML 原型页。改 skill/契约相关工作前值得先翻。

许可：**AGPL-3.0-only**（2026-09-10 定；LICENSE 全文 + 根/frontend/sidecar/src-tauri
manifest 同步）——`skills/` 方法论与提示词一并受其约束；唯一例外=`humanizer-zh`
（第三方 MIT，随文件保留署名）。搬入三方代码/提示词前先过许可兼容检查；**运行时
依赖树不得引入 AGPL 组件**（PyMuPDF→pypdfium2 整体替换即此动因，见 decision-log）。

## 结构与分层（重要边界）

```
src-tauri/       Tauri 2 壳（Rust）：只做窗口、sidecar 进程管理、IPC command。零业务逻辑
frontend/        React 19 + Vite + Tailwind（shadcn 风格手写组件）；只通过 HTTP+SSE 与 sidecar 通信
sidecar/         Python sidecar（FastAPI + uvicorn），装配 DeepAgents
```

（产品官网已迁出本仓，独立工程维护；原 `website/` 静态页见 git 历史 6643b4f。）

三条铁律：

1. **Rust 不含任何业务逻辑。**
2. **API Key 存本地库**：模型/百度 OCR 的 Key 与全部模型配置存 `app.db` 的
   `app_settings` KV 表（明文落盘，威胁模型与 .env 等价），经 sidecar HTTP 写入
   （`PUT /settings/models` 全量覆盖〔前端唯一写者，可收 background_roles〕、
   `PUT /settings/keys` 模型 Key、`PUT /settings/ocr-keys` 百度 AK/SK），改动即时生效
   （agent 缓存重建，无重启）。**硬性质：GET /settings 永不回读 Key**——只回
   `key_configured` 布尔，Key 的 HTTP 载荷只写不读；env（`LLM_API_KEY`/`MODEL_KEYS`/
   `BAIDU_OCR_*`）只作兜底读取。模型配置真值四键（model_profiles/default_model/
   model_keys/baidu_ocr）；后台任务角色 `background_roles`（{extract, vision}，空=跟随
   缺省）；`GET /settings/test?model=<id>` 按模型 ping、`?role=ocr` 探百度凭证。
3. **前端只消费事件契约，不依赖 DeepAgents 内部格式**。现行事件全集：
   `agent.started / agent.token / agent.reasoning / agent.retry / agent.completed /
   agent.error / tool.called / tool.result / todo.updated / artifact.created /
   deliverable.created / run.state / run.interrupt / conversation.renamed / ping`。
   现行关键语义（每条的演变史见 decision-log「契约与运行时」章）：
   - 全部流事件带 per-run 单调 `seq`（前端去重+缺口检测）；SSE 发送层 100ms 微合批带
     `seq_from`（服务端合并跳号不算缺口）；`ping`/`run.state`/`conversation.renamed`
     是连接级推送无 seq。
   - `tool.called`/`tool.result` 带 `tool_call_id` 与 `agent_id`（非空=子代理内部事件）；
     `agent.reasoning` 文本键 `text` 且带 `agent_id`；`agent.retry` 带
     attempt/total/wait_seconds/scope(`main`|`sub`)（抖动后真值，前端活倒计时）。
   - `run.state` = SSE 建连对账事件（最新 run 真实状态 + `started_at` epoch ms，断线
     重连据此收敛）；`agent.error`/`run.state` error 分支恒带 `code`（值域
     `cancelled`/`interrupted`/`llm_unavailable`/`llm_auth`/`internal`；error 文案=
     首行人话 + `\n` + 原文截 300 字）。
   - HITL 与 run 生命周期端点：`POST /runs/{rid}/resume`（裁决续跑，多中断按
     interrupt_id 分组）、`POST /runs/{rid}/cancel`（running 协作取消 + waiting_input
     直接终态）、`POST /runs/{rid}/continue`（error 且 code 可续的 run 从 checkpoint
     断点续跑，前置探活预检）——详见 HITL 节。
   - `artifact.created` 类型化（kind/schema_id/schema_version/display_name）→ 前端
     Processor Registry；`deliverable.created` = run **正常完成时**的瞬时呈现信号
     （不落库不重放、只呈现最新一个交付物、用户手开的面板槽永不被抢）。
   - 过程与结果分通道：旁白/思考按 tool.called 封段进 run_traces 步骤树；messages 表
     **只存最终回复**（HITL 单回合聚合按 run_id）；GET /messages 的 assistant 消息带
     `traceSteps`/`tracePaused`/`durationMs`/`files` 轻量摘要，完整过程按需
     `GET /conversations/{cid}/messages/{mid}/trace`。
   - run 级 token 用量落 `runs.token_usage`（HITL 分段累计），按轮明细表
     `run_turn_usage`（scope=main/sub 归因）。
   - POST /messages 可带 `thinking`（low/medium/high，缺省 low，**无关闭项**）与
     `model`（未知 id 静默回落 default；runs 表存档，resume/continue 沿用）。
   - agent 装配不变量（详见 decision-log）：模型实例 `dict[profile_id]` 缓存（saver
     共享、rebuild 清缓存）；任务上下文块 run 内冻结（前缀缓存铁律，见代码约定）；
     LLM 并发经 per-profile AIMD 闸（`app/llm_throttle.py`：429 减半/超时 −1/连续成功
     回升、冷却窗 5s、流式许可持有到流结束）；上下文窗口四层取值（用户手选 >
     langchain 注册表 > models.dev 本地缓存 > 保守 17 万），压缩摘要调用输入上限
     200K，超限 400 归一化为 ContextOverflowError 自愈压缩重试；中间件内部调用
     （lc_internal_call 进程令牌）不外发为 token/reasoning 事件。
4. **设计铁则（用户明令）**：保持简洁；冲突处理用「探测 + 提示用户裁决 + 恢复点兜底」，
   **不加锁/互斥/租约/排队**等后台协调机制；锁只允许用户不可见的 plumbing
   （原子落盘、发布进程内写锁、fs_guard/docx_ops 的同文件写完整性锁）且需用户认可。

## 任务层与 Artifact 系统

- **业务模型**：任务 = 一次投标 = workspace 下一个真实项目文件夹
  （`workspace/<task_id>/{sources, work, _meta}`，目录名只用不可变 id）——`sources/`
  只读来源（上传原件，AI 物理写不进）；`work/` 工作树（parse/analysis/outline/body
  过程文件 + `artifacts/<aid>/` 登记产物包）；`_meta/` 产物级谱系/暂存（UI 永不展示，
  唯 `<task>/_meta/staging/` 豁免=两步发布流的模型草稿区）。会话必须归属任务；产物
  **包磁盘位置 = (artifact_id, task_id) 的纯函数**，会话只是 provenance。产物=**单一
  当前版本**：发布即当前内容，无状态机；重跑覆盖（覆盖前留恢复点 3 个；**整本
  tender.volume 明确不设恢复点**——派生交付物可由节文件重合册复原）。共享上下文 =
  任务名 + 进度便签 + 产物清单 + 任务工作目录（`_TaskContextMiddleware` 每次模型调用
  现算注入、**run 内冻结**），聊天记忆按会话隔离。仓库 workspace 根的 out/drafts/
  artifacts/ 是重构前遗留（无代码引用，化石无害）。
- **契约注册表封闭**：未登记类型一律收拢通用笔记 `doc.note/note-md@1`（发布工具强制
  文档形态 title+body_md），客户端 NoteProcessor 打开编辑。现行契约：`doc.note`、
  `tender.directory`（目录树，numbering 格式任务级）、`tender.volume`（整本 docx 文件
  型产物，`publish_file_artifact` 机械发布、册名身份键、zip CRC 内容级去重短路）。
- **发布与读取（单一真源）**：publish 归属 task_id 必填（只给 conversation_id 时反查
  所属任务）；`read_artifact` 同契约在任务内唯一当前内容，用户手改后的成果经它回流为
  后续 AI 输入（闭环点）。发布内容未变短路（JSON=序列化文本逐字节、文件型=zip 内容
  CRC）——未变不重发 artifact.created、运行态五列不动。索引重建（rebuild）保留幸存行
  运行态（content_seq/last_run_id 等），全量 DB 丢失才回落复位语义。
- **删除语义**：删会话 = 只清转录 + 索引（db 级联）+ agent.db checkpoint
  （`delete_thread_memory`），**不动任务文件树**；删任务 = 整任务目录 mv 到
  `workspace/archive/<task_id>/`（归档不删，可手工找回）+ 全部会话记忆清理；409 活跃
  run 守卫不变。
- **任务级来源文件区**：上传落 `<task>/sources/`（`POST/GET/DELETE /api/files` 均必填
  `task_id`）；前端上传上下文带当前任务，无任务时禁用并提示先选任务。上传白名单不按
  扩展名拒（类型可否解析由解析层报人话）。
- **sidecar 模块速览**（细节见各模块 docstring 与 decision-log）：`app/contracts/`
  （契约真值只在 sidecar）；`app/artifact_store.py`（路径派生 + tmp+rename 原子包存
  + 归档 + 恢复点）；`app/publish.py`（唯一登记入口：JSON 产物与文件型产物两条发布
  路径）；`app/api/`（tasks/workbench/templates/knowledge/materials/settings/files/
  runs/conversations/sse/artifacts）；`app/tools/`（LLM 工具族：publish/read/
  check_pipeline/validate_analysis/validate_body/search_knowledge/check_residue/
  docx_ops/web_fetch/templates 等，`tools/__init__.TOOLS` 注册）；`app/runctx.py`
  （contextvars：cid/rid/task_id/thinking/agent_scope）；`app/dispatch_enrich.py`
  （写手派发说明程序拼装）；`app/run_files.py`（「本轮文件」快照 diff）；
  `app/token_usage.py`（用量累计）；`app/deliverables.py`（呈现信号收集）；
  `app/llm_throttle.py`（AIMD 并发闸）；`app/model_registry.py`（models.dev 窗口缓存）；
  `app/model_ping.py`（探活）；`app/path_resolve.py`（路径解析收拢 + 
  `PATH_RESOLVER_REGISTRY` 声明式登记，守卫测试扫 TOOLS 参数名对账，新工具不接线当场
  红）；`app/checkpoint_prune.py`（agent.db 安全清理，原则 P0-P7 真值在模块头）；
  `app/titler.py`（会话自动命名）；`app/baidu_ocr.py`（云端文档解析）；
  `app/parse/`（pdfium 引擎套件：pdfium_kit/pdf_text/pdf_tables/pdf_pdfium）；
  `app/knowledge/`（ingest/types/roles/materials_lib/autocheck）。
- **agent 内部件速览**（挂载与动因见 decision-log）：`_SubagentCompassMiddleware`
  （子代理三行罗盘）+ `_PathRescueMiddleware`（文件工具路径事前换算；delete/execute
  不参与；主代理与两个 SUBAGENTS 双挂）；`_DispatchEnrichMiddleware`（派发拼装）；
  `_ReplayGuardMiddleware`（重派守卫：节名对账+节文件 mtime>run 起点+描述无意图词
  →拒并指路 check_pipeline_state，同 run 拒满 3 次放行）；`_TodoFreshnessMiddleware`
  （清单陈旧提醒 + after_model 门卫整批拒绝滞后派发，泄压阀 3）；`_ToolTimeoutMiddleware`
  （兜底制超时：重工具 600s、其余 120s、task 无硬上限、ask_human 不包、取消感知）；
  `_TaskContextMiddleware`（任务上下文注入）；fs_guard（读拒二进制图片/PDF/Office、
  写走全局单锁+原子写）；docx_ops `_PATH_LOCKS`（同路径写锁）+`_atomic_save`。
  `work/` 管线子目录预建：`_PROCESS_DIRS` = parse/analysis/outline/outline/fragments/
  body（任务创建 + run 启动自愈双入口，`ensure_task_skeleton` 幂等；新管线目录随技能
  落地同步加清单）。

### 投标流水线（现行打法）

- **document-parse**（文件→markdown，入口）：check_pipeline_state 对账候选/已确认/
  未纳入 → 同名双格式去重 ask → 来源集合确认 → 写 `work/parse/sources.json`（任务级
  共享状态；**变化检测锚=parse_document 幂等返回**：跳过=未变、重解析=重传过——不用
  时间戳，模型写的时间戳不可信）→ 并行 parse_document（同一消息全部调用；pdfium
  全局锁 C 层串行、Python/IO 重叠；主文件失败在概况门前拦停）→ 解析概况确认门
  （数字全部取自 parse_document 返回文案；全部跳过时不弹门）。
- **tender-analysis**（七节要点）：第 0 步前置检查走 check_pipeline_state（纯事实零
  结论）；每节 validate_analysis（锚定/文件名∈来源集合/L 行号≤原文总行数；提示不是
  门禁、收尾全绿）；**freshness 锚=文件 mtime vs 来源 meta.generated_at**（两端程序/
  OS 可靠侧）；导航硬纪律=先读 outline.json 按行号取区段、禁整读全文；出处引用键必
  带行号区间+档位署名；**收尾=摆要点停轮**（汇报关键要点+待澄清清单+提醒界面过目，
  不自动衔接目录、不用 ask_human——解析概况门/目录 R1 拆分门仍用）。产物不带模型写
  头（修订标记程序盖）。
- **tender-outline**（目录）：R1 响应文件分解确认（多方案 ask）→ R2 初稿 + 三道清理
  固定顺序（查漏补缺/评分对齐/走查定稿）→ assemble_tender 组装发布。单册主线程就地；
  多册并发派 `tender-outline-writer`（fragments/<册名>.md 按册序合并）。**树格式红线**
  （`- ` 开头/无编号/2 空格缩进/独立附件平级）是 assemble 的解析协议，test_skills 硬
  失败守卫。**封面=每册树首「封面」节点**（无样例时正文编写排版成形；字段值只从承诺
  清单、日期只写派发块今天日期）；**目录=前置区末尾「目录」节点**（合册机械生成，
  不写节文件；前置区不占章号）。
- **tender-body**（正文，docx 直出）：流程=check_pipeline_state `[body]` 段（待写节
  清单/已写节/新鲜度）→ 生成 `work/body/写作指引.md`（每节一行：节｜模式｜依据｜素材
  ｜缺口/备注）**摆要点停轮**（两道 ask_human 门已弃用）→ 用户给值后落 `关键事实与承诺
  .md`（事项｜值；承诺只出自清单）停轮收齐 → 逐节生成（一节一 .docx，写作与修订全走
  docx_ops 工具族）→ validate_body 节级自查 → 收尾待办批注逐条点名。断点续跑/中断后
  重新派发前重调 check_pipeline_state 对账已写节。
- **派发现行契约**（细节在 SKILL/section-writing，test_skills 锚定）：拆分粒度归模型
  自主规划（轻节 3~5 个捆一任务、单任务 ≤~5 节、**同消息并发派发防串行退化**、每消息
  ≤8 任务=并发上限、全覆盖自查）；description 首行=节名清单（顿号分隔、逐字抄待写节
  清单、禁前导语）、第二行起特殊意图；共享上下文由 `dispatch_enrich` 程序拼装（任务
  前缀/输出路径/指引行/素材块名片/承诺清单全部值/缺口透传/原件定位行/兄弟摘要/天级
  日期/方法论段——段在则写手不读、段缺自读一次）；**REQ/MAND/SCORE/TPL 编号禁止出现
  在派发说明与正文**（依据 ID 解析为要求原文+出处；正文呼应用招标真实条款号）。
- **素材契约（2026-09-15 定稿）**：两库内容都可改写、**同主题优先素材库**（知识库只补
  证书原图/时效核对/块未覆盖事实，防双吃）；**块=授权与检索单位非注入原子**——注入
  粒度 LLM 自选（整块或 `lines` 子区间，授权围栏=请求区间须完全落在块勾选范围）；
  「同一内容区间不得进两节」（节间查重防线）；docx 原件块优先 docx_material_inject
  元素级注入再定向修订。
- **检索现行纪律**：素材清单在=直接采用、不再 search_references；清单缺失/【缺】/
  已失效才自行检索（查漏出口）；已派块的节不允许「再搜搜看」。公司事实填空优先级=
  派发段【知识库】＞现场 search_company_assets＞批注待办。物理附件三分：缺口列有
  【知识库】命中（含图）→建节+docx_image_insert 逐张贴图；全无命中→**建壳节**（标题
  +一行贴入位+批注详述，废标级资格件绝不许只登记不建节）。临时参考件三铁律（只借
  写法不抄事实/冲突以招标为准/只改写不整拷、不进 block_ids）。检索挑选纪律在
  search_company_assets docstring（时间限定先换算、不契合宁缺、枚举措辞形态）。
- **写作工具与产物规则**：写手最小工具集 `_BODY_WRITER_TOOLS`（13 个，三重守卫测试）；
  禁改指引与承诺清单（共享写点只归主线程）；**缺料/待澄清/待核验唯一正规落点=Word
  批注**（docx_comment_add），正文禁止任何占位文字（validate_body docx 节占位=issue、
  合册内联占位兜底扫描 ⚠️）；独立图片唯一通道=docx_image_insert（含图块必须注入、
  禁止跳过注入自写、修订不删〔图×N〕段；宽度程序定死全宽）；表格/图示走 md 块混排
  +docx_html_figure/mermaid（流程图 18cm 封顶防占页）；**章节编号=树位置的纯函数在
  合册生成**（chapter/decimal/gov/none 任务级存目录产物；格式件与正文统一编号；节内
  小标题不自动编号；建节 title 用裸名、自带编号形态探测 ⚠️）。
- **版式现行规则**：用户可见层叫**版式库**（=纯版式资产；代码标识符 /templates/
  docx_template/list_templates 不改名，「模板填充」模式词沿用指招标方待填件）；基准
  模板 `app/resources/tender_base_template.docx`（make_base_template.py 生成维护，改
  版式=改脚本重跑；Tender Body/Tender Cover/TOC 样式族；*Theme 引用三层防线）；拷贝
  模板策略（无样式素材正文段挂 Tender Body、带样式段/表格/direct 格式不动、招标件
  零改动全保真）；模板现状用 list_templates 查、不用文件工具检索；默认版式位=
  app_settings `docx_template`，改版式即时生效无重启、**只影响之后新建的节**。
- **整本=交付态**：合册接受全部修订 + 摘树外标题 outlineLvl + **节内小标题按树深度
  降级并程序编号**（2026-09-16：目标级=clamp(树深+源级−1,2,9)，深度 2 节下 H2→H3 式
  ——治裸 H2 与真节标题同级平铺；H3/H4 按节内出现顺序接续节号拼进文本（5.1.1 式，
  gov 接 1./（1））；深度 1 章叶/none 格式/H5+/文字自带编号形态不编；前置区/格式件章/
  封面不降不编，节文件不动）+ 目录页机械生成（Word
  目录域+缓存清单）+ 空容器抑制 + 批注随节迁移（「含批注 N 条待处理」）；每册落盘后
  `docx_assemble_volume` 机械发布 `tender.volume`（工作台有 volume 产物时整本文件行
  隐藏）；**语言纪律**：humanizer-zh 裁剪 7 条进 section-writing.md（作用域只管模型
  自生成文字，素材底稿/招标格式件保真不润——重写素材会掉使用率校验）。
- **样式/编号迁移卫生**（乱号事故防线）：`_merge_missing_styles` 按 styleId+样式名双维
  去重、迁入多级编号解析到目标内建标题/Normal 的绑定一律剥除、**迁入标题样式的
  numPr 剥除**（2026-09-16「素材自有编号保真」收窄为版式与内容、编号标题不保真）、
  `_strip_copy_residue` 剥拷入段直挂 outlineLvl 与死书签、标题类段落直挂 numPr
  （判据 `_style_is_heading_like`=样式名 heading/标题 或带 outlineLvl）——素材/
  招标件拷贝与合册三循环同接；正文列表编号保真不动。

### 前端架构现状

- `src/artifacts/registry.ts`（kind/schema@version → Processor 注册表 + 启动契约对账）；
  `components/processors/`（DirectoryProcessor 目录树编辑 / NoteProcessor 通用笔记 /
  VolumeProcessor 整本只读统计）；`components/ArtifactOpenHost.tsx`（未命中契约明确报
  不支持，**无 JSON 兜底预览**）。
- `components/HomeView.tsx`（任务首页）：**任务即房间**——会话只从任务内诞生、无草稿
  态、冷启动落首页不自动进会话；建任务=「开始新投标」卡内命名或**拖招标文件=以文件名
  直接建任务**；侧栏「新建任务」=导航首页（不弹窗）。
- 产物面板 v5：任务归属 + 单一当前版本 + 业务流任务树（产物按 kind 归业务夹、正文组
  volume 置顶、工作台 .md/.docx 与产物同夹）；行级右键菜单（打开/打开文件夹/复制路径
  /md 另存/恢复上一版）；`work/` 过程文件经 WorkbenchViewer 查看/编辑。
- docx/pdf 版式预览：纯浏览器本地渲染（文件不出本机）；docx-preview=接受视角、pdf.js
  必须 cMapUrl+standardFontDataUrl（`public/pdfjs/`）；写作指引/承诺清单按文件名分发
  GuideFileView（左树右详情）/PromiseFileView（文件仍是唯一真值、界面只是另一个编辑
  器；跨语言契约锁金样例双侧同源）。
- `lib/wbNames.ts` 的 `wbDisplayName` 是三处显示名唯一真值（path 恒为寻址真值）；
  **产物栏不设最大宽度**（用户明令，拖动上限仅窗口宽−360）。
- FileUpload 带任务 scope（taskScope/setTaskScope），文件 chips 只显示当前任务的文件、
  无任务禁传。
- **UI 风格统一纪律（用户明令）**：新增组件一律语义 token，禁 Tailwind 调色板类与硬
  编码色值；来源徽章四色=MAND danger/TPL info/REQ brand/SCORE warning + color-mix
  12% tint 派生。
- **并发/冲突**：无租约无互斥——任务内 run 随便并发；发布即覆盖（覆盖前留恢复点，
  `POST /artifacts/{id}/restore` 可恢复且可再撤销）；`content_seq` 是探测器不是锁
  （三编辑表面统一 useAutoSave 5s 轻量探测，外部更新无本地改动静默跟随、有则弹
  「拉取最新 / 保留我的=force 覆盖」）。
- **新契约接入**按设计文档 §13 五步打包：契约定义→SKILL.md 指导→客户端 Processor→
  模板集合→全链路验收；禁止半接入（客户端启动对账会 console.warn）。
- **已知限制**：任务模板未引入（授权 stub 全允许）；产物编辑不发 SSE（不在 run 内无
  seq 宿主），前端操作后自行刷新产物列表。

## HITL（human-in-the-loop）

- 用 deepagents 原生 `interrupt_on`（`agent.INTERRUPT_ON`，当前一项：`ask_human`
  `allowed_decisions=["respond"]` 问答型。task 派发审批门禁已删——恢复加回
  `"task": {"allowed_decisions": ["approve", "reject"]}` 即可）。子代理 spec 的
  interrupt_on 是整体替换继承——tender-outline-writer 传 `{}` 即排除。
- **暂停语义**：interrupt 发生在 after_model（节点内），**之前不会发 tool.called**；
  捕获后落半截回复（带标记）→ `db.interrupt_run` 置 `waiting_input` 存 requests 快照
  与 last_seq → 发 `run.interrupt`；被拦下的 running 步骤由 `_freeze_paused_steps`
  改标 paused 终态。多中断全合并（每条附 interrupt_id，resume 按分组组装映射）。
- **续跑**：`POST /api/runs/{rid}/resume`（decisions: approve/reject+message/respond/
  edit；决策数须与快照一致）；respond 同步落 user message；续段从 checkpoint 续跑
  同一 run、重发 agent.started，**seq 从 last_seq+1 续接**。续跑段 trace 从既有行
  deepcopy 承接步骤树（HITL 代答 tool.result 回填依赖此）。HITL resume 沿用首段
  thinking/model 档位。
- **cancel**：running=置位协作取消事件（下一流事件边界退出，长工具等返回）；
  waiting_input=直接 `db.cancel_waiting_run` 条件 UPDATE 抢占（无活 worker，与 resume
  并发一对一必有一赢、输家 409）→ retire_pause_marker → agent.error(code=cancelled)。
  checkpoint 不清（langgraph 自愈悬空 tool_calls）。
- **continue**：error 终态且 error_code ∈ RESUMABLE（interrupted/llm_unavailable/
  llm_auth；cancelled/internal 不提供）→ 无新输入从 checkpoint 断点续跑；前置链=
  非会话最新 run 409 → checkpoint_exists 预检 → `_preflight_ping(run.model)` 探活
  （无 Key/不可用 409 人话）→ db.continue_run 条件 UPDATE 抢占。
- runs 表 CHECK 加状态不能 ALTER——`db.init_db` 启动时探测 `sqlite_master` 整表重建。
  `recover_stale_runs` 只翻 running（waiting_input 的 interrupt 活在 checkpoint，重启后
  仍可 resume）；`active_run_exists` 视 waiting_input 为占用（发消息 409 提示先处理）。
- **前端**：`InterruptCard` 按 allowed 分支（respond-only=问答向导卡、否则审批卡）；
  **提问卡原位替换输入框**（waiting 期间占输入框槽位、上传钮+chips 在卡下、提交/放弃
  后回归）；一张活卡贯穿 run 生命周期（暂停冻结不换卡、批准/回答后同实例解冻）。
  ask_human 参数泄漏由 events 读写下场自愈（`_salvage_ask_human_args` +
  `normalize_hitl_requests`，参数已有值不碰）。
- **退出拦截**：running 态关窗/cmd+Q 先弹确认（`/runs/active` 只数 running；
  waiting_input 暂停存 checkpoint 退出无害不打扰）。

## 知识库与写作素材库

跨任务共享资料层，两个彻底分离的域：**知识库（事实层）**——公司有什么/做过什么
（资质证书、合同案例、人员证书、财报、业绩、公司介绍），LLM 轻抽取+事实纪律；
**写作素材库（素材层）**——用户从历史标书/范文里**手工勾选**的章节块+备注，零 LLM
裁定（块的价值判断归用户，程序只做机械；素材自动拆分 decompose 已废，用户明令）。

- **知识库管线**（`knowledge/ingest.py`）：上传 → 解析（数字版本地；扫描件/.doc 已配
  百度 OCR 路由云端、未配降级仅存档）→ 切段即 searchable → 三合一抽取（类型+锚点+
  内容说明）→ 图片抽取（确定性零 LLM，仅供内容页核实红章）。能力状态机
  stored→searchable→typed→enriched 派生不落库，失败逐层降级不阻塞。
- **检索问题 questions**：抽取同批生成 3–6 个「用户会怎么问」短问句（归类词必须与
  文中内容真实对应——防编造的唯一防线；写法类不生成），独立 §questions 检索段；PUT
  /metadata 可选收 questions；已确认条目的采纳走「对比采纳」交互（各区独立采纳/
  保留，确认不被静默覆盖）。
- **锚点回文核对+自动确认（两主人模型）**：机器守 suggested——`knowledge/autocheck.py`
  纯函数核对（身份锚点归一化回文命中/时间四格式/period/valid_until 一致性/事实类
  time_fields 非空却零时间锚点=可疑），全过自动确认（business 带 confirmed_by:auto）、
  有败留 pending_review 点名原因；人守 business——人工确认过重抽永不覆盖；启动回扫
  autocheck_sweep 清存量欠账。
- **类型注册表**（12 类，role=fact/writing）：机器消费锚点字段=时间四字段+
  project_name/client；**角色派生**三档（fact 类=fact-verified；写法类章节标题命中
  业绩词表=fact-candidate；其余=writing-reference）。
- **素材库**：自己的文件区（materials/files/）+ 解析产物（md/outline.json/blocks.json；
  docx 另产 **element_map.json**=元素级注入映射真值，**版本护栏 ≥2**）；上传收口为
  **仅 .docx ≤100MB**；重解析收尾同步块索引/检索段并探测行号漂移（reparse 端点+
  失败重试）；用户目录树勾选区间建块（多区间+备注；行号夹紧/嵌套去重叠归程序）；
  **块 id 只在 blocks.json 生命周期内稳定**（删块=引用失效）；引用打点
  use_count/last_used_at。图片可见性：块级含图数=区间内 `![](图片)` 占位行计数，
  检索命中标「含图 N 处」。
- **双检索工具**（`tools/search_knowledge.py`）：`search_company_assets`（问事实：全库
  召回，verified 排前/candidate 附标、项目名匹配关联证明材料；纪律=拟投入承诺不是
  现状事实、数字一律重核、过期证书不得写有效）；`search_references`（问写法/拷贝：
  查素材库块，命中文件的块全景骨架附后；docx 原件块优先注入再修订；范文警示常驻）。
  统一命中头（角色｜类型｜状态｜时效）+ evidence key + [evidence] JSON 行（validator
  消费格式已冻结）。
- **`tools/check_residue.py`**（check_name_residue）：拷贝修订第一道防线——来源条目
  project_name/client/文件名主干自动入扫描表+显式名单，机械扫残留（提交稿残留旧机构
  名=行业第一大事故）。
- **API**：`api/knowledge.py`（types/badge/上传/items/内容/raw/图片/metadata/retrigger/
  delete）+ `api/materials.py`（files 上传/列表/删除/outline/reparse/blocks CRUD+content
  区间预览 `?start&end`）。
- **agent 注入**：`_kb_summary_line` 双域口径；主 prompt 资料词汇表+无机制纪律（三库
  词汇定义；不存在「把版式应用到整本/已写章节」的工具、被要求时如实说明+给可行做法、
  禁把素材库文件当版式候选；用户请求没有的能力时如实说明不发明路径——守卫=
  test_agent 源码关键词断言）。
- **检索技术**：FTS5 jieba+bigram 同源分词、无向量；语义层=agent 迭代查询。
- **有意不做**：任务成果自动回流、版本替换机制（删旧传新）、向量检索（视召回评估）、
  素材块级编辑、素材自动拆分。

## 命令

- `npm run dev`（= `npx tauri dev`）：一条命令（Tauri 拉起 sidecar + Vite + 窗口）。
- `./dev.sh`（= `npm run dev:menu`）：交互式启动器，菜单或 `./dev.sh <mode>` 直接指定；
  模式 = `tauri` / `browser`（sidecar+Vite 一体，推荐）/ `sidecar`（只起 8765 前台日志）/
  `frontend`（只起 Vite）/ `preview`（只起 Vite 并打开 /preview.html）/ `stop`（停 8765/5173）。
  端口被占时**自动 kill 占用进程后启动**（8765/5173 是脚本专属开发端口）；`tauri` 启动前会腾干净
  两个端口避免残留 sidecar。别同时跑 Tauri 与浏览器模式（共用 agent.db 会 checkpoint 崩溃）。
- `npm run dev:browser`：浏览器模式一条命令（concurrently 拉起 sidecar[8765] + frontend；
  前端经 Vite dev proxy 同源访问 `/api`，无 CORS）。
- 纯 sidecar：`cd sidecar && uv sync && uv run --env-file .env python -m app.main --port 8765`。
- 前端：`cd frontend && npm run lint`（oxlint，配置在 `.oxlintrc.json`）、`npm run typecheck`
  （`tsc -b`，tsconfig 已开 strict）、`npm run build`（含类型检查）。
- `./check.sh`：一键全栈检查（sidecar=ruff+pytest / frontend=oxlint+tsc+vitest+build /
  rust=cargo check+clippy `-D warnings`；可 `./check.sh sidecar|frontend|rust` 单跑）。
  Python lint = `uv run ruff check app tests`（select 默认+isort；formatter 暂未启用）。
- sidecar 日志双写：stderr 控制台 + `data/logs/sidecar.log`（滚动 5MB×3）；Tauri 模式下
  stdio 被置 null，查后端问题直接看该文件（Rust 侧日志在 `~/Library/Logs/<bundle-id>/`）。
- 未配置任何模型 Key 时 sidecar 仍可起，但选用该模型对话会报「未配置 API Key」（设置页录入即用）。
- 浏览器模式（`npm run dev:browser`，前端经 proxy 访问的）8765 sidecar 用的是
  `sidecar/.env` 里的 `LLM_API_KEY`——它可能是占位/无效 key（会报 401 invalid key），真实 key
  只在 Tauri 模式由 Rust 从钥匙串注入。浏览器模式要跑真实对话，需在 `.env` 里配有效 key。
- sidecar 有 pytest（`uv run pytest`，覆盖 db 恢复 / 设置校验（含双角色）/ 工具路径 containment /
  契约校验 / 发布管线 / 编辑保存与恢复点 / 知识库（入库/检索/元数据/解析注册表，
  `test_knowledge_*.py`）/ **§5.5 事件契约 schema**（`test_contract.py`，
  字段清单须与前端 `api/sse.ts` 的 AgentEventData 人工同步））；单文件聚焦跑
  `uv run pytest tests/test_docx_ops.py -q`。frontend 测试 = vitest（`cd frontend && npm run test`，
  单文件 `npx vitest run src/lib/workbenchTable.test.ts`；覆盖 runReducer/workbenchTable/
  guideBasis/guideTree/wbNames/toolDisplay 等纯函数与 reducer）。Rust 单测少而存在
  （sidecar.rs 尾部 `#[cfg(test)]`，`cd src-tauri && cargo test`；check.sh 只跑
  check+clippy 不含 test）。
- e2e 冒烟：`cd sidecar && uv run pytest -m e2e`——spawn 真实 sidecar 子进程（独立端口 +
  隔离 DATA_DIR）跑一轮真实 LLM 对话，断言 run 完成、SSE seq 单调无重复、tool_call_id
  唯一、messages/trace 落库。需要 `.env` 有效 key（无则 skip）。日常 `uv run pytest` 默认
  排除 e2e（保持秒级）；**动 events/agent/bus/SSE 相关代码后应跑一次 e2e**。

## 代码约定

- **sidecar**（Python ≥3.12，uv 管理）：
  - `app/events.py` 是 LangGraph 流 → §5.5 事件的**唯一适配层**；库 API 变化只改这里。
    updates 只翻译真实执行节点：tool.called/tool.result 只从 node∈{model, tools} 的更新
    产出，中间件伪节点（状态重写不是新工作）天然跳过——跨 run 重放守卫，沿革与实测形态
    见 decision-log「契约与运行时」章。
  - SSE 事件 data 必须合法 JSON：在 `app/api/sse.py` 里 `json.dumps(data, ensure_ascii=False)`，
    因为 sse-starlette 对 dict data 会输出 Python repr（单引号，非法 JSON）。
  - agent 运行在 `asyncio.to_thread` 的 worker 线程，逐事件用 `run_coroutine_threadsafe`
    实时发布（否则 token/tool 事件会在 run 结束后一次性爆发，前端无流式）。
  - `SqliteSaver.from_conn_string` 在新版是上下文管理器；sidecar 常驻需自持连接：
    `sqlite3.connect(agent_db_path, check_same_thread=False)` + `SqliteSaver(conn)`；
    该连接进程存活期**只开一条、永不关闭**（rebuild 只换 agent 对象复用同一 conn/saver），
    否则运行中 PUT /settings 会让正在跑的旧流 checkpoint 崩溃。
  - 新增工具：在 `app/tools/` 里 `@tool` + zod（或 docstring schema），并加入 `tools/__init__.TOOLS`；
  - **工具/子代理失败纪律（2026-09-07）**：工具抛异常会打死整个 run（langgraph 工具节点
    对非参数校验异常一律 re-raise）——自家工具失败必须返回「[xxx失败] …」错误字符串；
    deepagents 内置 task（子代理派发）不守此纪律，经
    `ToolErrorMiddleware(on_error=_task_failure_content, tools=["task"])` 收敛：瞬时错误
    返回 None 上抛走 checkpoint 断点重试，其余转错误字符串回模型自裁决重派。瞬时分类器
    `_is_llm_transient`：网关流内错误事件=openai SDK 抛**裸基类 `APIError`**（openai
    `_streaming.py` 对流中 `{"error":…}` 无论带不带 code 都构造裸基类；类型化子类只在
    建连前非 2xx 路径产生，401/400/404 全是子类），精确类型 `type(exc) is APIError`
    判瞬时；断流关键词兜底；重试预算 3 次（3s/10s/30s，等待期响应停止）。
  - **前缀缓存铁律**：进 system/请求前缀的任何内容必须整个 run 内字节稳定——每次调用
    现算的易变项（时间戳/便签/产物清单）一律 run 冻结（`_task_context_block_frozen` 先例）
    或挪请求末尾；模型供应商前缀缓存按字节前缀匹配，断点之后全部按未命中全价计费
    （DeepSeek 命中价约 1/10-1/30）。新加「每次模型调用注入 XXX」类功能前先过这道检查。
  - **Artifact 存储内容是原始 dict 序列化——Pydantic 校验只验证、不物化默认值**，
    合法内容的 `directory/children/name` 键仍可能缺失，前端 Processor 必须防御性解析（`?? []`）。
  - 工具输入路径必须落在 workspace 内（做 containment 校验），
    防止文档内容注入诱导模型读取工作区外敏感文件。
  - 启动时把崩溃残留的 `running` run 标记为 error（`db.recover_stale_runs`），
    否则 sidecar 被杀自动重启后该会话会永久 409 死锁。
  - 双库恢复语义：agent.db checkpoint 是 LLM 记忆真值，messages 表是恢复源——
    启动时 `agent.recover_agent_memory` 对账（有消息但 thread 无 checkpoint 的会话用
    messages 历史重建，防 agent.db 丢失/损坏后失忆）；删会话经 `agent.delete_thread_memory`
    连带清 checkpoint；run 中断时已流出的半截回复落库（带「（任务中断）」标记）。
    messages 查询排序用 `created_at, rowid` 决胜（created_at 秒级精度，同秒消息按
    随机 uuid 排序会乱序）。
  - 模型配置与凭证（2026-08-29 定稿，铁则 2）：真值= `app.db` 的 `app_settings` KV 表
    （model_profiles/default_model/model_keys/baidu_ocr 四键，JSON 值）；读侧优先级
    env 兜底（LLM_API_KEY→default、MODEL_KEYS、BAIDU_OCR_*、LLM_BASE_URL/LLM_MODEL
    覆盖 default profile）> db > 内置默认；旧 settings.json（双角色/扁平/列表形状）
    在 db 为空且文件有内容时一次性导入。`app/api/settings.py` GET/PUT + keys 端点
    （**Key 只写不读**，GET 只回 key_configured 布尔）；改动即时生效（清 agent 缓存
    惰性重建，无重启）。Tauri 侧零参与（无设置类 IPC command）。
  - skills 从 `app/skills/` 启动时同步到 `data/workspace/skills/`（FilesystemBackend root）。
- **src-tauri**（Rust stable ≥1.85）：
  - `src/sidecar.rs`：选空闲端口 → 随机 token → spawn（`process_group(0)`）→ healthz(nonce 校验,1s×30) →
    指数退避重启（上限 3 次）→ 退出杀进程树并 wait 回收。**崩溃韧性六件套（2026-09-05）**：
    ①稳定窗口=探活成功后存活满 30s 才清失败计数（防「活 N 秒必崩」型起-崩永久循环，Docker
    成功窗口先例）；②spawn 失败与探活失败/意外退出同样计入熔断上限（此前 spawn Err 无限 2s
    重试）；③`restart_sidecar` command=手动重启入口（清零熔断计数+置 restart_requested，
    supervisor 存活监控/熔断等待两处消费；探活成功时主动消费积压请求防误杀健康进程）；
    ④失败分类 `FailureInfo{kind,detail}`（spawn_failed/boot_timeout/crashed/exited，
    classify_exit_status 纯函数+单测；wait status 编码：信号态=信号号本身、退出码才是 code<<8）
    经 `get_sidecar_failure` 透出前端红态横幅（`lib/sidecarFailure.ts` kind→人话标题+单测）；
    ⑤stderr 留档 `data/logs/sidecar-boot.log`（每次 spawn 截断重写，捕捉 Python 日志初始化前的
    启动早期错误；创建失败回退 null 不阻断拉起）；⑥`export_diagnostics` 导出单个 txt 诊断报告
    （版本/OS/失败原因+Rust 壳日志尾部+sidecar.log 尾部+boot 留档，零新依赖，尾部自附隐私提示）
    + `reveal_sidecar_logs` 打开日志目录（前端拿不到绝对路径，Rust 侧直接 reveal）。
    `get_sidecar_info` 在 Failed 且无重启请求时快速返回 Err（熔断后 info=None，否则前端每个
    请求挂满 20s 才报错）。env 只注入 plumbing
    （SIDECAR_TOKEN + TENDER_HEALTHZ_NONCE）——模型配置与凭证 2026-08-29 起在 sidecar
    的 app.db，钥匙串/MODEL_KEYS 注入/设置类 command（set_model_key 等）已全部移除；
    `stopping` 标志保证应用退出后 supervisor 不再拉起孤儿进程。
  - 打包分发（现行约束速览；实施过程与坑的沿革见 decision-log「打包、平台与依赖」章
    与 docs/packaging.md）：PyInstaller one-file 冻结 sidecar → `bundle.externalBin`
    （`binaries/tender-agent-sidecar`，产物带 `-$TARGET_TRIPLE` 后缀）→ tauri-plugin-shell
    `app.shell().sidecar()` 拉起（capabilities `shell:allow-spawn`）。sidecar.rs 启动
    **双模式探测**：`sidecar_dir()` 下有 pyproject.toml=dev（走 `.venv/bin/python`，
    `npm run dev` 零变化），否则 bundled（`DATA_DIR=app_data_dir` env 注入——one-file 下
    Python `__file__` 在 `_MEIPASS`，不注入数据全丢；RESOLVED_DATA_DIR OnceLock 供
    诊断/reveal 前缀校验同源）；supervisor（healthz nonce/退避/熔断/稳定窗口）全保留，
    句柄双形态化（bundled=CommandChild 无 wait，stderr 转发线程消费通道置终态；杀进程
    SIGTERM→轮询→按端口清孤儿→SIGKILL，Windows=taskkill /T /F）。
    打包三件套在 sidecar/：`run_frozen.py` 冻结入口（`--smoke` 自检十项：pypdfium2(native)/
    jieba/FTS5/trafilatura/python-docx 模板/基准版式模板〔app/resources——唯一「漏收集
    不崩溃、只静默退化英文默认版式」的 datas 项〕/openai 懒资源/agent 栈/server 栈/
    app.main）、`tender-agent-sidecar.spec`（datas 收 `app/skills/**` 与
    `app/resources/**`；collect_data trafilatura+justext；collect_submodules 保底
    deepagents/langchain 全家；**upx=False 硬性**——UPX 压缩产物过不了 codesign）、
    `build_sidecar.sh`（**独立 .build-venv**=uv 管 python-build-standalone 3.12，绝不用
    日常 .venv——miniforge 软链用户机必炸；锁版 pyinstaller==6.14.1；`--target <triple>`
    跨架构（uv 装对应架构托管 CPython，venv 落 `.build-venv-<arch>`，跨 OS 目标直接拒绝
    指路 docs/packaging.md）；构建尾部自动跑 `--smoke` 冒烟门（目标 OS=本机时）；
    产物落 `src-tauri/binaries/`（gitignore））。
    **bash 3.2 兼容铁则**：macOS `/bin/bash` 恒为 3.2（GPLv3 冻结）——`$(case ...)` 内嵌
    case 解析不了、`$VAR全角标点` 变量名会并入多字节字符（须 `${VAR}`）。
    `npm run build:sidecar` / `build:release`（先 sidecar 后 tauri build，有意不塞
    beforeBuildCommand）。冒烟基线：89MB 二进制、冷启至 healthy 11-14s（bundled 探活
    窗口放宽 60s）。已知坑备案：Windows NSIS 覆盖安装不更新 externalBin（tauri#15134，
    靠版本号变化规避）；未签名 one-file 杀软误报偏高（Developer ID 签名+公证缓解）；
    macOS universal=两个 triple 产物放 binaries/ + `tauri build --target
    universal-apple-darwin`（x86_64 半边可在 arm 机 Rosetta 构建）；Linux /tmp noexec
    需 `--runtime-tmpdir`。签名/公证/CI/自动更新器=后续门未做。
  - 已装插件仅三枚官方 plumbing：`tauri-plugin-single-instance`（须第一个注册——GUI 双开会撞
    agent.db 单库 checkpoint，二次启动聚焦已有窗口，不做互斥协调）+ `tauri-plugin-window-state`
    （记住窗口大小/位置）+ `tauri-plugin-shell`（2026-09-07 打包分发：bundled 模式经
    `app.shell().sidecar()` 拉起冻结 sidecar，见上条）；均纯 Rust 侧使用、前端零依赖。
- **frontend**：sidecar 地址解析在 `src/api/client.ts` 的 `getSidecarInfo()`——
  Tauri 环境走 `__TAURI_INTERNALS__.invoke('get_sidecar_info')`；浏览器开发模式默认返回
  相对路径（`/api/...`），由 `vite.config.ts` 的 `server.proxy` 同源转发到 8765——CORS
  整类问题被消除，SSE 也能透传；需直连时用 `VITE_SIDECAR_URL`/`VITE_SIDECAR_TOKEN` 覆盖。
  `vite.config.ts` 固定 `port: 5173 + strictPort`，端口被占宁可启动失败也不回退（回退会让
   CORS/地址失配静默失败）。SSE 用 `@microsoft/fetch-event-source`。
  - **SSE 全局单槽（2026-08-29）**：`api/sse.ts` 的 subscribeSSE 任意时刻只允许一条订阅
    （新订阅先 abort 旧的，跨会话同理）。这是浏览器「每域名 6 条并发连接」预算的结构性
    防线——SSE 是长连接，abort 经 Vite 代理后上游侧可能残留半开连接；并发多条会挤爆预算，
    后续普通请求（messages 等）永久排队饿死，表现为「点开会话骨架屏永不消失」。
    不要改回按会话多订阅并存。配套：`hooks/useMessages.ts` 用 retry:1 +
    refetchOnWindowFocus（快速进入可见错误态 + 页面隐藏恢复自愈）；ChatView 对 messages
    查询接 isError 渲染 ErrorCard+重试，empty 条件排除 isError（失败不得伪装成欢迎页空会话）。
  - **流式渲染性能三件套（2026-08-30）**：聊天流式表面（RunMessage 正文/DeepThinking/
    SubagentCard 思考/AssistantMessage 正文）一律走 `components/ai/MemoMarkdown`（按顶层
    mdast 节点分块 + 块级 memo，解析器与 react-markdown 同源；新增流式 markdown 位置禁止
    裸 ReactMarkdown，静态一次性内容如 processor/查看器不受限），流式文本进渲染前套
    `hooks/useThrottledValue`（state 存精确值、只节流渲染层），贴底滚动走 rAF 合并。
    memo 白名单制：`ChatMessage`/`RunTrace`/`SubagentCard`/`MessageList` 的比较器/引用
    稳定性依赖 props 全部为值或稳定引用，**新增 prop 必须同步进比较器**（漏了 = UI 不更新）。
  - **连续 grep 批次折叠组（2026-09-06）**：RunTrace 显示层把相邻 grep（废标反查词表
    20 连发）收进 `GrepBatch` 折叠组——「检索 ×N · 命中 H/N」组头 + 词表 chips 折叠态
    常驻（命中正常色/未命中置灰；命中判定=done 且 summary 非空且 ≠ deepagents
    'No matches found' 固定文案，提示非门禁）；**旁白/思考非空 = 新轮首个调用即断组**
    （组数诚实对应模型轮次、旁白常驻组头不被折叠吞掉）；≥2 才成组、单个（自扩词反查）
    维持普通步骤行；展开后逐个渲染 `ToolStepRow`（参数+结果原样可审计，组首行
    `embedded` 抑制已上提组头的旁白/思考）。分段纯函数 `traceGroups.ts` + vitest；
    数据/SSE 契约/runReducer 零改动，活跑与历史 trace 同构生效（勿扩到 read_file——
    逐章推进感有信息量；子代理 ChildStep 未接）。
  - UI 全手写、**零 radix/cva**：`components/ui/` 是 shadcn 风格基础件
    （button/dialog/input/collapsible/hover-card），`collapsible.tsx` 支持透传 data-*。
    `components/ai/` 是从 prompt-kit 移植的 AI 组件（Loader/TextShimmer/PromptSuggestion/
    Reasoning/ChainOfThought/Steps/Source/FileUpload/ThinkingBar/Tool），全部手抄适配、
    零第三方依赖，动画 keyframes 集中在 `styles/ai.css`。吸收新 prompt-kit 组件照此先例：
    抄源码思路适配到语义 token，不引 radix/cva/motion（详见记忆 prompt-kit-visual-adoption）。
  - 设计 token：真值 = `src/styles/tokens.css`（vendor 自 `docs/designtokens/`，v1.2 五集合
    `--Color-*/--Spacing-*/--Radius-*/--Typography-*/--Shadow-*`，Light + Dark 双 mode：暗色由
    `[data-theme="Dark"]` 变量翻转自动生效，开关在侧栏 UserBar、偏好存 `tender-agent.theme`，
    首帧由 main.tsx 落位防闪白）；`index.css` 只做 Tailwind `@theme inline` 工具映射（工具类名
    沿用 text-ink/border-line/bg-muted 等历史名，指针直连 --Color-*），`styles/workspace.css`
    是 Workspace 组件设计系统、只消费 token 不定义色值；状态 tint 用 color-mix(语义色, bg-canvas)
    现场派生、不硬编码浅色；UI 改动优先用语义变量，找不到 token = 加 token。
  - `preview.html`（→ `src/preview/`）是独立组件预览入口：只引 workspace.css，
    不引 index.css/Tailwind/后端；验证纯 UI 组件时用它，别在预览页引 Tailwind 工具类。

## 已知事项

- **浏览器模式下改 sidecar Python 代码不热载**：Vite HMR 只覆盖前端；改完 Python 必须
  `./dev.sh stop` 后重启 browser 模式才跑新代码（前端访问的 8765 是旧进程时会表现为
  「接口 404 / 行为没变」）。
- **浏览器模式的 Vite 只绑 IPv6 `[::1]`**：工具或浏览器连 `http://localhost:5173/` 超时
  时改用 `http://[::1]:5173/`（macOS 上 localhost 可能解析到 127.0.0.1，那里没人监听）。
- **uvicorn access log 在响应结束时才写**：SSE 活连接不写日志，日志里的 `GET /events 200`
  表示该连接已关闭；「events → runs/latest → messages×2」三连 = 前端 SSE 断开后 onError
  对账重连（页面不可见时 fetch-event-source 默认主动断开、恢复可见才重连，靠 run.state
  对账收敛）。排查连接问题用 `lsof -nP -iTCP:8765 | grep -c ESTABLISHED` 数连接。
- 网络镜像必配：pypi=清华（pyproject 内置）、npm=npmmirror（.npmrc）、cargo=rsproxy
  （`src-tauri/.cargo/config.toml`）、rustup=`RUSTUP_DIST_SERVER=https://rsproxy.cn`。
- DeepAgents 锁 0.7.7（`deepagents==0.7.7`）；langgraph 由依赖解析（当前 1.0.5）。
- uvicorn 不要开 `--reload`（Tauri 进程树管理会乱）。
- 解析支持 `.docx`（python-docx）与 `.pdf`（pypdfium2 引擎，无 soffice 依赖）；
  扫描 PDF（文本层过薄）与 `.doc`/图片在**已配置百度云文档解析**时路由云端整本 OCR
  （`app/baidu_ocr.py`，conversion=`paddleocr-vl`），未配置明确拒绝并提示设置入口
  （`.doc` 另可 Word 另存 `.docx` 后上传）。
- **409 发送失败错误卡滞留（2026-09-10 已诊断未修复）**：run 运行中 POST /messages
  撞防并发守卫 409 → useRun dispatch send-failed 只写 error 不碰 running/tools；
  随后对账快照恢复活卡时红卡不清，「错误卡+运行中活卡」并存挂到 run 结束
  （清除锚只有 started/settle-completed/run.state(running) 三路，纯执行期流事件
  不触碰 error）。runReducer.test.ts 六例**特征测试**实锚现状（断言标「缺陷
  实锚」，修复落地后对应断言应翻转）；修复方案待用户拍板——改此区域前先看
  该 describe 块的时序注释。
