# AGENTS.md

本仓库是 Tender Agent（智能标书 Agent 桌面客户端，local-first）的 monorepo。
给在本仓库工作的 coding agent 的约定。需求唯一事实来源：`tender-agent-mvp-prd.md`；
Artifact/任务系统的设计与决策唯一事实来源：`artifact-system-design.md`（改动相关代码前必读）。
另：`docs/skill design/`（重构手册上/下 + `schemas/` 四个 JSON Schema）是证据包/skill
体系的设计参考材料（自包含，面向新场景重建，非本仓现状的实现说明）；`docs/prototypes/`
放 HTML 原型页。改 skill/契约相关工作前值得先翻。

## 结构与分层（重要边界）

```
src-tauri/       Tauri 2 壳（Rust）：只做窗口、sidecar 进程管理、IPC command。零业务逻辑
frontend/        React 19 + Vite + Tailwind（shadcn 风格手写组件）；只通过 HTTP+SSE 与 sidecar 通信
sidecar/         Python sidecar（FastAPI + uvicorn），装配 DeepAgents
```

三条铁律：

1. Rust 不含任何业务逻辑。
2. **API Key 存本地库**（2026-08-29 用户明令修订，弃钥匙串）：模型/百度 OCR 的 Key 与
   全部模型配置存 `app.db` 的 `app_settings` KV 表（明文落盘，威胁模型与 .env 等价），
   经 sidecar HTTP 写入（`PUT /settings/keys`、`/settings/ocr-keys`），改动即时生效
   （agent 缓存重建，无重启）。**保留的硬性质：GET /settings 永不回读 Key**——只回
   `key_configured` 布尔，Key 的 HTTP 载荷只写不读；env（`LLM_API_KEY`/`MODEL_KEYS`/
   `BAIDU_OCR_*`）只作兜底读取。旧钥匙串条目作废（历史遗留不可见无害）。
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
   **契约 additive 扩展（2026-08-28 思考档位）**：`POST /messages` 请求体加
   `thinking`（low/medium/high，缺省 low；标准 `reasoning_effort` 直传模型，
   **无关闭项**——deepseek-v4-flash 等现代模型默认开思考）。runs 表加 `thinking`
   列存档（迁移 10；HITL resume 沿用首段档位、旧库空串兜底 low）。注入点=
   `agent._RunAwareChatDeepSeek`：覆写 `_get_request_payload` 现读 `runctx` 档位
   （contextvars 随 to_thread 线程拷贝传播，ToolNode 并行走 langchain_core 的
   ContextThreadPoolExecutor 同样拷贝 context——子代理派发后模型调用仍读到档位；
   主 agent 与子代理共用实例、并发 run 互不串扰）；titler 是独立实例不受影响。
   前端 `ThinkingSelect` 胶囊（composer 底栏 ModelSelect 旁，localStorage
   `tender-agent.thinking-level` 记忆、默认低，ChatView 持有态——无会话首发的
   initialSend 路径也要带上）。思考内容显示链路（agent.reasoning 事件 /
   run_traces.reasoning / DeepThinking 组件）零改动。
   **思考流按步封段（2026-08-31，SSE 契约零改动）**：主 agent 的 reasoning 不再
   整段累积——与旁白封段同一条规则，`tool.called` 到达即把未封口思考封进该步骤的
   `reasoning` 字段并清零（同轮连发多调用只有首个带；`task` 步骤同样封，子代理
   思考经 agent_id 追加在同字段后段、时序自然正确），run 结束最后未封口段=最终
   回复前的思考、照旧落 `run_traces.reasoning`。sidecar 落库点=agent.py
   tool_called 分支（agent.py:669 附近）；**`_merge_trace_trees` swap 改字段级
   兜底**（新副本 text/reasoning 为空且旧段非空时保留旧值——HITL 审批续跑重发
   tool.called 的新副本封段字段必为空，否则会抹掉暂停前封下的旁白/思考）；前端
   runReducer tool.called 同步封 `step.reasoning`。渲染：RunTrace 新增
   `StepThinking` 折叠行（Brain 图标「思考」，默认收起点开 max-h-72 看全文，
   在 NarrationLine 之上；AskedQuestions 组内同样渲染），SubagentCard 的
   StepReasoning 标签改「思考过程」；活卡 RunMessage 与历史 ChatMessage 的
   DeepThinking 都从 RunTrace 上方移到**下方**（语义=当前/最终未封口段；旧 trace
   快照整段 blob 照旧显示仅换位置）。动因=时序流水：此前全部思考堆在一个持续
   膨胀的顶部思考块，思考与工具调用的时间关系不可见；效果=思考→工具→结果→思考
   的可见流水。HITL interrupt 在模型节点内触发、先于 tool.called，暂停前思考留在
   未封口段（run 级 reasoning/活卡 reasoningText 承接），不丢。测试
   parity：test_agent.py（封段/batch/merge 兜底）+ runReducer.test.ts（封段/
   未封口段），test_contract.py 旁白 parity 断言不变。
   **契约 additive 扩展（2026-08-28 设置重构与文档解析）**：GET /settings 响应加
   `llm.image_support`、顶层 `ocr.configured`（百度 AK/SK 两 env 齐）与
   `paths.{data_dir,log_file}`；PUT 接受 `llm.image_support`（只存 settings.json、
   **不触发 agent 重建**；Rust 侧 ModelSettings 必须透传该字段，否则保存 key 重写
   settings.json 时会抹掉）。`GET /settings/test?role=ocr` = 用 AK/SK 换一次
   access_token 探活（未配置 400、失败 502）。设置界面 SettingsDialog →
   **SettingsModal** 双栏窗（ModalShell 加 cardClassName；左导航 模型/文档解析/通用
   + section 注册数组，入口与默认落点不变），右区顶部**能力状态条**（未配 LLM key/
   无视觉能力/未配文档解析，提示不是门禁），模型页加**厂商预设**（前端静态快捷填充
   不当真值）与「支持图片输入」勾选；文档解析页= 百度云 AK/SK 两字段（仅 Tauri，
   钥匙串 account `baidu-ocr-api-key`/`baidu-ocr-secret-key`，`set_baidu_ocr_keys`
   command 保存后重启 sidecar，凭证不进 HTTP）；通用页= 数据目录/日志路径 +
   「打开」（**reveal_in_folder 路径前缀从 workspace/ 扩到 data/**）+ 版本号
   （vite define `__APP_VERSION__`）。
   **契约 additive 扩展（2026-08-29 HITL 单回合聚合）**：messages 表加 `run_id` 列
   （迁移 13，nullable；POST /messages 用户消息/respond 回答/半截与最终 assistant
   消息全部带 rid 写入），GET /messages 每条消息带出 `run_id`——前端据此把同一
   run 的暂停段+续跑段消息聚合成单回合（一个头像头、续段正文对齐、审批卡贴附
   回合）。配套 sidecar 行为修正：run_traces 同 run 续跑收尾**合并不覆盖**
   （按 tool_call_id 去重、新段终态优先、旧段在前，message_id 新值优先/
   error 无产出保留暂停消息挂载，reasoning 拼接、duration 累加）；暂停/中断
   半截消息取 `_last_narration` 兜底时同步从 trace 步骤 text 清空（旁白不再
   双写）；`finish_run` 回写终态 `last_seq`（此前只有 interrupt_run 写过）；
   任务创建预建 files/out/drafts 骨架目录 + run 启动自愈（run_stream 解析出
   task_id 即 ensure_task_skeleton，幂等补齐——旧版只建库行的任务、纯检索类
   从未落盘的任务，模型第一步 ls 任务根目录不再 path_not_found）。
   前端配套：暂停/中断标记（「（等待你的输入…）」「（任务中断）」）渲染层
   剥离为状态徽章（正文不再带尾巴文本）；RunState 加 `continuation`（批准/
   回答后续跑段，sticky 防 SSE agent.started 二次到达冲掉）——RunMessage 去
   回合头紧贴暂停消息；主气泡状态行动态化（正在思考/正在执行·工具名/子代理
   执行中·已完成 N 项）；trace 折叠头含 paused 步骤时显示「已暂停 · N 步」；
   问答卡（ask_human 向导）头部改 tool_use 风格「已询问 N 个问题 · 等待你的
   回答」（用户明令：HITL 提问当 tool_use 呈现、不像会话被打断；纯审批卡
   维持确认框架）。**二轮（同日，路线 A 终态）**：HITL 痕迹全部收进过程区——
   暂停/中断消息不再渲染正文气泡（正文作旁白行进过程卡、标记成卡内徽章）；
   respond 回答消息不渲染对话气泡（识别=前一条 assistant 带标记或「已选：」
   前缀，`lib/hitlMessage.ts` 供 MessageList 与重新执行重试共用，顺带修掉
   纯文字回答被当指令重发的隐患）；已回答的 ask_human 步骤在 trace 里收进
   「已询问 N 个问题」折叠组（问题+「你的回答：」摘要）；续跑流式气泡渲染
   「你的回答：<lastSent>」一行防提交后空窗（decide() 路径补 remember-sent）。
   落库与恢复机制零改动（回答仍是 user message，只是渲染层不占转录）。
   **三轮（2026-08-30，单回合一张过程卡）**：暂停消息**无条件落库**（提问前零
   旁白时只落裸标记「（等待你的输入…）」——此前不落库会导致回合内唯一 assistant
   是最终回复、头像头错落到回合尾部，用户体感「进入另一个时空」）；前端组内
   装配把带标记的暂停段整体吸收进后续最终段（旁白/标记上提为卡片内的旁白行与
   徽章），全回合只渲染一张过程卡；retire_pause_marker/splitMarker 兼容裸标记。
   **四轮（2026-08-30，一张活卡贯穿 run 生命周期）**：活卡（RunMessage）渲染条件
   扩为 `running || interrupt`——ask_human 暂停时**原地冻结不换卡**：settle-interrupt
   不再清空（running 步骤经 `freezeRunningSteps` 冻结为 paused、reasoningText 保留、
   未封口 streamText 移入新状态字段 `pauseNarration` 渲染为过程区顶部旁白行），
   胶囊转「等待你的输入」、折叠头转「已暂停 · N 步」、正文气泡隐藏（动作入口=
   下方 `.turn-attach` 提问卡）；批准/回答后同一 React 实例解冻续跑（手动展开的
   折叠态全程保持）。暂停消息在活卡存续期间经 `isLivePauseMessage`（hitlMessage）
   从转录隐藏（hiddenPauseRunId=running?runId:interrupt.runId，数据驱动、旧库
   run_id 缺失自动退回双卡），终态后回到转录被最终/中断消息吸收。配套：
   `snapshot` action 接受 waiting_input（等待期刷新/重连也重建冻结活卡，不置
   running，restoreSnapshot 守卫同步放宽）；fillStep 对 paused 步骤也回填（409
   双窗口下 SSE started 先到、乐观 revive 未发生时续跑段 tool.result 仍能落终态）；
   RunMessage 回合头像头恒显示（continuation 的无头逻辑随双卡一起删除）；
   `.turn-attach` margin-top -10px（贴暂停消息卡尾部隐藏操作条的旧标定）改 2px。
   **多模型 profile 与输入框选模型（2026-08-29，替代上段的 llm/vlm 双角色形状；
   同日傍晚二改：配置与 Key 真值从 settings.json+钥匙串整体迁到 app.db——见铁则 2）**：
   GET /settings = `{models(含 key_configured), default_model, ocr, paths}`；PUT
   `/settings/models` 全量覆盖（前端唯一写者）；`PUT /settings/keys`（模型 Key）、
   `PUT /settings/ocr-keys`（百度 AK/SK，写后作废 access_token 缓存）——**只写不读**；
   `/settings/test?model=<id>` 按模型 ping（role=ocr 保留）。**vlm 独立角色删除**——
   视觉能力= 任一 image_support 的 profile（`config.resolve_vision()`：default 优先，
   否则第一个；vlm.py 改读它）。配置真值= app.db `app_settings` KV（键 model_profiles/
   default_model/model_keys/baidu_ocr；settings.json 仅作一次性导入来源不再写；
   env 只兜底读取）。**按消息选模型**：POST /messages 加 `model`（未知 id 静默回落
   default）；runs 加 `model` 列（迁移 11，resume 沿用）；agent 从进程级单例改
   **`dict[profile_id]` 缓存**（get_agent(pid)、rebuild=清缓存、saver 共享、in-flight
   持引用互不影响、子代理继承同实例）；titler/KB 抽取恒走 default profile（`llm_*`
   薄壳保留）。前端：设置模型区改**列表制**（厂商色块+图标行操作+「本地配置」
   说明卡；**无默认标识**——default_model 仅作后台兜底=列表首位，用户不可见亦不可选，
   2026-08-29 用户明令「默认没有任何义务意义」）；添加/编辑走**二级弹窗**（WorkBuddy
   式 2026-08-29）：标题带「仅支持 OpenAI 兼容协议 API」徽标，提供商可搜索分组下拉
   （厂商色块；预设=只填 Key+选模型，自定义才露接口地址，模型名下拉带「自定义模型
   名…」逃生口），显示名自动派生不再手填，保存=putModels+putModelKey 一键（测试=先
   静默保存再 ping）；**弹窗卡片不能加 overflow-hidden**（提供商下拉要溢出卡片，加了
   会把「自定义」裁掉）；厂商预设模型清单 2026-08-29 按各家官方文档刷新
   （DeepSeek V4 系/Kimi k3+K2 系/百炼 qwen3-max+qwen3-vl-plus/智谱 glm-5.x+4.6v/
   豆包 seed-1.6/MiniMax-M2.5 新增/OpenAI gpt-5.x），会过时、少而精；`ModelSelect`
   重写为**下拉选择器**（列全部模型+Check+「管理模型…」尾项，克隆 ThinkingSelect
   模式）；选中按会话粘性（localStorage `model-by-conv` map + `model-last`），
   随每条消息发送。Key 输入框浏览器/桌面两模式统一（都走 HTTP，保存即时生效无重启）。
   **二级弹窗 Escape 分层（下拉→弹窗→设置窗逐层关）**：点「添加模型」后焦点常停在
   弹窗后面的列表按钮上，keydown 目标不在卡片子树，卡片上的 React onKeyDown 根本
   不在传播路径（事件直达 window 会把设置窗一起关掉）→ 弹窗必须挂 window **捕获段**
   Escape 监听；下拉打开时经容器 `data-dropdown-open` 标记让位，由下拉自身的
   React handler stopPropagation 截停在 React root。
   env 只作兜底读取）。**后台任务模型角色（2026-08-29）**：app_settings 增
   `background_roles`（{extract, vision}，空=跟随缺省）——知识库 metadata 抽取走
   `resolve_extract_profile()`（显式>default），视觉转写 `resolve_vision()` 改
   显式 vision 角色>自动解析；PUT /settings/models 可选收 background_roles
   （不传=保留现值）；设置模型区「后台任务模型」小节两下拉。文档解析本身仍是
   确定性管线（解析不走 LLM，角色只覆盖解析后的轻任务）。
   **关不掉 bug 教训**：ModalShell 无 open 概念，SettingsModal 必须 `if (!open) return null`
   ——双栏重构时丢过一次（设置窗常驻、关闭回调全生效但 UI 永不卸载）。
   **契约 additive 扩展（2026-08-31 上下文窗口与超限自愈）**：`ModelProfile` 加可选
   `context_window`（token，None=未知；config.py dataclass 字段 + api/settings.py
   ModelBody `gt=0` /PUT/GET 三处 + contracts/dto.py，dto.gen.ts 已再生）。UI=模型
   编辑弹窗底部「高级选项」折叠区（默认收起、条件渲染而非 Collapsible——后者的
   动画包装层自带 overflow-hidden 会裁剪内部下拉面板）选预设档
   自动/32K~2M；厂商预设带建议值（**展开时才预填草稿、点保存才落库**，用户没做过
   的选择不落库；deepseek 系不填）。用途：build_agent 把窗口**合并**进 model.profile
   （`{**(model.profile or {}), "max_input_tokens": N}`——保留 langchain_deepseek
   注册表自动解析的能力键只覆盖窗口；注册表认识的模型如 deepseek-v4-flash 自带 1M
   不配置也已是比例档）→ deepagents SummarizationMiddleware（create_deep_agent 默认
   装配；state 非改写式、逐出历史落盘 `workspace/conversation_history/` 可 read_file
   回看）检测到 profile 即按窗口 85% 比例触发压缩。配套两件：①
   `_NoThinkingRetryCompletions` 加超限 400 归一化——各厂商措辞统一 re-raise 成
   langchain_core `ContextOverflowError`（实测网关原文 "This model's maximum context
   length is 1048576 tokens…"，langchain_openai 自带翻译不含此措辞），deepagents
   捕获后当场压缩重试，会话不再有超限永久报废路径；未命中措辞的其余 400 记 warning
   日志。②`_GLOBAL_DIR_NAMES` 加 `conversation_history`（逐出历史落盘处，防幽灵任务）。
   check.sh 契约漂移守卫比对的是 git 索引：再生 dto.gen.ts 后须 `git add` 才算同步。
   **契约 additive 扩展（2026-08-31 本轮文件）**：GET /messages 的 assistant 消息加
   `files`（`[{path, op}]`，`RunFilePayload` 契约模型；SSE **零改动**——completed 后
   前端先重取消息再拆活卡，files 经消息接口到达）。数据来源=`app/run_files.py`：
   run_stream 起点（task_id 解析 + 骨架自愈之后）对 `<task>/work/` 做快照，终态前
   diff 得「本轮新建/修改」清单（纯机械、无锁、不依赖工具登记；文件系统唯一真值）。
   收录范围与工作台面板同口径：work/ 下 `.md` 与 `.docx`（2026-09-06 docx 直出
   后扩收正文节文件）、跳隐藏文件与 `work/artifacts/`
   子树（产物包由产物卡展示，用户拍板；json 机器文件不可点开不收）。持久化=
   `run_traces` 新列 `files`（迁移 15，PRAGMA 探测 ALTER 同 reasoning 先例），
   与 tools/todos 同一挂载点（同 run 最终/中断消息才带）；HITL 续跑分段=
   每段起止各一次 diff、`merge_files` 合并进同一行（created 优先于 modified）。
   前端 `RunFiles.tsx` chips（正文气泡下方，「本轮文件」标签+文件图标+新建/修改
   徽标，新建=语义绿 tint color-mix 派生；默认 5 枚+「+N 个」展开）点击经
   App `openWorkbenchFile`（清产物预览态+面板收起则展开）打开工作台面板编辑；
   prop 链 ChatView→MessageList→ChatMessage（memo 比较器已同步）→AssistantMessage。
   已知限制（有意接受）：同任务并发 run 写入可能被归到另一 run（无锁铁则）；
   mtime/size 判修改=同内容重写也显示修改（parse_document 同 hash 幂等已避免
   最常见情形）；旧 run 无 files 恒 `[]`；waiting_input 暂停段的部分文件活卡
   期间不可见、续跑终态后随最终消息显示（与 tools 同挂载语义）。
   **契约 additive 扩展（2026-09-06 30M token 修复批）**：①**多中断恢复**——
   events._hitl_requests 遍历全部 Interrupt 合并 requests 并逐条附 `interrupt_id`
   （此前只取第一个：同轮双 ask_human 的第二个悬空，resume 撞 langgraph
   「must specify the interrupt id」直接打死 run，实测复现）；resume 端
   `_resume_map` 按快照 interrupt_id 分组组装 `{id: {"decisions":[…]}}` 映射
   （langgraph 对多 pending 的硬要求），旧快照无 id 走单中断旧格式；run_stream
   增 `resume_payload` 参数。②**任务上下文注入 run 内冻结**
   （`_task_context_block_frozen` + `_FROZEN_CTX`）——时间降为天级日期
   （Claude Code 同款精度；秒级时间戳每次调用都变），便签/产物清单随块在 run
   起点定格（中途更新不自动可见，模型按需 read_artifact），换 system 整 run
   字节稳定吃前缀缓存——秒级时间戳曾把主线程缓存全废（正文 run 千万级 token
   的主因；HITL 续跑同 run_id 沿用冻结块，续段缓存续上）。③**token 用量入库**
   ——`app/token_usage.py` 在模型壳 `_NoThinkingRetryCompletions.create` 返回处
   累计（主 agent+子代理共享模型实例全经过，runctx contextvars 传播），字段
   input/output/cached（openai 标准 `prompt_tokens_details.cached_tokens` 与
   DeepSeek 非标 `prompt_cache_hit_tokens` 都试）/reasoning；`runs.token_usage`
   （迁移 22，JSON）终态与暂停经 `_usage_json_final` 合并落库（HITL 分段累计），
   get_run / runs/latest 透出（additive）。④tender-body SKILL 第 0 步加
   「已写节 × 重写指令 → ask 范围（全部/指定章/仅自查不过）」不默认全量重写
   （实测整本 32 节被「重写一遍」全量重派的翻倍事故）；派发说明重排
   「短名 → 共享块（任务前缀+承诺清单）→ 节差异」——共享内容字节一致前置，
   各子代理共享更长缓存前缀。⑤**校验器误报分级**（同日二批，实测 81 次自查
   94% 一次通过、5 次未通过里 3 次是校验器误判）：残留扫描按来源分两级——
   硬级（显式名单+KB 元数据项目名/客户名）必须清零，**弱级（文件名主干）
   降为疑似提示**（「流程管理」等通用产品词误报）；validate_body 的节级残留
   命中全部弱级→warning、指引「需正文节点模式=—」降为提示并给表格类出路
   （评标索引表/分项报价表被目录形态错标为需正文的兜底）；tender-outline
   annotation.md 补「表格/索引/清单/填表类节点交付形态=模板或附件填充」。
   **契约 additive 扩展（2026-09-07 run.state 权威起点）**：run.state 载荷加
   `started_at`（epoch ms，源自 runs.created_at，sse.py 下发）——客户端刷新/
   切会话重挂后恢复 running 态，活卡「执行中 · Xs」计时按真实起点**续算**（此前
   拿不到起点、从恢复时刻重算，是可见失真）。前端 runReducer 兜底链=事件权威值
   >本地值>now（旧 sidecar 兼容）；waiting_input 对账不设起点（暂停不计时、
   续跑段从回答时刻起算语义更准，维持原状）。
   **契约 additive 扩展（2026-09-08 错误定性 code 值域 + agent.retry）**：动因=
   网关流内错误原文（"Our servers are currently overloaded…"）原样透传成红卡，
   用户分不清是模型服务的错还是程序的错；且自动重试退避期（3s/10s/30s）前端
   毫无感知、看似卡死。①`agent.error`/`run.state` 的 `code` 取值域扩展（形状零
   改动，code 本是自由字符串）：`llm_unavailable`=服务方过载/超时/断流（重试
   耗尽，agent.py worker 内判定+人话文案）、`llm_auth`=模型未配置/Key 失效
   （`AgentConfigError` 新异常类 + openai 401/403 分类）、`internal`=程序错误
   兜底、`interrupted`=sidecar 重启中断（recover_stale_runs 补写，前端同
   cancelled 中性灰「重新执行」）；cancelled 判定从「字符串相等」挪进 worker
   产出（_run_agent_stream 返回值改五元组，多了 error_code）；error 文案 sidecar
   单源拼好：**首行人话 + `\n` + 服务方/异常原文截 300 字**（前端 ErrorCard 按
   \n 拆行渲染：首行主文案、原文小字灰）。②新事件 `agent.retry`（worker 重试
   backoff 前 `_publish`，payload=attempt/total/wait_seconds）——前端 RunState
   .retrying 在正文气泡区显示 TextShimmer「模型服务不稳，正在自动重试（第 N/3
   次）…」并**清 streamText**（与 sidecar `cur_text_parts.clear()` 对齐，顺带
   修掉 agent.py docstring 记录过的「重试半截 token 前端重复」已知局限）；任何
   流增量（token/reasoning/tool）到达即清除。③runs 表加 `error_code` 列（迁移
   24；finish_run/finish_run_if_running 随 error 同写、completed 写 NULL；RunInfo
   DTO additive 透出），sse.py run.state code 优先读列、NULL 回退旧字符串判定
   （迁移前数据兼容）。前端 ErrorCard 重构：props= message/code/onOpenSettings，
   `llm_auth` 显示「去设置」按钮（重试救不了配置问题）、cancelled/interrupted
   灰卡、其余红卡「重试」。
   **内部修复+观测（2026-09-08 二批：error run 过程挂载 + per-turn 用量明细）**：
   动因=DeepSeek 欠费 402 打断整本 run（31/32 节已完成）后历史里执行过程全丢
   ——error 收尾分支创建「（任务中断）」半截消息但丢弃返回 id、`_save_merged_trace`
   写死 None，首段 error 的 run `run_traces.message_id` 恒空，GET /messages 按
   message_id 挂载查不到（DB 全部 error run 中招，含 39 分钟大 run；completed/
   暂停分支一直是对的）。修复=error 分支+外层兜底两处接住消息 id 传入
   （无新产出仍传 None=保留暂停消息挂载，续跑合并语义不变）；**迁移 25** 顺带
   回填历史孤儿 trace 到同 run 最后一条 assistant 消息（无产出的 run 不动，
   已挂载的不动；真实库副本验证：32 节 run 37 步全部挂回）。配套观测=新表
   `run_turn_usage`（迁移 25 同建）：每次模型调用一行（scope/input/cached/
   output/reasoning），scope 经 runctx 新增 agent_scope contextvar——
   `_SubagentScopeMiddleware`（挂 SUBAGENTS 两条目，与罗盘并列）在
   wrap_model_call 置 sub/finally 复位，主线程/SummarizationMiddleware 默认
   main，general-purpose 子代理挂不上记 main（接受）；`token_usage.record_usage`
   同步插行+INFO 日志「llm 用量 rid= scope= in= cached= out= reasoning=」
   （tail -f 现场观察）；归因查询=`SELECT scope, COUNT(*), SUM(input), SUM(cached),
   SUM(output), SUM(reasoning) FROM run_turn_usage WHERE run_id=? GROUP BY scope`。
   动因背景=整本 run 输入 14.49M（93% 缓存命中）需要归因主线程 vs 子代理。
   db.list_run_turn_usage(rid) 读侧；runs.token_usage 聚合零改动。
   **过程对账（2026-09-08 三批，SSE 契约零改动）**：动因=8 路子代理并发的
   reasoning/token 洪峰下 SSE 丢事件（bus 队列积压静默丢弃+断连窗口无订阅者），
   实测整本 run 第一波 straggler 的 tool.result 被挤掉→卡永远「运行中」、第二波
   7 张子代理卡零内部事件假「启动中」——sidecar 端一切正常（主代理 13:19:43
   那轮=必须全部 task 返回才继续；节文件 mtime/用量行全在跑），纯前端失真。
   修复=快照对账补「何时拉+怎么合」：①触发三处——`runReducer` seq 缺口
   （reduceSse 之外包一层发 `reconcile-trace` effect，告警从「只 console.warn」
   变「告警+自愈」；stream-batch 的跳号同款触发）+ SSE 重连 run.state +
   onError reconcile，统一走 `restoreSnapshot`（**5s 限频**，缺口风暴不连环拉
   全树快照；换会话复位）；②合并语义——`restoreSnapshot` 删「本地树非空不拉」
   闸，`snapshot` action 树非空走新纯函数 `mergeTraceTree` 字段级合并（本地
   done/error 终态优先=拉取竞态防盖回 running；本地 running+快照终态=死步修复；
   **快照 paused 不覆盖任何本地状态**——冻结职责归 run.state waiting_input
   对账，续跑乐观 revive 不被旧快照打断；children 本地空→整棵采用快照=假启动
   卡修复；text/reasoning/summary 本地缺失才补；快照独有步骤按位置插入、本地
   独有尾部附加——事件序单调）；todos/done/total 随快照重算（「任务清单 0/0」
   同源修复）；树空路径原样（全量替换+continuation revive/waiting freeze）。
   sidecar 基建零新增（`GET /runs/{rid}/snapshot`+`agent._LIVE_TRACES` 活树
   注册表已在：worker 在 tool_called/tool_result/todo_updated 边界 deepcopy 写入）。
   配套洪峰缓解：bus 队列 maxsize 500→2000、可丢事件丢弃日志 debug→info
   （info 可见=下次可诊断）。测试：runReducer.test.ts「过程对账 merge」八例
   +缺口 effect 两例；sidecar 零新测试（纯参数变更）。
   **契约 additive 扩展（2026-09-08 SSE 微合批）**：`api/sse.py` 发送层把 100ms
   窗口（`_COALESCE_WINDOW`，批次封顶 `_COALESCE_MAX=200` 条、洪峰即满即发）内的
   流式增量**按段分组合并**——以非流式事件（tool/todo/边界帧）为界切段，段内
   agent.token 归一组、agent.reasoning 按 (run, agent_id) 各归一组，text 拼接、
   seq 取组内最大值、additive 字段 **`seq_from`**=组内首个 seq（单条未合并帧也带，
   seq_from==seq）。段内跨流重排无害（token 与各子代理思考写互不依赖的缓冲），
   封段语义由段边界保证（段内增量全属于上一个边界之前）——8 路并发的增量交错
   到达，只合并「连续同类」几乎合不动，这是分组而非连续合并的原因；其余事件
   原样透传、顺序不变，run.state 对账帧与 ping 语义不变，seq 赋值点不动
   （agent.py `_publish` 每条一 seq、终态落 runs.last_seq——合批层只合并不赋号）。
   动因=token 级高频事件（8 路并发实测 ~320 帧/s）每帧过 sse-starlette 编码+TCP 写+
   WKWebView 网络进程逐帧跨进程转发+页面逐条 JSON.parse，四层成本与帧数成正比
   （真实 run 期间网络进程 70-88% CPU 的主因）；合并后线上帧数 ~30 倍↓（行业标配，
   AI SDK experimental_throttle 同思路）。
   配套前端：runReducer 两处缺口检查（sse 入口/stream-batch）连续性锚点改用
   `seq_from ?? seq`——**服务端合并跳号不再是缺口**（不触发过程对账），真丢事件
   （bus 积压丢弃/断连）的 seq_from>水位+1 照旧告警+对账；useRun 缓冲记批次首帧
   seqFrom 随 stream-batch 携带；去重水位（seq 单调）语义不变。首帧延迟上界
   +100ms（低于前端 200ms 渲染节流，不可感）。测试：test_sse.py 合批纯函数四例
   +生成器端到端一例；runReducer.test.ts seq_from 连续/真缺口两例。
   **契约 reshape（2026-09-08 messages 瘦身，非 additive）**：GET /messages 的
   assistant 消息**不再携带 tools/todos/reasoning**（标书会话实测 11.4MB、单条
   最大 2.7MB，随历史线性涨，而每次 run 收尾/invalidate/重连都全量重拉+全量
   JSON.parse+常驻缓存）；改带轻量摘要 `traceSteps`（顶层步数）/`tracePaused`
   （树内含 paused 步，SQLite json_array_length/json_tree 库内 C 层算，不把 MB 级
   JSON 拉回 Python）+ 保留 durationMs/files。完整过程新增按需端点
   `GET /conversations/{cid}/messages/{mid}/trace`（tools/todos/reasoning，
   cid 归属校验）。前端：历史过程区**点开时**才拉（ChatMessage 受控 open +
   useQuery ['message-trace', mid] enabled:open、staleTime 永久/gcTime 30min、
   加载行+失败重试），折叠头「已完成 · N 步/已暂停」改用摘要字段；运行中链路
   （SSE 活卡/`/runs/{rid}/snapshot` 重建/过程对账/HITL 装配——旁白来自
   splitMarker(content)）零改动（已审计：message.tools 全前端唯一消费点=
   ChatMessage）。dto.gen.ts 已再生。首次点开历史过程多一次本地请求（有加载
   指示），运行中显示与折叠态界面零变化。
4. **设计铁则（用户明令）**：保持简洁；冲突处理用「探测 + 提示用户裁决 + 恢复点兜底」，
   **不加锁/互斥/租约/排队**等后台协调机制；锁只允许用户不可见的 plumbing
   （原子落盘、发布进程内写锁）且需用户认可。

## 任务层与 Artifact 系统（P1–P4 + §16 任务分组目录已实施）

- **业务模型（2026-08-31 产物归任务；**2026-09-04 两态移除：单一当前版本**；取代旧
  P4/§16「正式稿/过程稿」双层模型与 08-31 的草稿/已确认两态）**：任务 = 一次投标 =
  workspace 下一个真实项目文件夹
  （`workspace/<task_id>/{sources, work, _meta}`，目录名只用不可变 id）——`sources/`
  只读来源（上传原件，AI 物理写不进）；`work/` 工作树（parse/analysis/outline/body
  过程文件 + `artifacts/<aid>/` 登记产物包）；`_meta/` 产物级谱系/暂存（UI 永不展示）。
  会话必须归属任务；产物不再分会话/任务两层——**包磁盘位置 = (artifact_id, task_id)
  的纯函数**，会话只是 provenance（last_run_id/last_thread_id）。产物=**单一当前版本**：
  发布即当前内容，无状态机；重跑覆盖（覆盖前留恢复点）。共享上下文 =
  任务名 + 进度便签 + 产物清单 + **任务工作目录**（每次模型调用经
  `_TaskContextMiddleware` 现算注入，模型路径带 `<task_id>/` 前缀），聊天记忆按会话
  隔离。仓库 workspace 根有 out/drafts/artifacts/ 等重构前遗留目录（无代码引用，
  历史化石无害）。
- **两态移除（2026-09-04，用户拍板路 A「太小心了」）**：删除草稿/已确认、确认/撤销
  确认、覆盖降级全部概念——确认按钮是「有承诺（正式成果）没机制（照样被覆盖，只是
  覆盖后降级）」的摩擦件，要么给真机制（锁定）要么删承诺，中间态最差。
  端点层：`POST /artifacts/{aid}/confirm`、`/unconfirm` 移除；`artifact.created` 载荷、
  `GET /artifacts` 行、`GET /artifacts/{aid}/meta` 三处 `state` 字段删除（**reshape 非
  additive**，前端 gen 文件同批再生——08-31 scope/promotion_proposed→state 的第二次
  reshape）。db：迁移 19 删 `artifact_index.state` 与死列 `promotion_proposed`（迁移 14
  保留在历史，v13 旧库先加后删、幂等正确）；旧包 meta.json 残留的 state/confirmed_at
  键读侧字段映射忽略。`artifact_store.write_meta` 随 confirm/降级三调用方全失而删；
  work/artifacts/ 包目录对 LLM 文件工具只读不变（fs_guard——`_meta/` 也拒写，
  **唯 `<task>/_meta/staging/` 豁免**：两步发布流的模型草稿区，publish_artifact 指示
  模型把契约 JSON 写到那里）。
- **未登记类型**一律收拢为通用笔记 `doc.note/note-md@1`（发布工具强制文档形态
  title+body_md），客户端 NoteProcessor 打开编辑；类型系统保持平台封闭注册。
- **发布与读取（单一真源）**：publish 归属=task_id 必填（只给
  conversation_id 时反查所属任务，会话仅 provenance）；read_artifact 不再有
  「正式稿→过程稿」两级读序——同契约在任务内唯一，读到的就是唯一当前内容，
  用户手改后的成果经它回流为后续 AI 输入（闭环点）。
- **删除语义（文件归任务后简化）**：删会话 = 只清转录 + 索引（db 级联）+ agent.db
  checkpoint（`delete_thread_memory`），**不动任务文件树**（产物/过程文件/来源全保留）；
  删任务 = 整任务目录 mv 到 `workspace/archive/<task_id>/`（文件归任务、归档不删
  子目录，可手工找回）+ 全部会话记忆清理；409 活跃 run 守卫不变。
- **任务级来源文件区**：上传落 `<task>/sources/`（`POST/GET/DELETE /api/files` 均必填
  `task_id`），跨任务同名文件互不影响；前端上传上下文带当前任务，无任务时禁用并提示先选任务。
- **sidecar 模块**：`app/contracts/`（平台契约目录，契约真值只在 sidecar，客户端只做映射）；
  `app/artifact_store.py`（路径派生 sources_dir/work_dir/work_artifacts_dir/meta_dir/
  staging_dir + 包存储（tmp+rename 原子替换）+ archive_task 整目录归档；meta.json 权威、
  `db.artifact_index` 可重建索引、恢复点留 3 个）；
  `app/publish.py`（**唯一登记入口**：契约存在→授权（stub：已注册契约全允许，模板待
  第二场景）→schema 校验→原子落盘）；`app/api/tasks.py`（任务 CRUD；POST 默认连带
  第一个会话，`with_conversation=false` 供输入区选择器就地新建）；`app/api/workbench.py`
  （work/ 过程文件 API：列出收 .md 与 .docx（json/隐藏文件不进列表，「面板
  不是调试器」）、读取/编辑只放行 .md、`GET /workbench/raw` 出 docx 原始字节
  （面板版式预览用，2026-09-07）、parse/ 只读（证据锚点手改=篡改原文）、
  base_hash 409 探测（拉取最新/
  保留我的）、写前 .bak 恢复点（单一上一版、互换可再撤销）、「修订=用户」头标记；
  「存为笔记」已删（2026-09-04 用户拍板砍用户手工产出通道，产物只由 AI 发布））；
  `app/tools/publish.py`（LLM `publish_artifact`，草稿限当前任务
  `_meta/staging/`（containment 防注入），未知契约收拢 doc.note）；
  `app/tools/read.py`（`read_artifact`：同契约任务内唯一当前内容）；
  `app/tools/task_progress.py`（进度便签）；`app/runctx.py`（contextvars 传
  cid/rid/task_id/thinking 思考档位）；`app/dispatch_enrich.py`（tender-body-writer
  派发说明程序拼装，治「派发塌成节名五字→子代理开局自救烧 token」，见「派发
  拼装机制」记录）；`app/run_files.py`（「本轮文件」起止快照 diff，
  见铁律 3 的 additive 记录）；`app/token_usage.py`（run 级模型用量累计，见铁律 3
  的 2026-09-06 修复批）。
  **子代理路径罗盘 + 文件工具路径自愈（2026-09-08）**：动因=run_traces 全库
  24 次子代理开局探测 path_not_found（主形态=ls work/body/… 缺任务前缀 ×14，
  另有 /workspace 段、/t_x/skills 误套、真实根前缀三形态；写错前缀的 write
  不报错自动建目录、glob/grep 静默空——事后检测接不住，故自愈层是**事前换算**）。
  两层各治一半：①`_SubagentCompassMiddleware`（子代理 spec 的 `middleware` 字段
  挂载，deepagents 原生支持；wrap_model_call 注入三行罗盘——任务前缀/全局目录
  skills·materials·knowledge/根即工作区，run 内字节稳定遵守前缀缓存铁律；主代理
  不吃罗盘，任务上下文块已含工作目录行）②`_PathRescueMiddleware`（wrap_tool_call
  事前换算：目标不存在时按固定候选序——去 /workspace 段→去真实根前缀→加任务
  前缀→全局目录剥任务前缀，规则可叠两层；ls/glob/grep 查目录、read/edit 查文件、
  **write 特殊**=原父目录在=真新文件不动、原父缺候选父在才换算防散落；命中附
  「路径已解析为…」注记；无命中时错误文案富化附罗盘让模型一步纠正。挂主代理
  middleware 列表 + 两个 SUBAGENTS 条目双挂（子代理 ToolNode 独立不继承）。边界：
  delete/execute 不参与（删除目标改写不可逆）；general-purpose 子代理（deepagents
  自动补、spec 不归我们传）两层都挂不上，历史 1 次错误频率接受。
  `work/` 是**任务级**技能工作台（`<task>/work/`：parse→analysis→outline→body 的中间
  产物；2026-08-31 由 out/ 更名），跨任务互不串台；已知管线子目录同样预建
  （`_PROCESS_DIRS` = parse/analysis/outline/outline/fragments，任务创建 + run 启动
  自愈双入口，`ensure_task_skeleton` 幂等）——2026-09-06 根治「目录空窗期 ls 吃
  path_not_found 红错」（写文件自动建父目录但 ls 撞不上，标准版式里的目录对模型
  不该是意外；空目录 UI 零可见=工作台/本轮文件只扫 .md），2026-08-29 sources/work
  先例的延伸；新管线目录（如 tender-body 的 body/）随技能落地同步加清单，
  artifacts/ 与 _meta/ 仍按需（publish/fs_guard 各自拥有）。
- **投标流水线 Phase 1（2026-08-25，入口段 2026-08-26 重构）**：旧 tender-toc skill
  及其工具已移除，新体系 =
  skill `document-parse`（**文件→markdown 独立技能**，流水线入口：check_pipeline_state
  拿候选/已确认来源/未纳入清单（2026-09-03 机械对账工具化，取代 ls+read sources.json 手工比对；
  .docx/.pdf/.txt/.md 均可解析）→ 同名双格式去重 ask → 来源集合确认（单文件默认主文件
  确认+补传窗口/多文件选主文件/新增只问角色，沿用不重问）→ 写来源确认单
  `work/parse/sources.json`（main/supplements[+role]/excluded——任务级共享状态，
  跨会话交接+重入沿用依据；**变化检测锚点=parse_document 幂等返回**：跳过=未变、
  重入时重新解析=确认后重传过，交确认门裁决——**不用时间戳**，模型写的时间戳
  不可信（confirmed_at 零点占位先例，字段已删））→ **并行 parse_document**
  （同一 assistant 消息一次性发出全部调用，ToolNode 线程池真并行——PyMuPDF 释放
  GIL；主文件失败在概况门前拦停，不串行即停）→
  **解析概况确认门**
  （流式摘要：角色/字符量/页数/标题数/解析档位/顶层章节/警示/降级声明 + ask 确认/停下，
  全部[解析跳过]时不弹门；**数字全部取自 parse_document 返回文案**（跳过同样带全量
  概况），不读 meta.json；档位与出处署名联动））+
  skill `tender-analysis`（七节要点提取，第 0 步=前置检查走 check_pipeline_state（2026-09-03
  机械检查工具化：来源确认/三件套齐备/新鲜度只报事实、零结论，裁决分支留 skill）；
  每节写完跑 validate_analysis 机器校验（coverage/出处引用两层：锚定/文件名∈来源集合/
  L 行号≤原文 md 总行数——杀编造引用，提示不是门禁、收尾前必须全绿；
  **2026-09-04 模型写头已删**：产物不带首行元信息头，修订标记由服务端程序盖）；
  purpose 下沉 references/ 文件级、单项可重跑；导航硬纪律=先读 work/parse/<文件名>/
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
  workspace containment、裸文件名回退任务 sources/）+
  **云端文档解析（2026-08-28）**：`app/baidu_ocr.py`（百度云 PaddleOCR-VL，平移老系统
  document_helpler 的 token manager + 异步任务协议：AK/SK 换 access_token（30 天缓存）
  → base64 提交 → 5s 轮询 → 下载结果拼 md；凭证 BAIDU_OCR_API_KEY/SECRET_KEY 只认 env）。
  路由纪律：**数字版 PDF 永远本地 PyMuPDF**（书签/目录链接结构识别只在本地有）；
  扫描 PDF（文本层过薄）/.doc/图片在**已配置时**路由云端**整本**解析（文档级 API 无逐页
  接口，conversion=`paddleocr-vl`，幂等检查在路由前防重复云端花费），未配置维持明确拒绝
  并提示设置入口；出处署名同 pdf-plain（OCR 标题不可回原文验证）。知识库侧转写优先级
  同步改为 baidu > VLM > 降级（KB 上传白名单加 .doc，无 baidu 时降级仅存档）。任务文件
  上传**白名单放开**（files API 不再按扩展名拒绝，类型是否可解析由解析层报人话）+
  工具 `assemble_tender`（读 work/analysis 三张机器输入表构建 MAND/TPL/REQ/SCORE 登记表
  （**行序=编号，注释行（含程序盖的修订标记/旧文件残留头）会被 registry 跳过**）+ work/outline 目录中间态
  →lineage_check→发布 `tender.directory` 成果）。
  后续 Phase：tender-flow skill（规划中）；大文件专项优化留在
  document-parse 阵地内迭代。
- **投标流水线 Phase 3·第一批（2026-09-06，tender-body 打法固化）**：skill
  `tender-body`（SKILL.md + references/{guide-format,section-writing}.md）——正文=
  逐节回应的展开，产物为 `work/body/` 过程文件（**零新契约**；目录树节点
  无稳定 id，正文文件名↔节点按「清洗后标题」对账，映射契约真值=`tools/body_contract.py`）。
  **正文形态后续已切换为 docx 直出（第三批，一节一 .docx）**——写作与修订全走
  docx_ops 工具族（建节/读视图/修订标记/合册），本段的 md 流程描述为打法起源，
  现行形态以第三批为准。
  流程五段：①check_pipeline_state（新增 `[body]` 段：指引/承诺清单存在性、已写节、
  叶子对账、目录产物 content.json mtime vs 正文 mtime 新鲜度——**该工具首次引入
  db/artifact 依赖**）②开工=生成 `work/body/写作指引.md`（每节一行：节｜模式｜依据｜
  素材｜缺口；模式=素材修订/格式跟随/推理撰写「+」组合；素材列记素材块 id、缺标【缺】
  =备料对账）→ ask_human 确认（**提问文案自带面板查看路径**——run 期间工作台列表不刷新
  的已知缺口缓解）→ ask_human 收承诺值落 `work/body/关键事实与承诺.md`（事项｜值｜
  说明；**承诺只出自清单，拍板前不写正文**）③逐节生成按指引模式路由（模板填充列待填
  清单/容器跳过/待核验问人；缺料【待补】不阻塞；待澄清内联）④validate_body 节级自查
  ⑤收尾待澄清/待补逐条点名。**素材先行五步**（references/section-writing.md）=检索→
  **列使用计划（记块 id）**→素材贴底稿→改写适配→自查——2026-09-06 用户实测教训
  「检索≠使用」的流程化修复，拷贝修订为默认模式。新工具 `validate_body(section,
  block_ids)`（tools/validate_body.py）：按文件名分流——写作指引.md 校验表完整性
  （叶子有行/模式合法/blk 可解析），其余 body md 校验占位清点（清单非错误）+旧名残留
  （复用 check_residue 抽出的纯函数 scan_residue，行为零变化）+素材使用率（与选用块
  同款归一化后 10 字 shingle 重叠率，<10% 提示未实质使用——提示不是门禁）。
  **素材跨节重复防线（2026-09-08，大地任务实测同一 625 段素材块全文进两节后加）**：
  指引校验加「同块多派=issue」（同块注入两节即逐字重复，无正当场景；文案带拆块/
  改推理撰写出路）与「不同块 id 同素材文件区间重叠派不同节=弱级提示」（治历史
  马甲块——同区间两个块名不同，失效检查发现不了）；全局模式加「节间两两查重」
  （归一化 10 字 shingle 交集/较小方 ≥50% 点名，短节 <5 shingle 跳过；重构后
  独立于承诺清单跑——清单缺失也照查）。建块侧防线在前端（materialsBlocks.ts
  overlappingBlocks + 建块弹窗 exact/partial 提示，提示不阻断），后端不做（建块
  唯一入口是用户 UI，模型无建块工具）。guide-format.md 素材列「一块只派一节」、
  SKILL.md 第 3 步全局行同步接线。
  `_PROCESS_DIRS` 加 body/（骨架自愈）；agent.py 主 prompt 路由句加 tender-body。
  本批**串行写节**（并发子代理+兄弟摘要、全局跨节审计、语义审阅、字数校准留后续
  批次）；联网检索模式=枚举预留未实现。
- **投标流水线 Phase 3·第二批（2026-09-06，前端补齐+整本并发铺开）**：①前端三小件
  ——ask_human 加可选 `guide_path` 参数（透传前端、工具体不消费，提问卡渲染
  「打开指引」按钮直开 workbench 文件，InterruptCard/ChatView 两文件）+ run 终态
  （agent.completed/error）invalidate `['workbench']`（run 期间新写的 body 文件结束
  时自动进面板列表）+ WB_NAMES 显示名；②并发铺开——agent.py SUBAGENTS 加
  `tender-body-writer` 子代理（interrupt_on:{}；先读 section-writing.md 按素材先行；
  硬纪律=承诺只用派发说明给的清单值/缺料【待补】/裁决【待澄清】带回/**禁改指引与
  承诺清单**——共享写点只归主线程，并发下唯一写边界），SKILL 第 2 步按范围分执行
  方式：单节就地、多节（≥2）同一消息并发派发（**派发 description 必带清单缺一不
  派**：任务前缀/输出路径/指引行/行号出处/承诺清单全部值/兄弟节开头摘要）、整本
  按一级章节分批派批间汇报；③validate_body 加**全局模式**（section="body" 目录）：
  承诺清单「事项｜值」每个值去空白归一化子串匹配扫全部正文节，未落正文点名
  （单向清单→正文；反向不一致属语义审阅留批次 3）。
- **投标流水线 Phase 3·第三批（2026-09-06，招标格式件拷贝+表格单元格修订）**：
  ①新工具 `docx_source_inject`（tools/docx_ops.py）——任务 sources/ 的招标
  docx 原件按「整文件或 md 行号区间（tolerate L 前缀）」元素级拷进正文节
  （现场跑解析注册表拿 element_lines 确定性定位，不依赖任务侧解析落盘——
  独立格式附件可能没走过 parse；basename+sources_dir containment，与
  material_inject 共用图片/样式/编号迁移引擎）；场景=格式跟随节与模板填充类
  格式件（投标函/授权书/一览表），pdf 原件无可拷元素维持文本成形。②
  docx_section_revise 支持**表格单元格修订**：视图逐行展开 `[T1] R2：C1=文本
  C2=（空）`（格截断 60 字、合并格标「同左/同上」）；edits 扩 {table,row,col}
  寻址，action=replace（格内段落按接受视角定位复用 _tracked_replace）/
  fill（仅限接受视角空格，新 `_tracked_fill` 整段落 w:ins 填空）；插行/删行/
  嵌套表格不支持（在 Word 中改）；`_flatten_rejected` 自校验扩到格内段落
  （表格内写坏同样拒存）。③**模板填充产出即并整本**（2026-09-06 用户拍板，
  取代「不写正文不占位」旧口径）：docx_assemble_volume 对 NON_PROSE 叶子改
  「有节文件→按树序发标题并入；无文件→跳过+计数行『模板填充类未产出 N 节
  （按附件对待）』」；check_pipeline [body] extra 侧改全叶集合（iter_leaves）、
  missing 侧维持 prose_leaves——格式件文件不再误报「无对应目录节点」。④
  validate_body docx 节占位/残留定位标签：段落 P{i}、表格行 T{t}R{r}（
  docx_ops.section_lines_labeled 单源，section_text_lines 变其投影）——与读
  视图互查，修掉表格行被标越界 P 号的隐患。SKILL/section-writing/guide-format
  /tender-body-writer prompt 同批接线（格式跟随扩拷原件支路、模板填充执行期
  二分：格式表格类拷+填空产出 vs 物理附件类维持待填清单）。
- **docx 注入机制修复批（2026-09-08 review 实证，七项全修）**：①`_merge_missing_numbering`
  原「目标已有同 numId 即沿用目标定义」在素材（历史标书，Word 的 numbering id
  从小数字分配）撞上建节模板自带的 numId 1-9/abstractNumId 0-8 时**静默错配**
  （中文编号变圆点/多级错位；read 视图与 validate 均不可见，注释「跨源冲突罕见」
  漏了素材 vs 模板这条轴）。重写为**按定义内容判定 + 冲突 id 重映射**：id 相撞且
  定义不同→分配未用新 id 迁入源定义并**改写拷贝元素上的引用**（含迁入样式副本里
  的 numPr——_merge_missing_styles 随之改传迁入副本而非源元素）；同一次调用内同
  numId 共享映射（块内列表编号连续）、跨调用各自独立序列（不同素材的同定义列表
  不得被错误并接成连续编号）；内容比对剥 id 属性与 nsid/tmpl 随机 GUID；
  w:numStyleLink 场景不重映射（内建编号样式语义跨文档一致）。合册用同一对迁移
  函数，节间 id 冲突同批修复。②**段内分节符剥离**（`_strip_inner_sectpr`，
  素材注入/招标件拷贝/合册三循环同接）：素材的横向页/分节属性随段落拷贝会中途
  生效突变版式。③**默认字体定死**（`_apply_default_fonts`，建节+合册）：Normal
  eastAsia=宋体、Heading*/Title=黑体、拉丁 Times New Roman——默认模板无 eastAsia
  声明=中文显示随打开端兜底不可控；只管程序生成内容（素材 run 级字体照旧保真）。
  ④**纯图片段 md 占位行**（parse/docx.py `![](图片)`）：图片段=空行会被「连续
  3+ 空行只留 2」折叠吃出 element_map→该图永远注入不进（静默丢图），占位行保命
  且勾选界面可见有图；已上传素材需重新上传才生效（无重解析端点）。⑤**锚定漂移
  探测**（inject 补跑映射路径）：补跑前后比对 md，「同原件确定性解析=锚定不变」
  只在解析代码不变时成立，变了拒绝注入点名重勾（探测+用户裁决）；run_parse 仍
  不 reindex（md 变了块本来就要废）。⑥**同块重复注入拦截**（强归一化只留中文+
  字母数字的 10 字 shingle，块特征在节文件终稿文本出现 ≥60% 即拒——append 语义
  下重复=翻倍无正当场景；概率防线，大幅改写后漏拦可接受）。⑦**素材使用率归一化
  强化**（validate_body._normalize 剥 md 表格竖线/分隔行/列表标题前缀、去行内
  空白）：表格为主的块不再被 md/视图格式差稀释误报「未实质使用」。附：
  _migrate_images fallback 删跨包 relate_to（外部 part 序列化损坏）改跳过；
  RT import 随之删除。历史已产出节文件不自动纠正（重注入/重写节才走新逻辑）。
  明确不做：素材库旧名元数据（零 LLM 是拍板设计，残留扫描弱级+显式名单兜底）、
  素材交叉引用跨块死链（跨文档引用无完美解，纸面无感，记录在案）。
