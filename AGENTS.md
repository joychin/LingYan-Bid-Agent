# AGENTS.md

本仓库是 Tender Agent（智能标书 Agent 桌面客户端，local-first）的 monorepo。
给在本仓库工作的 coding agent 的约定。需求唯一事实来源：`tender-agent-mvp-prd.md`；
Artifact/任务系统的设计与决策唯一事实来源：`artifact-system-design.md`（改动相关代码前必读）。
另：`docs/skill design/`（重构手册上/下 + `schemas/` 四个 JSON Schema）是证据包/skill
体系的设计参考材料（自包含，面向新场景重建，非本仓现状的实现说明）；`docs/prototypes/`
放 HTML 原型页。改 skill/契约相关工作前值得先翻。

## 结构与分层（重要边界）

```
src-tauri/       Tauri 2 壳（Rust）：只做窗口、sidecar 进程管理、钥匙串、IPC command。零业务逻辑
frontend/        React 19 + Vite + Tailwind（shadcn 风格手写组件）；只通过 HTTP+SSE 与 sidecar 通信
sidecar/         Python sidecar（FastAPI + uvicorn），装配 DeepAgents
```

三条铁律：

1. Rust 不含任何业务逻辑。
2. API Key 永不出现于 HTTP 载荷与前端 JS 内存；key 由 Rust 从钥匙串读取（llm/vlm 两
   account：`llm-api-key`/`vlm-api-key`），spawn 时注入 env。
3. 前端只消费 PRD §5.5 事件契约（agent.started / agent.token / tool.called / tool.result /
   agent.completed / agent.error / todo.updated / artifact.created / run.state / ping），
   不依赖 DeepAgents 内部格式。run.state 是 SSE 连接建立时由端点下发的对账事件
   （最新 run 真实状态），客户端断线重连后据此恢复/收敛 running 态（MVP 无历史补发）。
   artifact.created 已**类型化**（payload 带 kind/schema_id/schema_version/display_name），
   客户端据此走 Processor Registry 唤起处理程序。
   **契约 additive 扩展（2026-08-25）**：tool.called/tool.result 带 `tool_call_id` 与
   `agent_id`（非空=子代理内部事件，值为所属 task 调用的 id，前端据此挂 SubagentCard 的
   children/reasoning）；agent.reasoning 的文本键是 `text` 且带 `agent_id`；全部流事件带
   per-run 单调 `seq`（前端去重+缺口检测，是 SSE 双连接重影的结构性防线）；run 结束时
   执行过程快照落 `run_traces` 表（tools 步骤树+todos+duration_ms），GET /messages 的
   assistant 消息挂 `tools/todos/durationMs`（历史会话/刷新后执行过程可见）。
   **契约 additive 扩展（2026-08-25 HITL，见下节）**：新事件 `run.interrupt`；runs 状态机
   加 `waiting_input`；`POST /api/runs/{rid}/resume` 裁决续跑。
   **契约 additive 扩展（2026-08-25 自动命名）**：新事件 `conversation.renamed`
   （payload 仅 conversation_id+title，**无 seq**——连接级推送，同 ping/run.state）。
   首条用户消息后 `app/titler.py` 用一次独立轻量 LLM 调用（不走主 agent、不碰
   checkpoint）生成标题，经 `db.set_title_if_default` 原子条件 UPDATE 写回（仅默认
   「新对话」时生效，用户手动改名后永不覆盖），成功后推事件让侧栏即时刷新。
   **契约 additive 扩展（2026-08-26 用户停止）**：`POST /api/runs/{rid}/cancel`
   （仅 running）置位 `agent.CANCEL_EVENTS` 协作式取消事件，worker 线程在下一个流
   事件边界退出（LLM 流式期间 token 持续到达故响应快；长工具中则等工具返回），
   走既有 error 路径：半截回复落库（「（任务中断）」标记）+ trace + run 标
   error「任务已停止」+ agent.error 事件；前端发送钮在 running 且非 HITL 等待时
   变为可点的停止钮（useRun.cancel，runId 由 agent.started/run.state 维护），
   取消到收尾的事件边界窗口内按钮转「正在停止…」防重复点；POST /messages 撞到
   cancel-pending 的 running run 时探测等待 ≤3s 其终止再放行（停止→立刻发不撞 409）。
   **过程旁白分流（2026-08-26，SSE 契约零改动）**：正文按轮次封段——主 agent 的
   tool.called 到达即把之前流出的正文封为旁白挂到该 trace 步骤的 `text` 字段
   （同轮连发多个调用只有第一个带），run 结束时最后未封口段 = 最终回复：messages 表
   **只存最终回复**（interrupt/error 半截落库在 final 为空时用最后一段旁白兜底，
   `_last_narration`），旁白随 run_traces 步骤树下发；前端 useRun 用同一条封段规则
   （tool.called 时封段清 streamText），RunTrace/SubagentCard 在工具行前渲染旁白行。
   checkpoint 记忆不受影响（仍是完整 AIMessage 序列）。system_prompt 加输出纪律
   （工具调用轮正文一句以内，完整汇报只在最终回复）。动因=行业实践：A2A/LangSmith/
   Anthropic Agent SDK/Responses items 一致「过程与结果分通道」，且无主流产品把
   逐轮旁白拼进一条正文消息。
   **契约 additive 扩展（2026-08-27 停止态标记）**：`agent.error` 与 `run.state`
   （error 分支）恒带 `code`（`cancelled`=用户主动停止，文案常量在
   `events.CANCELLED_MESSAGE`），前端据此把主动停止渲染成中性灰「重新执行」卡、
   不与真实错误共用红色。配套：run.interrupt 的 `requests[].description` 在 events
   适配层把 langchain HITL 默认英文模板（含完整 args repr）重写为人话摘要（args
   原样保留，前端「查看参数」仍可见全量）；暂停落库消息在续跑段终止且无新产出时
   经 `db.retire_pause_marker` 把「（等待你的输入…）」改写为「（任务中断）」
   （runs.pause_msg_id 记录暂停消息，PRAGMA 探测 ALTER 迁移）。
