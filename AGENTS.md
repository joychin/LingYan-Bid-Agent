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
   收录范围与工作台面板同口径：work/ 下 `.md`、跳隐藏文件与 `work/artifacts/`
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
4. **设计铁则（用户明令）**：保持简洁；冲突处理用「探测 + 提示用户裁决 + 恢复点兜底」，
   **不加锁/互斥/租约/排队**等后台协调机制；锁只允许用户不可见的 plumbing
   （原子落盘、发布进程内写锁）且需用户认可。

## 任务层与 Artifact 系统（P1–P4 + §16 任务分组目录已实施）

- **业务模型（2026-08-31 重构定稿：产物归任务 + 草稿/已确认两态；取代旧 P4/§16
  「正式稿/过程稿」双层模型）**：任务 = 一次投标 = workspace 下一个真实项目文件夹
  （`workspace/<task_id>/{sources, work, _meta}`，目录名只用不可变 id）——`sources/`
  只读来源（上传原件，AI 物理写不进）；`work/` 工作树（parse/analysis/outline/body
  过程文件 + `artifacts/<aid>/` 登记产物包）；`_meta/` 产物级谱系/暂存（UI 永不展示）。
  会话必须归属任务；产物不再分会话/任务两层——**包磁盘位置 = (artifact_id, task_id)
  的纯函数**，会话只是 provenance（last_run_id/last_thread_id）；产物状态两态存包内
  meta.json + `db.artifact_index.state`（draft/confirmed，迁移 14）。共享上下文 =
  任务名 + 进度便签 + 产物清单 + **任务工作目录**（每次模型调用经
  `_TaskContextMiddleware` 现算注入，模型路径带 `<task_id>/` 前缀），聊天记忆按会话
  隔离。仓库 workspace 根有 out/drafts/artifacts/ 等重构前遗留目录（无代码引用，
  历史化石无害）。
- **确认（旧「转正」，2026-08-31 改盖戳语义：不复制不搬家）**：AI 发布的产物恒为
  draft；「确认为正式成果」由用户点击 `POST /api/artifacts/{aid}/confirm`（原地写
  meta.json.state + 索引、留恢复点，`/unconfirm` 可撤销——面板已确认行的 hover
  动作即撤销入口，直接执行无弹窗；两端点均不发 SSE——不在 run 内无
  seq 宿主，前端 confirm 成功后自行刷新产物列表）。LLM 永远无法把产物置为
  confirmed（发布工具恒写 draft；work/artifacts/ 包目录对 LLM 文件工具只读，
  fs_guard——`_meta/` 也拒写，**唯 `<task>/_meta/staging/` 豁免**：两步发布流的
  模型草稿区，publish_artifact 指示模型把契约 JSON 写到那里）。同重构顺带
  **reshape**：`artifact.created` 载荷的 scope/promotion_proposed 两键一次性替换
  为 `state`（draft/confirmed）——非 additive，前端 events.gen.ts 同批再生。
  发布覆盖已确认产物时**先降级 meta 再写内容**（崩溃窗口 fail-safe=草稿+旧内容）。
- **未登记类型**一律收拢为通用笔记 `doc.note/note-md@1`（发布工具强制文档形态
  title+body_md），客户端 NoteProcessor 打开编辑；类型系统保持平台封闭注册。
- **发布与读取（2026-08-31 单一真源）**：publish 归属=task_id 必填（只给
  conversation_id 时反查所属任务，会话仅 provenance）；read_artifact 不再有
  「正式稿→过程稿」两级读序——同契约在任务内唯一，读到的就是唯一当前内容
  （已确认或草稿），用户手改后的成果经它回流为后续 AI 输入（闭环点）。
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
  （work/ 过程文件 API：列出/读取/编辑**只放行 .md**（json/隐藏文件不进列表，「面板
  不是调试器」）、parse/ 只读（证据锚点手改=篡改原文）、base_hash 409 探测（拉取最新/
  保留我的）、写前 .bak 恢复点（单一上一版、互换可再撤销）、「修订=用户」头标记、
  存为笔记）；`app/tools/publish.py`（LLM `publish_artifact`，草稿限当前任务
  `_meta/staging/`（containment 防注入），未知契约收拢 doc.note）；
  `app/tools/read.py`（`read_artifact`：同契约任务内唯一当前内容）；
  `app/tools/task_progress.py`（进度便签）；`app/runctx.py`（contextvars 传
  cid/rid/task_id/thinking 思考档位）；`app/run_files.py`（「本轮文件」起止快照 diff，
  见铁律 3 的 additive 记录）。
  `work/` 是**任务级**技能工作台（`<task>/work/`：parse→analysis→outline→body 的中间
  产物；2026-08-31 由 out/ 更名），跨任务互不串台；过程子目录按需创建，启动不预建
  （仅任务创建 + run 启动自愈补 sources/work 骨架，`ensure_task_skeleton` 幂等）。