- **标书基准 docx 模板（2026-09-08，格式与内容分离）**：动因=用户反馈
  「生成的 Word 格式难看」——建节/合册原从 python-docx 默认**英文**模板起建
  （Heading 蓝色 Calibri Light、正文不缩进、单倍行距），_apply_default_fonts
  只补字体不管版式。行业调研共识（pandoc reference-doc / python-docx 官方 /
  Anthropic docx skill / 中文标书工具链一致）：**版式全部活在一份模板的
  styles.xml，代码只挂样式名**，LLM 零参与。落地=`app/resources/
  tender_base_template.docx`（由 `sidecar/scripts/make_base_template.py`
  生成维护，改版式=改脚本重跑，37KB 入库随包分发）+ docx_ops `_new_document()`
  （建节/合册两处 Document() 换模板起建；**模板 body 带样式示例段**——打开模板
  即可直观预览/改版式（Title/H1-4/正文各一行），起建时整段剥离只留 sectPr，
  示例永不进入业务产物；模板缺失回落默认模板防打包漏带）。
  版式档=标书通行惯例（非公文 GB/T 9704 档，政采标走格式跟随拷招标件）：
  A4 上下 2.54/左右 3.18、页脚居中页码域、标题黑体分级加粗**黑色**
  （H1 小二~H4 小四）、Normal 中性（宋体小四单倍无缩进——素材拷贝的无样式
  段落与表格单元格吃它，**标书正文格式不进 Normal 防缩进/行距泄漏进表格**）、
  自定义样式 **Tender Body** 承载 AI 正文段（1.5 倍行距+首行缩进 2 字符，
  firstLineChars=200 与 firstLine=480 并写双保险——「字符」单位随字号自适应，
  twips 兜底非 Word 渲染器）。接线三处：建节初始段 add_paragraph(style=
  "Tender Body")、修订插段 _tracked_insert_after 加 style_id 参数挂 pStyle
  （_body_style(doc) 探测，模板缺样式名回落 Normal——将来用户换自带模板
  建节不失败）、合册 out 同模板起建并**删手动页码域三件套**（模板页脚自带，
  留着=双重页码）。_apply_default_fonts 删除（字体进模板）。spec datas 加
  ("app/resources", "app/resources")。测试：test_base_template_layout_on_
  create_and_assemble（字体/样式/缩进/行距/A4/页脚域/合册页码唯一）+
  insert_after 挂样式断言+视图标签 Normal→Tender Body 三处更新，572 全绿。
  界面化（用户上传自定义模板替换单槽）**明确后置**——先验证内置版式，
  用户拍板后再做（预案：设置页上传口，模板在建节时生效、换模板只影响新节）。
  **拷贝内容的模板策略（2026-09-08 用户拍板：素材库归顺、招标件保真）**：
  docx_material_inject 拷贝循环给**无样式引用的素材正文段**挂 Tender Body
  （`_ensure_body_style`——获得标书缩进/行距，与 AI 正文段同观感；此前吃
  中性 Normal 不缩进是观感割裂主因）；边界=带样式引用的段落不动（内置
  Heading 同名自动吃模板黑体分级、自定义样式走保真迁移——某段该不该归顺
  是语义判断归写作流程改写适配）、表格整表不动（单元格段落不加缩进）、
  段落 direct 格式不动（run 级字体/对齐覆盖样式，居中落款等不受影响）；
  docx_source_inject（招标格式件）**零改动全保真**（格式由招标文件定死）。
  测试 test_material_inject_body_style_adoption（归顺/表格不挂/招标件不挂
  三断言），573 全绿。
  **模板库独立入口（2026-09-08 拆库拍板：素材=内容资产/模板=格式资产分离）**：
  侧栏新入口「模板库」（Sidebar NavRow LayoutTemplate；activeView 加
  'templates'）+ `components/TemplatesView.tsx`（左列表=内置基准+用户上传
  .docx、右=docx-preview 版式预览复用 raw 字节端点；上传=入库不自动激活、
  显式「设为当前」生效——语义分离防误传即全局生效；删除两步确认 3s 复位
  （素材库教训）；「应用到任务」弹窗选任务）。sidecar `app/api/templates.py`：
  GET /templates（列表）/ POST 上传（20MB 上限、可打开校验拒损坏件、同名
  覆盖=新版语义）/ DELETE（内置不可删；删激活位回落内置）/ {key}/activate /
  {key}/raw（FileResponse 不进 dto）/ POST /templates/apply（task_id）。
  存储=data/templates/；生效位=app_settings `docx_template`（缺省=内置），
  docx_ops `_active_template_path()`（建节/合册每次现读，改模板即时生效无
  重启；用户模板无 Tender Body 样式时 `_body_style` 返回 None 正文段降级
  Normal 不失败）。**换装=`docx_ops.restyle_docx` 重建式**：当前生效模板
  起建+原内容（含修订标记）整体搬迁+`_merge_missing_styles/numbering/
  _migrate_images` 保真迁移（与素材注入同构引擎）——OOXML 引用-定义分离：
  内置样式段自动吃新模板定义、直接格式与自定义样式保真、旧版入恢复点栈；
  apply 端点 409 活跃 run 守卫（任务下任一会话）、「整本-」派生物跳过计数、
  单节失败不中断进报告（RestyleReport DTO）；**换装落盘原子化（review 批）**：
  先写 `.restyle.tmp` 成功→旧版入恢复点→replace 顶上（直接 save 留「旧已挪
  走、新写失败」窗口=节文件本体丢失）；apply 端点同步 def（磁盘密集循环丢
  线程池，不阻塞事件循环上的 SSE 心跳）；list_templates stat 竞态跳行不 500。
  前端：TemplatesView 复用 useTasks 的 ['tasks'] 全局缓存（**同 queryKey 换
  queryFn 会互相污染缓存形状**——Sidebar 任务树会拿到 {tasks} 对象崩掉）；
  上传/删除后连带 invalidate ['template-raw']（同名覆盖后预览防旧缓存 5min）。
  记录在案不修：超链接外部关系（w:hyperlink rel）不随元素迁移——存量注入
  引擎同病、换装全节搬迁暴露面更大，正文超链接罕见（政采标书），后续批与
  注入引擎一起修；换装换新 sectPr=节文件的自定义页眉页脚丢（模板页眉是
  预期行为，恢复点兜底）；空节文件 apply 计入 applied 未实际动（语义小偏差）。dto.gen.ts 已再生入库
  （TemplateInfo/RestyleResult/RestyleReport）。测试 tests/test_templates.py
  四例（CRUD+激活即生效+apply 换装/恢复点/409/404），576 全绿。前端门禁
  tsc+oxlint 绿；vite build/vitest 在本机 node 20.12 撞 rolldown styleText
  数组不兼容（存量环境问题，与本次无关，打包用常用构建环境验证）。