4. **设计铁则（用户明令）**：保持简洁；冲突处理用「探测 + 提示用户裁决 + 恢复点兜底」，
   **不加锁/互斥/租约/排队**等后台协调机制；锁只允许用户不可见的 plumbing
   （原子落盘、发布进程内写锁）且需用户认可。

## 任务层与 Artifact 系统（P1–P4 + §16 任务分组目录已实施）

- **业务模型（P4 定稿 + §16 布局，详见 artifact-system-design.md §15/§16）**：任务 =
  一次投标 = workspace 下一个真实项目文件夹（`workspace/<task_id>/{formal,threads/<conv_id>,files,out,drafts}`，
  目录名只用不可变 id）；会话必须归属任务；产物分两层——任务「正式稿」（formal/）/
  会话「过程稿」（threads/<conv_id>/），manifest 的 task_id 恒为所属任务、conversation_id
  区分两层，**包磁盘位置 = (artifact_id, manifest) 的纯函数**（store 层路径函数全部
  `(aid, scope)` 签名）；共享上下文 = 任务名 + 进度便签 + 产物清单 + **任务工作目录**
  （每次模型调用经 `_TaskContextMiddleware` 现算注入，模型路径带 `<task_id>/` 前缀），
  聊天记忆按会话隔离。
- **转正**：AI 发布只写过程稿、可挂 `propose_promotion` 建议标记；正式稿的每次写入
  都由用户点击 `POST /artifacts/{id}/promote`（复制不移动，task-single 覆盖留恢复点、
  记 derived_from，manifest 的 derived_from 只在首次发布写入）。LLM 工具永远无法直写正式稿。
- **未登记类型**一律收拢为通用笔记 `doc.note/note-md@1`（发布工具强制文档形态
  title+body_md），客户端 NoteProcessor 打开编辑；类型系统保持平台封闭注册。
- **全局作用域已移除（§16.4）**：publish 必须恰传 task_id/conversation_id 之一；
  read_artifact 读序两级（正式稿→本会话过程稿）；db 无 NULL/NULL 分支；前端 scope 类型无 global。