- **投标流水线 Phase 1（2026-08-25，入口段 2026-08-26 重构）**：旧 tender-toc skill
  及其工具已移除，新体系 =
  skill `document-parse`（**文件→markdown 独立技能**，流水线入口：ls 任务 sources/ 枚举候选
  （.docx/.pdf/.txt/.md 均可解析）→ 同名双格式去重 ask → 来源集合确认（单文件默认主文件
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
  skill `tender-analysis`（七节要点提取，第 0 步=前置检查：sources.json 就绪+产物齐备+新鲜；
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
  （**行序=编号，产物头部 HTML 注释行会被 registry 跳过**）+ work/outline 目录中间态
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
  每册产物落 `work/outline/fragments/<册名>.md`，返回后主线程按册序合并覆盖写
  tender-response-docs.md + 规则 8 跨册去重互查；单册重做=重派该册重合并）。
  树格式红线（`- ` 开头/无编号/2 空格缩进/独立附件平级）是
  assemble 的解析协议。`tests/test_skills.py` 对全部 skill 做 frontmatter+references
  存在性校验（deepagents 加载坏 skill 只 warning 不报错，测试升级为硬失败防半接入）。
- **frontend**：`src/artifacts/registry.ts`（kind/schema@version → Processor 注册表 + 启动契约对账）；
  `components/processors/`（DirectoryProcessor 目录树编辑 / NoteProcessor 通用笔记）；
  `components/ArtifactOpenHost.tsx`（通用容器，未命中契约明确报不支持，**无 JSON 兜底预览**）；
  `components/TaskPicker.tsx`（新会话必选所属任务）；侧栏任务文件夹树（hover 新会话/重命名/删除）；
  产物面板 v4（任务归属 + 草稿/已确认两态 + 业务流任务树：目录产物已确认置顶 +
  行内「确认」盖戳（不复制可撤销）+ 工作表/fragments 与产物同夹并排靠图标徽章区分；
  `work/` 过程文件经 `WorkbenchViewer` 查看/编辑——409 探测/.bak 恢复/修订标记/
  行数漂移确认）+ 任务进度便签编辑；
  `context/FileUpload.tsx` 带任务 scope（taskScope/setTaskScope，ChatView 按会话/选择器写入），
  文件 chips 只显示当前任务的文件、无任务禁传。
- **并发/冲突**：无租约无互斥——任务内 run 随便并发；发布即覆盖（覆盖前自动留恢复点，
  `POST /artifacts/{id}/restore` 可恢复且可再撤销）；`content_seq` 是探测器不是锁
  （目录编辑器 5s 轮询，外部更新时无本地改动静默跟随、有则弹「拉取最新 / 保留我的=force 覆盖」；
  NoteProcessor 不轮询，靠保存 409 兜底同一裁决）。
- **新契约接入**按设计文档 §13 五步打包：契约定义→SKILL.md 指导→客户端 Processor→
  模板集合→全链路验收；禁止半接入（客户端启动对账会 console.warn）。
- **已知限制**：任务模板未引入（授权 stub 全允许）；产物确认/编辑不发 SSE（不在
  run 内无 seq 宿主），前端操作后自行刷新产物列表。

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
    指数退避重启（上限 3 次）→ 退出杀进程树并 wait 回收。env 只注入 plumbing
    （SIDECAR_TOKEN + TENDER_HEALTHZ_NONCE）——模型配置与凭证 2026-08-29 起在 sidecar
    的 app.db，钥匙串/MODEL_KEYS 注入/设置类 command（set_model_key 等）已全部移除；
    `stopping` 标志保证应用退出后 supervisor 不再拉起孤儿进程。
  - 生产分发限制：目前用 `Command` 直接 spawn `.venv/bin/python -m uvicorn` + 自定义 supervisor
    （随机端口/token 注入/healthz 探活/退避重启），dev 期没问题，甚至比官方 `sidecar()` 更强
    （官方不做健康检查/鉴权/重启）；但 `tauri build` 分发时打包应用找不到 Python。届时须转官方模式：
    PyInstaller 把 sidecar 打成二进制 → `bundle.externalBin` 注册（`-$TARGET_TRIPLE` 后缀）→
    shell 插件 `sidecar()` 拉起（capabilities 配 `shell:allow-spawn`），保留现有 supervisor
    探活/重启逻辑、仅把 python 路径换成打包二进制。
    参考 https://github.com/dieharders/example-tauri-python-server-sidecar
  - ~~钥匙串用 macOS `security` CLI 子进程~~（2026-08-29 已移除：Key 改存 app.db，见铁则 2；
    历史：keyring crate 在此 macOS 写 Data Protection 钥匙串，`security` CLI 不可见）。
  - 已装插件仅两枚官方 plumbing：`tauri-plugin-single-instance`（须第一个注册——GUI 双开会撞
    agent.db 单库 checkpoint，二次启动聚焦已有窗口，不做互斥协调）+ `tauri-plugin-window-state`
    （记住窗口大小/位置）；均纯 Rust 侧、零 IPC 权限、前端零依赖。
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