- **tender-body 调度优化批（2026-09-08，straggler/串行检索治理；背景=整本 40min
  解剖：批被最慢节钉死 813s、先完成子代理均空等 ~400s、批间主线程轮 1.3-2min×5、
  指引检索 32 节=32 轮串行）**：①**整本派发按「均衡分波」不再按一级章节分批**——
  check_pipeline_state `[body]` 新增分波参考：指引已生成且待写节 ≥4 时，按
  「模式基数（推理撰写3/素材修订2/格式跟随1，「+」取最高）+素材列 blk 块数」权重
  做**最少负载分桶**（LPT 贪心：降序逐项补当前最轻且未满的波，重节分散；比蛇形
  折返更均衡——2 波时 9..1 权重 LPT 分 23/22 vs 蛇形 25/20）；物理附件类不参与、
  已写节剔除、指引缺行的待写需正文叶子按权重 1 兜底补入并注明；纯机械零结论，
  「全部重写」时分波参考不含已写节、SKILL 指引模型按同口径自建。SKILL 整本分支
  同步改「一波返回、一句话汇报、再派下一波」，保留不做一次几十节齐发红线。
  ②**并发步数封顶**：`_MAX_CONCURRENT_STEPS=8` 经 stream config 顶层
  `max_concurrency` 注入（langgraph 原生语义：封顶同 superstep 并行任务，经
  ensure_config 的 ContextVar 拷贝自动传入子代理图、各图自建 executor 无死锁；
  三条执行路径——初次/HITL resume/瞬时重试——共用该 stream 调用点一处生效）；
  行业标配（Claude Code 20/OpenAI SDK/LangGraph），波容量与它**刻意对齐**=波内
  任务不排队。③**指引生成检索并行化**：SKILL 第 1 步硬纪律——同一消息并发多个
  search_references（每轮 ≤8）、按表顺序分轮，禁止一节一轮串行（线程安全已核实：
  每 db 调用私有连接+sqlite3 serialized+WAL，无需加锁）。测试：
  test_check_pipeline.py `_balanced_waves` 纯函数三例 + 分波集成三例（权重算术/
  物理附件排除/缺行兜底/已写剔除/多册键/<4 不出参考）。