- **删除语义**：删会话 = rmtree `threads/<conv_id>/` + 索引行（db 级联清理）+ 记忆清理；
  删任务 = 先 rmtree `threads/`（过程稿硬删）再整任务目录 mv 到 `workspace/archive/<task_id>/`
  （正式稿+上传文件+out/ 工作台随归档可手工找回）+ 全部会话记忆清理；409 活跃 run 守卫不变。
- **任务级文件区（§16.2）**：上传落 `<task>/files/`（`POST/GET/DELETE /api/files` 均必填
  `task_id`），跨任务同名文件互不影响；前端上传上下文带当前任务，无任务时禁用并提示先选任务。
- **sidecar 模块**：`app/contracts/`（平台契约目录，契约真值只在 sidecar，客户端只做映射）；
  `app/artifact_store.py`（任务分组路径派生 formal_dir/thread_dir/task_files_dir/task_out_dir/
  task_drafts_dir + 包存储 + archive_task 整目录归档；manifest 权威、`db.artifact_index`
  可重建索引（结构化扫描各任务目录）、恢复点留 3 个）；
  `app/publish.py`（**唯一登记入口**：作用域恰传其一（会话反查所属任务恒写 task_id）→
  契约存在→授权（stub：已注册契约全允许，模板待第二场景）→schema 校验→原子落盘）；
  `app/api/tasks.py`（任务 CRUD；POST 默认连带第一个会话，`with_conversation=false` 供
  输入区选择器就地新建）；`app/tools/publish.py`（LLM `publish_artifact`，草稿限当前任务
  `drafts/`，未知契约收拢 doc.note）；`app/tools/read.py`（`read_artifact` 读序两级；
  task-multi 用 artifact_id 指定）；`app/tools/task_progress.py`（进度便签）；
  `app/runctx.py`（contextvars 传 cid/rid/task_id）。
  `out/` 是**任务级**技能工作台（`<task>/out/`：parse→analysis→outline→body 的中间产物），
  跨任务互不串台；目录按需创建，启动不预建。
- **投标流水线 Phase 1（2026-08-25，入口段 2026-08-26 重构）**：旧 tender-toc skill
  及其工具已移除，新体系 =
  skill `document-parse`（**文件→markdown 独立技能**，流水线入口：ls 任务 files/ 枚举候选
  （.docx/.pdf/.txt/.md 均可解析）→ 同名双格式去重 ask → 来源集合确认（单文件默认主文件
  确认+补传窗口/多文件选主文件/新增只问角色，沿用不重问）→ 写来源确认单
  `out/parse/sources.json`（main/supplements[+role]/excluded——任务级共享状态，
  跨会话交接+重入沿用依据；**变化检测锚点=parse_document 幂等返回**：跳过=未变、
  重入时重新解析=确认后重传过，交确认门裁决——**不用时间戳**，模型写的时间戳
  不可信（confirmed_at 零点占位先例，字段已删））→ **并行 parse_document**
  （同一 assistant 消息一次性发出全部调用，ToolNode 线程池真并行——PyMuPDF 释放
  GIL；主文件失败在概况门前拦停，不串行即停）→
  **解析概况确认门**
  （流式摘要：角色/字符量/页数/标题数/解析档位/顶层章节/警示/降级声明 + ask 确认/停下，
  全部[解析跳过]时不弹门；**数字全部取自 parse_document 返回文案**（跳过同样带全量
  概况），不读 meta.json；档位与出处署名联动））+
  skill `tender-analysis`（七节要点提取，第 0 步=前置检查：sources.json 就绪+产物齐备+新鲜；
  purpose 下沉 references/ 文件级、单项可重跑；导航硬纪律=先读 out/parse/<文件名>/
  <文件名>.outline.json 按行号取区段、补充文件同纪律，禁止整读全文；**出处引用键**：
  必带行号区间「章节名（L412-L430，第23页）」，章节名在作者声明/自报档
  （docx-native/pdf-toc/pdf-link-toc/pdf-printed-toc）与编号档（docx-numbered/pdf-numbered，
  标题印在原文可验证）署名，pdf-plain 只给行号+页码）+
  工具 `parse_document`（docx/pdf/txt/md→md + 带行号区间的 outline.json + meta.json；
  **结构识别分档**（meta.conversion）：docx 样式 / PDF 书签 get_toc 优先（作者声明，
  命中率<50% 回退）/ 无书签 pdf 走**目录页超链接**（条目自带 GOTO 链接：矩形即标题、
  目标即物理页，pdf-link-toc，实测语料 14/17 命中）→ **印刷目录页解析**（解析文件自印的
  目录条目、回正文逐条定位，pdf-printed-toc）→ 中文编号兜底（docx-numbered/pdf-numbered，标题印在
  原文可验证）→ pdf-plain（无结构，警示 grep 兜底）；**字号判级已删除**（2026-08-28
  实测证伪：政采 PDF 章标题字号常与正文相同、封面全是巨字，17 份语料 3/3 全灭）；
  **PDF 页眉页脚剔除**（跨页重复条带+纯页码）+ 每页 `<!-- p:N -->` 页码锚点；txt/md
  透传（gb18030 兜底）；meta 含 pages/top_level(前12)/tables；同 hash 幂等、扫描件兜底、
  workspace containment、裸文件名回退任务 files/；.doc 明确拒绝提示另存为 .docx）+
  工具 `assemble_tender`（读 out/analysis 三张机器输入表构建 MAND/TPL/REQ/SCORE 登记表
  （**行序=编号，产物头部 HTML 注释行会被 registry 跳过**）+ out/outline 目录中间态
  →lineage_check→发布 `tender.directory` 过程稿+建议转正）。
  后续 Phase：tender-body / tender-flow skill（规划见 docs 讨论，
  机器输入格式契约在 assemble_tender.py 模块 docstring）；大文件专项优化留在
  document-parse 阵地内迭代。
- **投标流水线 Phase 2（2026-08-25；多册并发 2026-08-26）**：skill `tender-outline`
  （SKILL.md + 6 references）：
  R1 响应文件分解（首个 LLM 裁量确认点=两问测试，多方案 ask_human）→ R2 初稿 +
  **三道清理固定顺序**（①查漏补缺/②评分对齐/③走查定稿，原则从 document_helpler 老流水线
  逐字保留，各有跳过条件与声明义务，节点增删改同步维护来源标注/目录说明）→
  assemble_tender 组装发布。**单册**主线程就地做；**多册（≥2）**并发派发
  `tender-outline-writer` 子代理每册一个（同一消息全部 task 调用，一次审批卡批量放行；
  子代理不继承任务上下文注入也不自动载 skill——派发 description 自带任务目录前缀/
  scope/fragment 路径，方法论让它 read_file skills/tender-outline/references/*.md；
  每册产物落 `out/outline/fragments/<册名>.md`，返回后主线程按册序合并覆盖写
  tender-response-docs.md + 规则 8 跨册去重互查；单册重做=重派该册重合并）。
  树格式红线（`- ` 开头/无编号/2 空格缩进/独立附件平级）是
  assemble 的解析协议。`tests/test_skills.py` 对全部 skill 做 frontmatter+references
  存在性校验（deepagents 加载坏 skill 只 warning 不报错，测试升级为硬失败防半接入）。
- **frontend**：`src/artifacts/registry.ts`（kind/schema@version → Processor 注册表 + 启动契约对账）；
  `components/processors/`（DirectoryProcessor 目录树编辑 / NoteProcessor 通用笔记）；
  `components/ArtifactOpenHost.tsx`（通用容器，未命中契约明确报不支持，**无 JSON 兜底预览**）；
  `components/TaskPicker.tsx`（新会话必选所属任务）；侧栏任务文件夹树（hover 新会话/重命名/删除）；
  产物面板两层 tab（正式稿/过程稿）+ 过程稿行内「转正」+ 任务进度便签编辑；
  `context/FileUpload.tsx` 带任务 scope（taskScope/setTaskScope，ChatView 按会话/选择器写入），
  文件 chips 只显示当前任务的文件、无任务禁传。
- **并发/冲突**：无租约无互斥——任务内 run 随便并发；发布即覆盖（覆盖前自动留恢复点，
  `POST /artifacts/{id}/restore` 可恢复且可再撤销）；`content_seq` 是探测器不是锁
  （目录编辑器 5s 轮询，外部更新时无本地改动静默跟随、有则弹「拉取最新 / 保留我的=force 覆盖」；
  NoteProcessor 不轮询，靠保存 409 兜底同一裁决）。
- **新契约接入**按设计文档 §13 五步打包：契约定义→SKILL.md 指导→客户端 Processor→
  模板集合→全链路验收；禁止半接入（客户端启动对账会 console.warn）。
- **P4/§16 已知限制**：任务模板未引入（授权 stub 全允许）；跨会话正式稿变更无实时推送；
  task-multi 多次转正会产生多份副本。

## HITL（human-in-the-loop，2026-08-25）

- 用 deepagents 原生 `interrupt_on`（`agent.INTERRUPT_ON`，当前两项：`ask_human`
  `allowed_decisions=["respond"]` 问答型；`task` approve/reject——子代理派发审批门禁，
  tender-outline 多册并发派发前用户确认）。给其他工具加门禁改这里。子代理 spec 的
  `interrupt_on` 是**整体替换继承**——tender-outline-writer 传 `{}` 即排除（子代理不直接问用户）。
- **暂停语义**：langgraph 在 updates 模式以 `{"__interrupt__": (Interrupt,...)}` 下发
  （值是元组，不专门处理会被 `events.iter_stream` 静默丢弃且 run 以空回复 completed）；
  捕获后 run_stream 落半截回复（带「等待你的输入…」标记，沿用任务中断先例）+ trace →
  `db.interrupt_run` 置 `waiting_input` 并存 requests 快照与 `last_seq` → 发
  `run.interrupt`（data 带 `requests:[{tool,args,description,allowed}]`）。注意 interrupt
  发生在 after_model（节点内），**之前不会发 tool.called**。中断快照里被门禁拦下的
  running 步骤由 `_freeze_paused_steps` 改标 `paused` 终态（前端「已暂停」徽章、自动
  收起）——不冻结转圈、避免与续跑段同名步骤形成"冻结+活跑"双卡。
- **续跑**：`POST /api/runs/{rid}/resume`（decisions: approve/reject+message/respond/
  edit；决策数须与快照一致）。respond 决策同步落 user message（messages 是记忆恢复源）；
  续段以 `Command(resume=...)` 从 checkpoint 续跑同一 run、重发 agent.started，**seq 从
  runs.last_seq+1 续接**（前端按 run_id 去重，重置会吞掉续段事件）。
- **runs 表 CHECK 加状态不能 ALTER**——`db.init_db` 启动时探测 `sqlite_master` 整表重建
  迁移（仓内首例）。`recover_stale_runs` 只翻 running：waiting_input 的 interrupt 活在
  checkpoint，sidecar 重启后仍可 resume；`active_run_exists` 视 waiting_input 为占用
  （发消息 409 提示先处理）。
- **前端**：`InterruptCard`（`components/ai/`，模仿 langchain agent-chat-ui 的 interrupt
  内联卡——HITLRequest 载荷同源）按 `allowed` 分支：respond-only=问答卡（`args.options`
  渲染可点选选项，`args.multiple` 决定单选/多选；点选与输入框补充文字由 ChatView 拼成
  「已选：X；Y\n补充…」一条 respond 回答，send 自动路由）；否则审批卡（批准/拒绝+可选
  理由；edit UI 不做）。run.state/GET runs/latest 在 waiting_input 时附 requests 快照
  恢复卡片（点选状态不持久，重连后重选）。
  （原 HITL 全链路测试载体 ai-news-research 技能及其 news-researcher 子代理已于
  2026-08-27 删除；HITL 机制由 ask_human/task 门禁本身及 tender 流水线持续使用。）

## 知识库（公司资料库，2026-08-27 已实施）

跨任务共享的公司资料层（资质证书/合同案例/人员证书/公司介绍等），写标书时检索引用。
单库、无向量：FTS5 全文检索，`kb_items` + `kb_segments`（FTS5 虚表）两张表，索引可从
kb_items+磁盘 md 重建（启动 `rebuild_kb_index`）；同 hash 上传 API 层拦截（uq_kb_items_hash）。

- **磁盘布局**：`workspace/knowledge/{files,parse}/`——与 skills/archive 同级的**全局目录**
  （`artifact_store._GLOBAL_DIR_NAMES` 先例，任务目录枚举跳过它、agent 文件工具天然可读）。
  原件在 files/（投标引用用原件）；解析产物 parse/<stem>/（.md/.outline.json/.meta.json，
  与任务场景 parse_document 同三件套格式）。
- **sidecar 模块**：`app/knowledge/types.py`（类型注册表**封闭**，10 类：营业执照/资质证书/
  人员证书/合同案例/验收报告/财务审计/公司介绍/技术方案/荣誉知产/其他；每类字段模板+
  文件名提示规则；类型清单不进表结构（doc_type 存 code、字段全收 JSON 列），加类型零迁移）；
  `segmenter.py`（outline 节点→检索段）；`fts.py`（**jieba 写入/查询两侧同源分词 + 中文
  bigram 补充**——unicode61 把连续 CJK 当单 token 会整句 miss，bigram 保两字词子串命中）；
  `ingest.py`（入库管线：上传后 fire-and-forget `asyncio.create_task`+to_thread（titler 先例），
  状态 parsing→ready（切段完成即可检索）→extracting→ready；启动 `db.recover_stale_kb`
  对账残留态）；`app/api/knowledge.py`（上传/条目列表详情/PUT metadata 确认/GET kb/badge
  红点计数/kb/types 类型注册表）；`app/tools/search_knowledge.py`（LLM 检索工具：命中带
  章节路径+行号区间+摘录+read_file 精读指引；doc_type 过滤后无命中回退未过滤结果
  （误召回>漏召回）；失败返回「[检索失败]」文案不抛异常打崩 run）。
- **审核边界=提示不是门禁**：kb_items 双列 suggested_metadata（LLM 抽取建议）/
  business_metadata（人工确认）；pending_review 条目照常可检索；PUT metadata 确认即
  confirmed+重建检索段（人工填的字段也要可检索）。
- **视觉路由**：图片整体走 VL 转写；PDF 按逐页文本量分类（meta.scanned_pages），扫描页
  渲染成图 VL 转写后拼回页锚点；转写后统一走文本抽取管线（VL 只是图→文本替代 OCR）。
  VLM 未配置一律降级链：收原件+登记资产+人工填表，**不阻塞上传**。
- **解析注册表**：`app/parse/`（扩展名→**确定性**转换器，docx/pdf/txt/md→md；知识库入库
  与 parse_document 工具共用同一套核心转换器，工具层只加场景限制）。注册表不收图片/
  扫描页转换器（`parse/image.py` 提供但不注册）——外部模型调用不得静默触发，属入库编排层。
- **VLM 客户端**：`app/vlm.py`，OpenAI 兼容 chat.completions+image_url，配置经
  VLM_API_KEY/VLM_BASE_URL/VLM_MODEL（三者任一缺失=未配置），provider 无关。
- **上下文注入**：agent 任务上下文注入附 `_kb_summary_line`（类型清单+待确认数一行，
  引导模型先 search_knowledge 再写）。
- **frontend**：`components/KnowledgeView.tsx`（左栏类型分组折叠列表+右区内容/信息两 tab，
  信息 tab=元数据确认表单）+ `hooks/useKnowledge.ts`（react-query；parsing/extracting
  分阶段轮询）+ NavRow 红点（badge 60s 轮询）。

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
- 未配置钥匙串 key 时 sidecar 仍可起，但 agent 调用会报「LLM_API_KEY 未设置」。
- 浏览器模式（`npm run dev:browser`，前端经 proxy 访问的）8765 sidecar 用的是
  `sidecar/.env` 里的 `LLM_API_KEY`——它可能是占位/无效 key（会报 401 invalid key），真实 key
  只在 Tauri 模式由 Rust 从钥匙串注入。浏览器模式要跑真实对话，需在 `.env` 里配有效 key。
- sidecar 有 pytest（`uv run pytest`，覆盖 db 恢复 / 设置校验（含双角色）/ 工具路径 containment /
  契约校验 / 发布管线 / 编辑保存与恢复点 / 知识库（入库/检索/元数据/解析注册表，
  `test_knowledge_*.py`）/ **§5.5 事件契约 schema**（`test_contract.py`，
  字段清单须与前端 `api/sse.ts` 的 AgentEventData 人工同步））；frontend/Rust 暂无测试 runner。
- e2e 冒烟：`cd sidecar && uv run pytest -m e2e`——spawn 真实 sidecar 子进程（独立端口 +
  隔离 DATA_DIR）跑一轮真实 LLM 对话，断言 run 完成、SSE seq 单调无重复、tool_call_id
  唯一、messages/trace 落库。需要 `.env` 有效 key（无则 skip）。日常 `uv run pytest` 默认
  排除 e2e（保持秒级）；**动 events/agent/bus/SSE 相关代码后应跑一次 e2e**。

## 代码约定

- **sidecar**（Python ≥3.12，uv 管理）：
  - `app/events.py` 是 LangGraph 流 → §5.5 事件的**唯一适配层**；库 API 变化只改这里。
  - SSE 事件 data 必须合法 JSON：在 `app/api/sse.py` 里 `json.dumps(data, ensure_ascii=False)`，
    因为 sse-starlette 对 dict data 会输出 Python repr（单引号，非法 JSON）。
  - agent 运行在 `asyncio.to_thread` 的 worker 线程，逐事件用 `run_coroutine_threadsafe`
    实时发布（否则 token/tool 事件会在 run 结束后一次性爆发，前端无流式）。
  - `SqliteSaver.from_conn_string` 在新版是上下文管理器；sidecar 常驻需自持连接：
    `sqlite3.connect(agent_db_path, check_same_thread=False)` + `SqliteSaver(conn)`；
    该连接进程存活期**只开一条、永不关闭**（rebuild 只换 agent 对象复用同一 conn/saver），
    否则运行中 PUT /settings 会让正在跑的旧流 checkpoint 崩溃。
  - 新增工具：在 `app/tools/` 里 `@tool` + zod（或 docstring schema），并加入 `tools/__init__.TOOLS`；
    领域事件由 server 装配的 eventSink 落库，工具不直接写 UI。
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
  - 模型设置双角色嵌套（2026-08-27）：`data/settings.json` 结构 `{llm:{...},vlm:{...}}`
    （旧扁平 LLM_* 键兼容迁移），优先级 env > settings.json > 默认值；
    `app/api/settings.py` GET/PUT 双角色读写+连通性测试，**key 永不接受 HTTP 修改**
    （GET 只回 key_configured 布尔）；PUT 后 llm 变更即时重建 agent、vlm 是无状态客户端
    改 env 即生效；Tauri 侧对应 IPC `set_model_settings`（按 role 写 settings.json+钥匙串）。
  - skills 从 `app/skills/` 启动时同步到 `data/workspace/skills/`（FilesystemBackend root）。
- **src-tauri**（Rust stable ≥1.85）：
  - `src/sidecar.rs`：选空闲端口 → 随机 token → spawn（`process_group(0)`）→ healthz(nonce 校验,1s×30) →
    指数退避重启（上限 3 次）→ 退出杀进程树并 wait 回收。模型设置单一真值在
    `data/settings.json`（`{llm, vlm}` 双角色嵌套，HTTP PUT 与 IPC `set_model_settings`
    都写它，spawn 前读取注入 env）；key 存钥匙串**两 account**：`llm-api-key`/`vlm-api-key`
    （vlm 传空 base_url=显式清除配置，llm 空值不覆盖现值；改完触发 supervisor 重启 sidecar）；
    `stopping` 标志保证应用退出后 supervisor 不再拉起孤儿进程。
  - 生产分发限制：目前用 `Command` 直接 spawn `.venv/bin/python -m uvicorn` + 自定义 supervisor
    （随机端口/token 注入/healthz 探活/退避重启），dev 期没问题，甚至比官方 `sidecar()` 更强
    （官方不做健康检查/鉴权/重启）；但 `tauri build` 分发时打包应用找不到 Python。届时须转官方模式：
    PyInstaller 把 sidecar 打成二进制 → `bundle.externalBin` 注册（`-$TARGET_TRIPLE` 后缀）→
    shell 插件 `sidecar()` 拉起（capabilities 配 `shell:allow-spawn`），保留现有 supervisor
    探活/重启逻辑、仅把 python 路径换成打包二进制。
    参考 https://github.com/dieharders/example-tauri-python-server-sidecar
  - 钥匙串用 macOS `security` CLI 子进程（`keyring` crate 在此 macOS 写 Data Protection 钥匙串，
    `security` CLI 不可见，无法满足 PRD M3 验收）。
  - 已装插件仅两枚官方 plumbing：`tauri-plugin-single-instance`（须第一个注册——GUI 双开会撞
    agent.db 单库 checkpoint，二次启动聚焦已有窗口，不做互斥协调）+ `tauri-plugin-window-state`
    （记住窗口大小/位置）；均纯 Rust 侧、零 IPC 权限、前端零依赖。
- **frontend**：sidecar 地址解析在 `src/api/client.ts` 的 `getSidecarInfo()`——
  Tauri 环境走 `__TAURI_INTERNALS__.invoke('get_sidecar_info')`；浏览器开发模式默认返回
  相对路径（`/api/...`），由 `vite.config.ts` 的 `server.proxy` 同源转发到 8765——CORS
  整类问题被消除，SSE 也能透传；需直连时用 `VITE_SIDECAR_URL`/`VITE_SIDECAR_TOKEN` 覆盖。
  `vite.config.ts` 固定 `port: 5173 + strictPort`，端口被占宁可启动失败也不回退（回退会让
   CORS/地址失配静默失败）。SSE 用 `@microsoft/fetch-event-source`。
  - UI 全手写、**零 radix/cva**：`components/ui/` 是 shadcn 风格基础件
    （button/dialog/input/collapsible/hover-card），`collapsible.tsx` 支持透传 data-*。
    `components/ai/` 是从 prompt-kit 移植的 AI 组件（Loader/TextShimmer/PromptSuggestion/
    Reasoning/ChainOfThought/Steps/Source/FileUpload/ThinkingBar/Tool），全部手抄适配、
    零第三方依赖，动画 keyframes 集中在 `styles/ai.css`。吸收新 prompt-kit 组件照此先例：
    抄源码思路适配到语义 token，不引 radix/cva/motion（详见记忆 prompt-kit-visual-adoption）。
  - 设计 token：`index.css` 定义 `--paper/--panel/--ink/--line/--accent-soft` 等（light only），
    `styles/workspace.css` 是 Workspace 组件设计系统；UI 改动优先用这些语义变量。
  - `preview.html`（→ `src/preview/`）是独立组件预览入口：只引 workspace.css，
    不引 index.css/Tailwind/后端；验证纯 UI 组件时用它，别在预览页引 Tailwind 工具类。

## 已知事项

- **浏览器模式下改 sidecar Python 代码不热载**：Vite HMR 只覆盖前端；改完 Python 必须
  `./dev.sh stop` 后重启 browser 模式才跑新代码（前端访问的 8765 是旧进程时会表现为
  「接口 404 / 行为没变」）。
- 网络镜像必配：pypi=清华（pyproject 内置）、npm=npmmirror（.npmrc）、cargo=rsproxy
  （`src-tauri/.cargo/config.toml`）、rustup=`RUSTUP_DIST_SERVER=https://rsproxy.cn`。
- DeepAgents 锁 0.7.7（`deepagents==0.7.7`）；langgraph 由依赖解析（当前 1.0.5）。
- uvicorn 不要开 `--reload`（Tauri 进程树管理会乱）。
- 解析支持 `.docx`（python-docx）与 `.pdf`（PyMuPDF 原生提取，无 soffice 依赖）；`.doc` 不支持（上传与解析均明确拒绝，提示另存为 .docx）。