- **派发契约：内部编号退出写手语境（2026-09-08，REQ 泄漏根治）**：动因=run_traces
  实证 134 条 tender-body-writer 派发里 106 条带「覆盖REQ-42至REQ-47」式编号，
  6/30 docx 正文首句与之**逐字镜像**（同句式派发 4 泄 3 净=写手侧随机，但零编号
  派发零泄漏；SKILL 清单原要求带「依据 ID」=制度化泄漏入口；「行号区段」项
  0/134 从未真实执行过）。修复=派发差异块以**要求清单**取代编号——每条=要求
  原文片段或要点＋出处（招标条款号+L 行号区间），派发前主代理按指引依据列 ID
  从目录产物 registry 解析一次（text=招标原文片段、出处照抄，机械零损耗）；
  **REQ/MAND/SCORE/TPL 编号禁止出现在派发说明**。编号保留在 analysis/目录/指引
  （机器对账货币，消费方=程序与主代理）；outline 来源标注协议不动。写手 prompt
  加防御性禁令（从指引/目录读到编号也不写进正文），正文呼应招标要求用要求内容
  或招标文件真实印着的章节/条款号（评标人可对照；内部编号他们对不上）。四文件：
  tender-body SKILL.md 派发清单/agent.py 写手 prompt/section-writing.md 通用纪律
  与格式跟随注记/guide-format.md 依据列。不加机器检查（validate_body 用户否决），
  历史 6 个泄漏 docx 不自动改。
- **派发拼装机制 + 写手开局瘦身（2026-09-08 token 治理批）**：动因=DeepSeek 实测
  整本 32 节 14.5M 输入（¥10/标书）的六成来自派发契约塌方——主代理派发说明只有
  7~10 字节名（SKILL「必带清单缺一不派」纪律管不住模型方差），32 个子代理开局
  自救 521 次 ls/grep/read 重建上下文（读回 写作指引**全文**/承诺清单/分析表/
  check_pipeline_state×32），读入的全文再被此后 ~26 轮逐轮重发。修法=派发契约
  **从纪律升机制**：`app/dispatch_enrich.py` 纯函数 `build_enriched_description`
  （瘦描述→程序拼共享上下文块；节名对账目录叶子=精确>包含>近似（SequenceMatcher
  ≥0.55 且头两名分差 ≥0.10）**唯一命中才拼**，0/多义放行不猜；产出文本零
  REQ/MAND/SCORE/TPL 编号——依据列 ID 经目录产物 `content["registry"]` 解析为
  「要求原文+出处」后即弃；块=模型原话首行（UI 卡标题）+任务前缀/输出路径/
  指引行（`_parse_guide_rows`）/素材块/承诺清单全部值（`_iter_tables`）/兄弟节
  摘要（同册 mtime 降序 ≤3 个 × 前 200 字，`docx_ops.head_text`）；无时间戳、
  同子代理 run 内字节稳定=前缀缓存铁律无伤；整体异常放行原文绝不打断 run）。
  接线=agent.py `_DispatchEnrichMiddleware`（wrap_tool_call 三层过滤：工具名=
  task → `subagent_type == _BODY_WRITER_NAME`（SUBAGENTS spec 与中间件同一常量）
  → runctx 有 task_id；挂 build_agent middleware 栈 `_PATH_RESCUE_MW` 同层；
  改写用 `request.override`，tool.called 事件仍带模型原始 args——UI 卡标题不受
  影响，拼装块由任务文件确定性推导无需事件侧同步）。配套瘦身四文件：写手
  prompt 开局纪律（只读 section-writing.md 且同一条消息并发读完、禁
  check_pipeline_state、禁读 写作指引/关键事实与承诺 全文、docx 视图 create 后
  通读一次此后按标签定位）+SKILL.md 派发段改「只写短名+特殊意图，共享上下文
  系统自动补全」（主代理每波 8 条×2-3K 字的派发输出同步省掉）+section-writing.md
  子代理段/排序句 +guide-format.md 依据列注（主代理无需手工解析 registry）。
  测试：test_dispatch_enrich.py 九例（含缩写命中实测形态「低代码产品方案」、
  零编号回归断言）+ test_agent.py 接线/禁令源码守卫。同批：error run 的 trace
  挂载修复（agent.py error 分支接住 `error_msg_id`——此前写死 None 首段 error 的
  trace 永远挂不上消息，历史过程全丢）+ 孤儿 trace 一次性回填（3 行，含 32 节
  run）。预期整本输入 14.5M→~5M、¥10→¥3~4、轮数 26/节→≤15；基线与验收口径=
  run_turn_usage 按 scope 聚合（45 万 token/节、~0.3 元/节 → ≤20 万、~0.1 元）。
  已知取舍：拼装只认 tender-body-writer（其他子代理零接触）；模型已写富文本
  （>200 字符）或含幂等标记「〔系统附」时放行原文。
- **投标流水线 Phase 2（2026-08-25；多册并发 2026-08-26）**：skill `tender-outline`
  （SKILL.md + 6 references）：
  R1 响应文件分解（首个 LLM 裁量确认点=两问测试，多方案 ask_human）→ R2 初稿 +
  **三道清理固定顺序**（①查漏补缺/②评分对齐/③走查定稿，原则从 document_helpler 老流水线
  逐字保留，各有跳过条件与声明义务，节点增删改同步维护来源标注/目录说明）→
  assemble_tender 组装发布。**单册**主线程就地做；**多册（≥2）**并发派发
  `tender-outline-writer` 子代理每册一个（同一消息全部 task 调用直接并行执行；
  子代理不继承任务上下文注入也不自动载 skill——派发 description 自带任务目录前缀/
  scope/fragment 路径，方法论让它 read_file skills/tender-outline/references/*.md；
  每册产物落 `work/outline/fragments/<册名>.md`，返回后主线程按册序合并覆盖写
  tender-response-docs.md + 规则 8 跨册去重互查；单册重做=重派该册重合并）。
  树格式红线（`- ` 开头/无编号/2 空格缩进/独立附件平级）是
  assemble 的解析协议。`tests/test_skills.py` 对全部 skill 做 frontmatter+references
  存在性校验（deepagents 加载坏 skill 只 warning 不报错，测试升级为硬失败防半接入）。
- **skill 体系 agentic 化（2026-09-03，审计+业界调研后落地）**：①机械检查下沉为工具——
  `app/tools/check_pipeline.py`（无参任务级，`[sources]/[candidates]/[parse]/[untracked]/
  [analysis]/[freshness]` 纯事实报告、零结论：裁决分支留 skill，工具说「可不可以跑」会与
  「缺节允许跑但声明影响」矛盾；**2026-09-04 freshness 换锚=文件 mtime vs 来源
  meta.generated_at**（两端均为程序/OS 可靠侧，模型写时间戳不可信——头部删除裁决
  的一部分；界面编辑/恢复会刷新 mtime，方向漏报不误报）与
  `app/tools/validate_analysis.py`（coverage/出处引用两层：锚定（同文件
  或来源文件名开头，「/」段继承「；」段独立，**括号深度 0 才分割**——golden 实测括号内
  「；后果见…」是行文注释）/文件名∈sources 集合/L 行号≤原文 md 总行数；提示不是门禁、
  收尾全绿纪律，golden case 8 件 114 条引用校准过）；document-parse 第 1 步、tender-analysis
  /tender-outline 第 0 步改接工具，**裁决规则文字不动**。②`tender-qa` 新薄技能（重构手册
  answer_query 空位）：针对已解析招标文件的单点问答——check_pipeline_state 查现状 →
  **产物优先**（对应节已在则读产物沿用出处，否则按 evidence-rules 导航回原文）→ 五类陈述
  区分作答；description 与 tender-analysis 消歧（系统提取产文件 vs 单点问答不产文件）。
  ③证据纪律上提 `_shared/evidence-rules.md`（原 tender-analysis/references/shared-rules.md
  的安全边界/证据边界/检索纪律/不确定性四段，输出段并入 tender-analysis SKILL.md 输出约定，
  原文件删除——一条规则一个家，tender-analysis/tender-qa 共用）。④三个 description 重写为
  「只写触发+关键词」（删流程概述——obra 实测流程概述会让模型走捷径），主 system prompt
  三技能段同步瘦身为路由一句话（细节唯一真源=SKILL.md）。动因：Anthropic skill 最佳实践
  （自由度光谱/确定性下沉/plan-validate-execute）+ 用户「LLM 语义、程序机械」铁律。
- **通用文本润色技能（2026-09-06 引入）**：`humanizer-zh`——第三方 MIT 技能
  （op7418/Humanizer-zh，SKILL.md 原样移植，frontmatter 加 `license: MIT`，处理流程接
  `_shared/response-guidelines.md`），去除中文文本的 AI 写作痕迹（夸大的象征意义/宣传语/
  模糊归因/破折号/三段式/AI 词汇/否定式排比等，基于维基百科 Signs of AI writing）；正文
  草稿润色等场景用，主 prompt 路由句已登记，deepagents 启动自动发现加载。
  **tender-body 接入（2026-09-07）**：section-writing.md 加「语言纪律（生成文字去
  AI 腔）」节——humanizer 规则按标书场景**裁剪重写**为 7 条（填充语/夸大修辞/模糊
  归因/强行三段式/句尾肤浅分析/空洞承诺结尾/否定式排比，各带正反例；「注入个性」
  等半数规则对标书有害不取），**作用域只管模型自己生成的文字**——素材底稿与拷贝的
  招标格式件原样保留（为去腔重写素材会掉 validate_body 素材使用率重叠率）；SKILL.md
  注意事项一行指向。主线程与 tender-body-writer 子代理经 section-writing.md 引用链
  自动覆盖，humanizer-zh 本体不动（显式润色场景仍走全量规则）。validate_body AI 词表
  弱级扫描已提议未采纳。
- **frontend**：`src/artifacts/registry.ts`（kind/schema@version → Processor 注册表 + 启动契约对账）；
  `components/processors/`（DirectoryProcessor 目录树编辑 / NoteProcessor 通用笔记）；
  `components/ArtifactOpenHost.tsx`（通用容器，未命中契约明确报不支持，**无 JSON 兜底预览**）；
  `components/TaskPicker.tsx`（新会话必选所属任务）；侧栏任务文件夹树（hover 新会话/重命名/删除）；
  产物面板 v5（任务归属 + 单一当前版本 + 业务流任务树：产物按 kind 归业务夹 +
  工作表/fragments 与产物同夹并排靠图标徽章区分；
  `work/` 过程文件经 `WorkbenchViewer` 查看/编辑——409 探测/恢复点栈/修订标记/
  行数漂移确认）+ 任务进度便签编辑；
  产物面板**行级右键菜单**（2026-09-07）：打开/打开文件夹（reveal_in_folder，仅
  Tauri 显示）/复制路径（`<task_id>/work/…`、来源行 `<task_id>/sources/…` 前缀=
  任务上下文里模型的引用口径，粘贴即可寻址）/md 另存为（前端拉全文 blob 副本
  下载，不动本体；revoke 延迟 10s——WKWebView 同步回收会吞下载）/产物恢复上一版（有恢复点才显示，复用处理器内范式）——菜单项按行类型
  差异化，通用壳 `components/ui/ContextMenu.tsx`（目录树 TreeContextMenu 抽出，
  Escape 捕获段阻断防与工作区编辑器 Esc 互触）。配套 additive：workbench 与
  files 列表行带 `abs_path`（FileItem 进契约、dto 已再生；WorkbenchFile 是前端
  手写接口直改不走 dto）。拍板缓做：docx 下载端点（打开文件夹已覆盖取文件
  诉求；版式预览的字节端点 2026-09-07 已先行落地，见下条）、「添加到对话框」（文件本就在任务工作区、agent 可直接读，价值打折）、
  产物转 md 导出；
  产物面板**docx/pdf 版式预览**（2026-09-07）：纯浏览器本地渲染、文件不出本机
  （隐私卖点）。docx=docx-preview 0.4（MIT）、pdf=pdfjs-dist 6（裸引擎自写薄层，
  不引 react-pdf 封装）；渲染体 `components/preview/{DocxPreviewBody,PdfPreviewBody}`
  经 React.lazy 分包（**项目首个代码分割先例**：docx 171K/pdf 432K+worker 1.2M
  均不进主包）。后端两 additive 字节端点（FileResponse，不进 dto）：
  `GET /workbench/raw`（限 .docx，`_resolve` 同口径含唯一后缀兜底）+
  `GET /files/{name}/raw`（sources 原件，containment 照抄 delete，无扩展白名单）；
  前端 `fetchWorkbenchRaw/fetchSourceRaw` 走 rawFetch→blob（不带 request() 的
  15s 超时，大合册传输慢）。宿主接线：`DocxView` 双模式（版式默认/文本序列化
  兜底，头部小切换；版式渲染失败自动落文本+提示一行）、新 `SourceView`
  （sources 行按扩展分流 pdf/docx/图片直出/.doc 提示另存 docx 重传）、App 第三
  预览槽 `sourceFile`（与 previewId/workbenchPath 单槽互斥）。**实测结论**：
  docx-preview 修订呈现=**接受视角**（w:ins 显示为正文、w:del 隐藏——与
  docx_ops view_lines 同口径，面板预览=接受后效果，审阅修订仍归 Word）；
  中文字体靠 workspace.css 六组 `@font-face local()` 别名（宋体→Songti SC、
  仿宋→STFangsong、黑体/楷体/微软雅黑等，Windows 同名直接命中）；
  pdf.js **必须传 `cMapUrl`+`standardFontDataUrl`**（`public/pdfjs/` 静态资源
  ~2.4MB 随 build 进 dist）——缺 cMap 中文直接画不出来（translateFont failed）；
  pdf 逐页 canvas 懒渲染（IntersectionObserver 进视口前 400px）+ fit 宽
  ResizeObserver 防抖重算 + sticky 页码胶囊。pdfjs 6.x 的 `PDFWorker`
  构造器 port 参数 .d.ts 类型写坏（null|undefined），走
  `GlobalWorkerOptions.workerPort` 模块级单例（多文档共享线程）绕开。
  Tauri/WKWebView 真壳层验证留用户前台验收。
  **写作指引/承诺清单结构化表格界面（2026-09-08）**：产物面板按**文件名分发**
  （basename=`写作指引.md`/`关键事实与承诺.md`，容忍模型 guide_path 前缀变体）
  到 `components/workbench/` 的专用视图（GuideFileView 五列表 / PromiseFileView
  三列表），其余照旧 WorkbenchViewer/DocxView。核心原则=**文件仍是唯一真值，
  界面只是另一个编辑器**：`useTableFile` 在 useAutoSave 之上包「rows↔md」双向
  （保存仍走 PUT /workbench/content，base_hash 冲突/恢复点/修订=用户标记全沿用）；
  前端**解析宽容**（`lib/workbenchTable.ts`，表头按名取列与 _iter_tables 同规则）
  **序列化唯一**（标准五列/三列表、空单元格「—」、`|`/换行清洗防拆表）；解析
  失败（无表/多表）自动落源码模式+头部手动切换（DocxView 逃生口同款）。指引表
  能力：依据 id 四色 chips 点开=SourceTraceDialog（目录产物 registry，「查看原文
  上下文」跳 parse/ 定位）；素材块 chips 显示标题、点开=块内容弹窗（素材库现有
  接口零后端改动）、失效块/同块多派/【缺】警示；状态列已写（点击直达节 docx，
  writtenSections=check_pipeline 对账规则的 TS 移植，**文件侧根级册键=空串 vs
  行侧无斜杠册键=未命名**两侧键规则不同须分开）；编辑=模式 inline toggle、节列
  锁定（须与目录逐字一致）、按目录叶子**选择器**加行（非手输）、删行两步确认。
  跨语言契约锁=`sidecar/tests/test_workbench_table_contract.py` 金样例（与
  `lib/workbenchTable.test.ts` 逐字节同源，双侧任一漂移即红）+ validate_body
  全绿断言（用户界面保存的格式=AI 自查放行的格式）。sidecar 应用代码零改动。
  `context/FileUpload.tsx` 带任务 scope（taskScope/setTaskScope，ChatView 按会话/选择器写入），
  文件 chips 只显示当前任务的文件、无任务禁传。
- **产物查看/编辑重做（2026-09-04，方案真值 `docs/artifact-view-edit-redesign.md`）**：
  ①**编辑基建统一**——`hooks/useAutoSave.ts`（纯 core `createAutoSaveCore` 不绑 React
  直测竞态 + 薄 hook 壳；请求序号守卫 + inflight 串行化挂起续存 + 5s 轮询外部更新
  （无 dirty 静默 adopt/有 dirty 置 conflict）+ `beforeSave` 闸（工作台行数漂移、
  目录结构确认都挂这里）+ 卸载冲刷先常规后 force）；三个编辑表面（Directory/
  Note/Workbench）全部换用；`SaveStateBar` 五态恒显（保存中/已保存·时间/未保存/
  失败重试/有新版本）。配套轻量探测端点 `GET /artifacts/{aid}/meta`（进 dto）与
  `GET /workbench/meta`（不进 dto）——轮询不再拉全量列表/全文；笔记补上查看态
  跟随+解析失败错误态。**工作台恢复点升级 3 个**（`<file>.restorepoints/NNNN.bak`
  不进 rglob 列表与 run_files 收录；restore 语义改「当前入栈+写回最近恢复点」
  与产物同构可再撤销；旧 `.md.bak` 栈空时自动收编为最旧一条）。
  ②**目录查看**——来源徽章（MAND/TPL/REQ/SCORE）可点开 `SourceTraceDialog`
  （registry 原文+出处自足展示）；「查看原文上下文」解析出处 L 行号 →
  `openWorkbenchFile(path, {line})` 打开 parse/ md 只读定位视图（出处不含文件名，
  取 parse/ 首个文件=单主文件场景）；树搜索（命中+祖先链裁剪渲染、全展开、
  key 加 `q-` 前缀强制重挂防折叠态残留）。
  ③**markdown 统一编辑器**——`components/editors/MarkdownEditor.tsx`（CodeMirror 6
  `@uiw/react-codemirror`+`@codemirror/lang-markdown`，源码/分屏/预览三态、viewOnly
  只读预览、readOnly 只读源码（定位视图）；CM 主题走 workspace.css 的 `.md-editor`
  段消费 token（dark 自动跟随）；受控纪律=父组件仅无 dirty 时换 value）。笔记正文
  与工作台 textarea 全部替换；分屏滚动同步有意不做。
  ④**目录树编辑操作集**——`processors/directoryTree.ts` 纯函数库（moveTo 三落点
  above/below/inside 跨层级+整子树 relevel、promote/demote、isDescendant 拦截、
  5 级封顶、`structureSignature` 结构签名=节点索引路径集合（增删/移动变、改名不变），
  vitest 10 例）；`processors/DirectoryEditor.tsx` 编辑态组件（原生 HTML5 拖拽三区
  落点上 25%/下 25%/中 50%=并入子节点、**有意不引 dnd-kit**（现有同级拖拽原生实现
  扩展中间区 +30 行 vs 重构 200 行）；右键菜单浮层（升级/降级/上下移/增删、防溢出
  视口、Escape/外点关）；undo/redo 50 步快照栈（编辑会话内、Cmd+Z、保存成功不清
  ——「刚保存想撤销」是合法预期）；结构性变更确认条挂 beforeSave（签名≠已确认
  基线即拦，用户「继续保存」前移基线、纯改名不触发、告知不是门禁）。
  **UI 风格统一纪律（用户明令 2026-09-04）**：`tokens.css` 加 `--Color-info`（蓝，
  TPL 徽章），来源徽章四色=MAND danger/TPL info/REQ brand/SCORE warning +
  color-mix 12% tint 派生（暗色自动适配）；三个编辑表面 15 处硬编码调色板类清零
  （amber 横幅→warning token、拖拽插入线 rgb→brand、red→destructive）；新增组件
  一律语义 token，禁 Tailwind 调色板类与硬编码色值。
- **并发/冲突**：无租约无互斥——任务内 run 随便并发；发布即覆盖（覆盖前自动留恢复点，
  `POST /artifacts/{id}/restore` 可恢复且可再撤销）；`content_seq` 是探测器不是锁
  （三个编辑表面统一 useAutoSave 5s 轻量探测，外部更新时无本地改动静默跟随、
  有则弹「拉取最新 / 保留我的=force 覆盖」）。
- **新契约接入**按设计文档 §13 五步打包：契约定义→SKILL.md 指导→客户端 Processor→
  模板集合→全链路验收；禁止半接入（客户端启动对账会 console.warn）。
- **已知限制**：任务模板未引入（授权 stub 全允许）；产物编辑不发 SSE（不在
  run 内无 seq 宿主），前端操作后自行刷新产物列表。

## HITL（human-in-the-loop，2026-08-25）

- 用 deepagents 原生 `interrupt_on`（`agent.INTERRUPT_ON`，当前一项：`ask_human`
  `allowed_decisions=["respond"]` 问答型。`task` 派发审批门禁已删——2026-09-06
  用户拍板：每次派发子代理都弹审批卡太吵，直接执行；恢复加回
  `"task": {"allowed_decisions": ["approve", "reject"]}` 即可）。给其他工具加门禁改
  这里。子代理 spec 的
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

## 知识库与写作素材库（双域手工模型，2026-09-04 定稿；v3 自动拆分已废）

跨任务共享资料层，两个彻底分离的域：**知识库（事实层）**——公司有什么/做过什么
（资质证书、合同案例、人员证书、财报、业绩、公司介绍），LLM 轻抽取+事实纪律；
**写作素材库（素材层）**——用户从历史标书/范文里**手工勾选**的章节块+备注，零 LLM
裁定（块的价值判断归用户，程序只做机械）。2026-09-03 的 v3 内容角色模型（chapter-copy
三形态/decompose 自动拆分/topics 词表）实施后次日在 09-04 被用户拍板简化取代；检索侧
search_references 只查素材块一种形态。

- **知识库管线（`knowledge/ingest.py`）**：上传 → 解析（数字版本地；扫描件/.doc 已配
  百度 OCR 路由云端、未配降级仅存档）→ 切段即 searchable → 三合一抽取
  （`extract.py` 一次 LLM：类型+时间/身份锚点+内容说明 statement——事实类=逐条关键
  内容带（第N页）锚点，写法类=2–3 句结构概览；说明进 §statement 检索段，命中标
  「AI 整理·数字须回原文核对」）→ 图片抽取（`images.py` 确定性零 LLM，2026-09-04
  降级重构：仅供内容页「本文档图片」折叠区核实证书红章/签名，不进检索、与素材库
  脱钩）。能力状态机 stored→searchable→typed→enriched 派生不落库，每步完成即对外
  生效，失败逐层降级不阻塞。
  **检索问题 questions（2026-09-08，WeKnora 生成问题思路的文件级落地）**：抽取同批
  生成 3–6 个「用户会怎么问」短问句（≤20 字；归类词必须与文中内容真实对应——项目
  是医院的才许写「医疗行业」，防编造的唯一防线；写法类不生成），独立 `§questions`
  检索段（与 §statement 同构：行号空、business 版优先、留空沿用建议版）——纯字面
  检索下补「用户问法↔资料写法」措辞缺口（正文印「医院」、用户问「医疗行业项目」）。
  命中渲染=「检索问题」标注+引用键 `kb:<id>:q`+摘录取问句清单，**不加 AI 整理注**
  （问句不含事实，答案以原文为准）。PUT /metadata 可选收 questions（≤10 条、单条
  ≤40 字、坏形状 422）；前端信息页增删改（StatementCard 显 pills）。**已确认条目的
  采纳交互（2026-09-08 重做，取代信息页单字段「换用 AI 建议」按钮）**：识别完成
  toast + 详情页顶部常驻更新条（摘要=新增 N 个检索问题/说明有改动/N 处字段变化/
  类型建议），点「对比采纳」展开逐区卡片（检索问题 pills/说明双栏预览/字段 旧→新/
  类型），各区独立「采纳建议/保留我的」（纯新增默认采纳、有旧值默认保留），保存才
  落确认版——守住「确认不被静默覆盖」同时把差值亮到明面上；diff=`computeKbDiff`
  纯函数（只列可采纳差异：建议侧为空不列），识别中隐藏、「知道了」按 updated_at
  会话级消隐（新一轮识别落地自动回来）。重新生成走既有 retrigger 整条重抽。
  KbMetadata DTO
  additive 加 questions（dto.gen.ts 已再生）。
  **锚点回文核对+自动确认（2026-09-08，WeKnora 调研产物「两主人模型」）**：动因=
  待确认清单=没人处理的欠账单（确认非门禁——未确认照常检索/时效/关联消费，确认
  只改徽章/排序/合成段），同 09-04 砍产物确认按钮的「有承诺没机制」病。不做 LLM
  自报置信度（无机制数字），做 `knowledge/autocheck.py` 纯函数核对：身份锚点
  （project_name/client）归一化（NFKC+去空白）回 md 子串命中抓编造；时间锚点四格式
  解析（YYYY-M-D/年月日/./・/含全角，日可缺）任一规范化形态命中；period 年份命中；
  valid_until≥valid_from 一致性；**事实类 time_fields 非空却零时间锚点=可疑**
  （时效全瞎），company_profile/other/写法类零锚点平凡通过。两主人：机器守
  suggested——`_extract` 收尾跑核对（retrigger 同路径=每次重抽重核对，无陈旧盖章
  漏洞），全过→review_status=confirmed+**business=suggested 副本带
  `confirmed_by:"auto"` 标记**（写副本是必须的：reindex「条目信息（人工确认）」
  合成段与前端全部确认展示挂 business 存在性，自动=人工同显；顶层标记不进合成段）；
  有败→pending_review+business 清 None+check_result 点名原因（「未在原文找到该
  日期——疑似抽取有误」）。人守 business——人工确认/编辑过（business 无 auto 标记）
  重抽只更新 suggested/check_result 展示，确认状态与 business 永不动。安全性=核对
  过≠语义对（日期语义错位抓不住），但此类错误现状同样消费，自动确认只改标签排序
  不改机器消费行为，风险面零变化；语义防线依旧在检索纪律层。kb_items 新列
  check_result（迁移 26；`_KB_ITEM_COLS`/`kb_update_item` 白名单/business+check
  可置空三处同步），KbItem DTO additive 加 check_result（KbAnchorCheck{status,
  results[{field,label,ok,detail}]}，中文结果串后端拼好仿 freshness）+
  KbMetadata.confirmed_by，dto.gen.ts 已再生。启动回扫 `autocheck_sweep()`
  （main.py lifespan，rebuild_kb_index 之前——存量 pending+extract done+无 business
  +**从未核对过**的条目补跑，检索段由随后的全量重建收口；范围排除已核对项=幂等）
  上线当场清欠账。前端 InfoForm 顶部 AutoCheckBar：显示条件=有 check_result 且
  非人工所有（`!business || business.confirmed_by==='auto'`，人已拍板不再显示）；
  pass=success 胶囊「程序核对通过」+命中项一行、fail=逐条警示行（`.kb-check*`
  样式语义 token）；StatusDot/详情头/胶囊/StatementCard 零改动（全挂
  review_status/business 存在性）。检索侧零改动（徽章只看 review_status）。
  测试 test_knowledge_autocheck.py（纯函数+回扫幂等）+test_knowledge_ingest.py
  四例（自动确认/败留待/重抽降级/人工免疫），595 全绿。
- **类型注册表（`knowledge/types.py`，12 类，role=fact/writing）**：机器消费锚点字段=
  时间四字段+project_name/client（freshness/来源标注/关联核对/残留扫描依赖）；其余
  内容不预设字段。
- **角色派生（`knowledge/roles.py`，命中级纯计算）**：fact 类命中=fact-verified；写法
  类文件**章节标题命中业绩词表**（业绩/案例/成功/客户/合同/验收/项目经验/实施案例，
  启发式会漏会错，漏的走 unknown+纪律兜底）=fact-candidate；写法类其余段=
  writing-reference。
- **素材库（`knowledge/materials_lib.py` + `api/materials.py`）**：自己的文件区
  （materials/files/）+ 解析产物（materials/parse/<stem>/{md, outline.json, blocks.json}；
  docx 另产 **element_map.json**=「body 元素全序索引+起止行号」，是 docx_material_inject
  元素级注入的映射真值，旧解析幂等重跑补产；**重解析收尾同步块索引/检索段并探测
  行号漂移**——`POST /materials/files/{fid}/reparse`（前端有按钮）重跑 run_parse，
  有块且 md 行数变化时 ready+error 提示复核勾选区间、行数不变则区间安全（blank→
  占位行 1:1）。**图片可见性批（2026-09-08）**：动因=云枢素材 87 图、正文 run 25 条
  注入调用 0 次=整本 0 图——docx 纯图片段占位行 `![](图片)`（一段一行）是图的唯一
  md 可见形态，块级含图数=区间内占位行计数（`block_image_count`，段内嵌图/一段多图
  不可见、旧解析无占位恒 0 须重解析）；search_references 命中行/块骨架 N>0 标
  「含图 N 处」+硬话「必须注入——自写无法带图」（docx 直出管线无放图通道，图片只
  随 docx_material_inject 元素拷贝进正文；SKILL/section-writing/写手 prompt 同步
  「禁止跳过注入直接自写」+修订不删〔图×N〕段）。流程=上传（.docx/.pdf/.txt/.md/.doc
  ≤100MB）→ 后台纯机械解析（无抽取无图片）→ 用户目录树勾选章节区间建块（多区间+
  备注；行号夹紧/嵌套区间去重叠归程序）→ 块进检索（复用 kb_segments，item_id=mt_
  前缀；事实检索按 kb_items 映射过滤天然隔离）。**块 id 只在 blocks.json 生命周期内
  稳定**（删块=引用失效，模型侧报「素材块不存在」引导重新检索）。引用打点
  use_count/last_used_at（检索命中+注入落盘都算）。
- **双检索工具（`tools/search_knowledge.py`）**：`search_company_assets`（问事实：全库
  召回，verified 排前/candidate 附标「业绩候选·须核对」+项目名匹配关联证明材料/纯
  写法段排除；纪律=拟投入承诺不是现状事实、数字一律重核、过期证书不得写有效）；
  `search_references`（问写法/拷贝：查素材库块——标题+用户备注+多区间行号+真实字数+
  摘录+引用键 `mt:<fid>:b:<块id>`，命中文件的块全景骨架附后；**docx 原件块优先
  docx_material_inject 元素级注入再定向修订**，非 docx 原件按文本参考改写；范文警示
  常驻）。统一命中头（角色｜类型｜状态｜时效）+ evidence key + [evidence] JSON 行
  （含 role，validator 消费格式已冻结）。
- **`tools/check_residue.py`（check_name_residue）**：拷贝修订第一道防线——来源条目
  project_name/client/文件名主干自动入扫描表+显式名单，机械扫残留行号（行业第一大
  事故=提交稿残留旧机构名）。
- **API**：`api/knowledge.py`（/kb/types、/kb/badge、上传、items 列表/详情/内容/raw/
  图片、PUT metadata（statement/锚点字段确认）、retrigger、delete）；`api/materials.py`
  （/materials/files 上传/列表/删除+outline 目录树、/files/{fid}/reparse 重解析
  （2026-09-08 失败重试入口，照抄 KB retrigger 单飞语义；配套 db.recover_stale_mt
  启动对账把残留 pending/parsing 置 failed，失败行前端有「重试」钮）、
  /materials/blocks CRUD+content——建块=勾选区间+标题+备注）。
- **迁移 18**：v3 三表 DROP 重建历史；素材库是 mt_ 前缀新表族，v3 的 materials.json
  decompose 真值已随模型更换作废。
- **frontend**：`KnowledgeView.tsx`（左栏**平铺+类型下拉+待确认胶囊筛选**——五轮收敛
  2026-09-04，分组头已删；详情三 tab——内容 tab 含说明卡（AI 整理标签+锚点文本）、
  信息 tab=说明编辑+锚点字段+类型下拉）；`MaterialsLibraryView.tsx`（侧栏「写作素材库」
  **一等入口**：文件/块浏览）。
- **agent 注入**：`_kb_summary_line` 双域口径（事实层按 role 分类计数+待确认数+素材库
  文件数块数；指引双工具+拷贝素材后残留扫描）。
- **检索技术**：FTS5 jieba+bigram 同源分词、无向量；语义层=agent 迭代查询。
- **有意不做**：任务成果自动回流、版本替换机制（删旧传新）、向量检索（视召回评估）、
  素材块级编辑、素材自动拆分（decompose 已废——用户明令块的价值判断归人）。

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
  字段清单须与前端 `api/sse.ts` 的 AgentEventData 人工同步））；frontend/Rust 暂无测试 runner。
- e2e 冒烟：`cd sidecar && uv run pytest -m e2e`——spawn 真实 sidecar 子进程（独立端口 +
  隔离 DATA_DIR）跑一轮真实 LLM 对话，断言 run 完成、SSE seq 单调无重复、tool_call_id
  唯一、messages/trace 落库。需要 `.env` 有效 key（无则 skip）。日常 `uv run pytest` 默认
  排除 e2e（保持秒级）；**动 events/agent/bus/SSE 相关代码后应跑一次 e2e**。

## 代码约定

- **sidecar**（Python ≥3.12，uv 管理）：
  - `app/events.py` 是 LangGraph 流 → §5.5 事件的**唯一适配层**；库 API 变化只改这里。
    **updates 只翻译真实执行节点（2026-09-08）**：工具事件（tool.called/tool.result）
    只从 node∈{model, tools} 的更新产出——中间件钩子伪节点（deepagents
    `PatchToolCallsMiddleware.before_agent`、langchain `SummarizationMiddleware.
    before_model`）的 messages 是**状态重写不是新工作**：新 run 开头发现上一 run
    中断遗留的悬空 tool_calls 时，before_agent 会把整段历史消息原对象+补插的取消
    ToolMessage 一并写进 updates，照译会把上一轮全部工具步骤重放进本轮的 SSE/trace
    （实测中断 run 的下一轮 trace 混入 12~64 个外来 tool_call_id）。todos 提取不受
    白名单影响。加新中间件若在伪节点写 messages，天然被跳过（正是期望行为）。
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
  - **前缀缓存铁律（2026-09-06 30M token 事故的教训）**：进 system/请求前缀的任何内容
    必须整个 run 内字节稳定——每次调用现算的易变项（时间戳/便签/产物清单）一律 run
    冻结（`_task_context_block_frozen` 先例）或挪请求末尾；模型供应商前缀缓存按字节
    前缀匹配，断点之后全部按未命中全价计费（DeepSeek 命中价约 1/10-1/30）。新加
    「每次模型调用注入 XXX」类功能前先过这道检查。
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
  - 打包分发（2026-09-07 已实施，取代原「生产分发限制」备注）：PyInstaller one-file 冻结
    sidecar → `bundle.externalBin` 注册（`binaries/tender-agent-sidecar`，构建产物带
    `-$TARGET_TRIPLE` 后缀）→ tauri-plugin-shell `app.shell().sidecar()` 拉起（capabilities
    加 `shell:allow-spawn`，scope 限定本 sidecar 二进制）。sidecar.rs 启动探测**双模式**：
    `sidecar_dir()` 下有 pyproject.toml=dev（走 `.venv/bin/python` 原路径，`npm run dev`
    零变化），否则 bundled（shell 插件拉起 + `DATA_DIR=app_data_dir` env 注入——one-file
    下 Python `__file__` 在临时解压目录 `_MEIPASS`，不注入数据全丢；config.py 的 env 优先
    逻辑零改动生效；RESOLVED_DATA_DIR OnceLock 供 export_diagnostics/reveal 前缀校验同源）。
    supervisor（healthz nonce/退避/熔断/稳定窗口）全保留，仅句柄双形态化：dev=std Child
    （try_wait 轮询+进程组 SIGKILL），bundled=CommandChild（**无 wait/try_wait**——stderr
    转发线程消费 CommandEvent 通道置终态标志，通道不消费会堵死子进程；退出分类共用
    classify_termination 纯函数）。杀进程 bundled 模式=SIGTERM→轮询终态≤3s→按端口
    `lsof -ti tcp:PORT` 清孤儿→SIGKILL（**实测 macOS one-file 确是 bootloader+python 双进程**，
    只杀 bootloader 留孤儿占端口（tauri#11686 同款）；SIGTERM 会被 bootloader 转发、整树
    正常退出），Windows=taskkill /T /F。打包三件套在 sidecar/：`run_frozen.py` 冻结入口
    （app/main.py 是相对导入不能直当入口脚本；`--smoke` 冻结自检八项：pymupdf/jieba/
    FTS5/trafilatura/openai 懒资源/agent 栈/server 栈/app.main）+ `tender-agent-sidecar.spec`
    （datas 收 `app/skills/**`；collect_data trafilatura+**justext**（stoplists 是冻结冒烟
    抓的漏）；collect_submodules 保底 deepagents/langchain 全家/openai——3.x 懒资源代理是
    纯字符串 import_module；**upx=False 硬性**，UPX 压缩产物过不了 codesign）+
    `build_sidecar.sh`（**独立 .build-venv**=uv 管的 python-build-standalone 3.12 按
    uv.lock 装，绝不用日常 .venv——它是 miniforge 软链，conda dylib 指前缀、用户机必炸；
    锁版 pyinstaller==6.14.1；产物落 `src-tauri/binaries/`（gitignore））。
    `npm run build:sidecar` / `build:release`（先 sidecar 后 tauri build，有意不塞
    beforeBuildCommand）。冒烟基线：89MB 二进制、冷启动至 healthy 11-14s（bundled 探活
    窗口放宽到 60s）。已知坑备案：Windows NSIS 覆盖安装不更新 externalBin（tauri#15134，
    靠版本号变化规避）；未签名 one-file 杀软误报偏高（正式 Developer ID 签名大幅缓解，
    Tauri bundler 会自动逐个签 externalBin 并公证）；macOS universal 需 lipo 合成 sidecar
    或发双包；Linux /tmp noexec 需 `--runtime-tmpdir`。签名/CI/Linux/自动更新器=后续门未做。
  - ~~钥匙串用 macOS `security` CLI 子进程~~（2026-08-29 已移除：Key 改存 app.db，见铁则 2；
    历史：keyring crate 在此 macOS 写 Data Protection 钥匙串，`security` CLI 不可见）。
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
- 解析支持 `.docx`（python-docx）与 `.pdf`（PyMuPDF 原生提取，无 soffice 依赖）；
  扫描 PDF（文本层过薄）与 `.doc`/图片在**已配置百度云文档解析**时路由云端整本 OCR
  （`app/baidu_ocr.py`，conversion=`paddleocr-vl`），未配置明确拒绝并提示设置入口
  （`.doc` 另可 Word 另存 `.docx` 后上传）。
