# 决策日志（decision log）

> 本文件是 AGENTS.md 2026-09-16 拆分时移出的**历史批次存档**：每个批次的设计动因、
> 根因分析、被否方案与「明确不做」拍板的原始记录，按域分六章，条目保持拆分时的原文
> （逐字搬移，仅整理章节归属；章内条目按原文件行序=撰写先后）。
>
> 与 AGENTS.md 的分工：**AGENTS.md 只写现行规则，本文件写「为什么长这样、什么被否过」**。
> **今后新批次的记录写这里，不再写 AGENTS.md**——仅当批次改变了现行规则时，同步改写
> AGENTS.md 对应条目。
>
> 用法：改动相关代码前按域查同章条目，或全文 grep 关键词。条目内的互引（「见铁律 3」
> 「见下节」等）指向拆分前的原文结构，按关键词 grep 定位即可。

## 目录


### 一、契约与运行时（SSE 事件 / API 形状 / agent 中间件 / 工具基建 / token 与内存治理）

- L40-535 *契约 additive 扩展（2026-08-25）：tool.called/tool.result 带 `tool_call_id` 与
- L560-598 *契约 additive 扩展（2026-09-13 交付物呈现信号）：新事件
- L706-746 *路径可靠性批（2026-09-15，四件+配套，断 r_eedd621716b5 事故链）：当日
- L747-797 *客户端自适应并发闸 AIMD + 退避抖动（2026-09-15，feat/llm-adaptive-concurrency
- L798-824 *重试可见性批（2026-09-15 二批，A 活倒计时+B 失败源归属，agent.retry
- L918-940 *子代理路径罗盘 + 文件工具路径自愈（2026-09-08）：动因=run_traces 全库
- L1266-1295 通用文件工具并发编辑丢更新修复（2026-09-13，fs_guard 全局写锁+原子落盘）：
- L1310-1367 任务清单陈旧提醒中间件（2026-09-13，机制+纪律）：动因=整本正文生成 run
- L1640-1667 *全仓 review 修复批（2026-09-10，四批 14 条：P1×1+P2×7+P3×6；四 commit=
- L1880-1914 内存/CPU 积累修复批（2026-09-08，行业实践对齐，零契约改动）：系统排查
- L2237-2252 ask_human 参数泄漏自愈（2026-09-10，两轮实测两形态）：deepseek-v4-flash
- L2476-2483 *updates 只翻译真实执行节点（2026-09-08）：工具事件（tool.called/tool.result）
- L2502-2507 前缀缓存铁律（2026-09-06 30M token 事故的教训）：进 system/请求前缀的任何内容

### 二、任务与 Artifact 系统

- L536-559 *产物发布去重与索引重建同步（2026-09-12 四批，SSE 契约零改动，前端零改动）：
- L599-636 *契约 additive 扩展（2026-09-13 整本标书升格正式产物 tender.volume，文件型产物）：
- L859-895 业务模型（2026-08-31 产物归任务；2026-09-04 两态移除：单一当前版本；取代旧

### 三、正文流水线（tender-body / tender-outline / 派发 / docx 工具 / 提示词纪律）

- L1325-1338 *整本小标题程序编号批（2026-09-16 二批，「编号是重复工作不花 token」）：
  降级同时按节内出现顺序拼编号进标题文本（5.1.1 式；gov 接 1./（1）；
  章叶/none/H5+/自带编号形态不编）——09-10「小标题不编号」拍板修订
- L1339-1365 *整本节内小标题按树深度降级批（2026-09-16，平铺观感治理；用户拍板直取简单方案）：
  动因=用户实拍整本「5.1 下有很多 H2」——218 裸 H2 与 54 真节标题同级平铺
- L1366-1397 *素材拷入编号剥除批（2026-09-16，「素材自有编号保真」拍板收窄为版式与内容、编号标题不保真）：
  动因=用户实拍整本「6.1 数据建模」下小标题渲染「1.1.2.4.1 数据项定义」
- L694-705 *检索工具挑选纪律批（2026-09-15，纯提示词零逻辑）：search_company_assets
- L825-852 *prompt 一致性批（2026-09-16，全 prompt 面逐个审计后 7 处点状修复，纯文案）：
- L941-1068 投标流水线 Phase 1（2026-08-25，入口段 2026-08-26 重构）：旧 tender-toc skill
- L1069-1135 投标流水线 Phase 3·第二批（2026-09-06，前端补齐+整本并发铺开）：①前端三小件
- L1136-1194 临时参考件纪律（2026-09-14，全提示词层零代码）：动因=用户问「标书写完后
- L1195-1231 样式/编号迁移去重与拷贝卫生批（2026-09-13，整本目录乱号根因修复）：动因=
- L1232-1265 读图撑爆上下文 + docx 并发互写坏修复批（2026-09-13，两刀全机械层）：动因=
- L1296-1309 09-14 表格通道/回读收敛批 review 修复四件（2026-09-14，小批）：review 挂在
- L1368-1375 element_lines 坐标系统一（2026-09-10）：parse/docx.py 表格从整块 append 改
- L1376-1404 单图插入工具 `docx_image_insert`（2026-09-08，docx 直出管线的放图通道补全）：
- L1405-1438 待办批注体系 `docx_comment_add`（2026-09-08 交付防线批，占位文字退出正文）：
- L1439-1454 整本最终稿标识+交付提醒（2026-09-08，同批前端）：ArtifactPanel body 组
- L1455-1507 标书基准 docx 模板（2026-09-08，格式与内容分离）：动因=用户反馈
- L1508-1517 *拷贝内容的模板策略（2026-09-08 用户拍板：素材库归顺、招标件保真）：
- L1518-1546 *模板库独立入口（2026-09-08 拆库拍板：素材=内容资产/模板=格式资产分离）：
- L1547-1560 *模板库只读工具 list_templates（2026-09-09）：动因=实测用户问「我们有多少
- L1561-1579 *「模板库」定名改「版式库」（2026-09-09 用户拍板）：动因=「模板」二字
- L1580-1615 *封面页机制（2026-09-09，树首节点约定）：设计拍板=封面进目录树当每册
- L1616-1639 *章节编号批（2026-09-10，程序化生成、落点在合册）：动因=整本 docx 章节
- L1668-1687 tender-body 调度优化批（2026-09-08，straggler/串行检索治理；背景=整本 40min
- L1688-1729 派发分组归模型自主规划（2026-09-15，AI 自拆批；取代上批 ①的机械均衡分波）：
- L1730-1743 派发契约：内部编号退出写手语境（2026-09-08，REQ 泄漏根治）：动因=run_traces
- L1744-1774 派发拼装机制 + 写手开局瘦身（2026-09-08 token 治理批）：动因=DeepSeek 实测
- L1775-1798 素材检索复用收口 + 知识库缺口点名（2026-09-10，检索链三态审计后落地）：
- L1799-1819 知识库材料进正文三处接线（2026-09-10 二批，取代上条②「点名需什么」版与
- L1820-1844 写作指引缺口列读者分离（2026-09-13，用户主诉「这段备注真看不懂」）：
- L1845-1855 写手最小工具集（2026-09-10）：`agent._BODY_WRITER_TOOLS`（frozenset 13 个
- L1856-1879 整本交付态修复批（2026-09-12，用户主诉「最终产物 docx 目录乱」诊断后三批）
- L1915-1928 投标流水线 Phase 2（2026-08-25；多册并发 2026-08-26）：skill `tender-outline`
- L1929-1948 skill 体系 agentic 化（2026-09-03，审计+业界调研后落地）：①机械检查下沉为工具——
- L1949-1961 通用文本润色技能（2026-09-06 引入）：`humanizer-zh`——第三方 MIT 技能

### 四、知识库与写作素材库

- L2271-2317 *检索问题 questions（2026-09-08，WeKnora 生成问题思路的文件级落地）：抽取同批
- L2331-2337 占位行 1:1）。图片可见性批（2026-09-08）：动因=云枢素材 87 图、正文 run 25 条
- L2366-2416 frontend：`KnowledgeView.tsx`+`components/kb/`（2026-09-08 知识库 UI 重做，
- L2419-2431 *主 prompt 资料词汇表+无机制纪律（2026-09-09）：动因=「为整本应用模板」请求下

### 五、前端

- L2164-2196 *转录产物卡跨会话失显修复（2026-09-16，方向 A 用户拍板）：症状=换会话
- L637-655 *整本预览空白修复（同日实测反馈）：症状=打开「商务部分」产物卡统计行/横幅
- L1971-1980 产物面板行级右键菜单（2026-09-07）：打开/打开文件夹（reveal_in_folder，仅
- L1981-2003 产物面板docx/pdf 版式预览（2026-09-07）：纯浏览器本地渲染、文件不出本机
- L2004-2011 *工作台显示名单源 wbNames（2026-09-10）：`lib/wbNames.ts` 的 `wbDisplayName`
- L2012-2029 *写作指引/承诺清单结构化表格界面（2026-09-08）：产物面板按文件名分发
- L2030-2042 *指引查看/编辑增强（2026-09-09，文生图设计稿 A+D 组合用户选定，`docs/prototypes/guide-ui/`）：
- L2043-2050 *实机点测两修复（2026-09-09，Playwright 真实 GUI 测试抓到）：①浮层秒开秒关——CellPicker
- L2051-2071 *依据定性增强 F+H（2026-09-09 二批，设计稿 `docs/prototypes/guide-ui/E~H` 用户选定 F+H；
- L2072-2082 *层级区分两批修复（2026-09-09 三批，用户反馈「目录层级区分不清晰」）：根因=树深最多 4 层
- L2083-2095 *出处上下文就地展示（2026-09-09 四批，用户反馈「查看原上下文点击后不会跳转到上下文，
- L2098-2104 *行内内容行+查看态五列（2026-09-13，动因=用户「指引还是无法直观看到自己想要做的内容」；
- L2105-2114 *写作指引两栏重构（2026-09-13 同日二批，取代上段的五列表格；用户选 N/O 图=左树右详情）：
- L2115-2126 「任务即房间」导航重构（2026-09-13，用户拍板）：会话只从任务内诞生，主区按
- L2127-2137 拖放进输入框残留覆盖层修复（2026-09-13）：症状=把文件拖到输入框上松手后，整区
- L2138-2147 前端内存修复批（2026-09-13，行业实践对齐，零契约改动）：3GB 级内存占用的六处收口。
- L2148-2177 产物查看/编辑重做（2026-09-04，方案真值 `docs/artifact-view-edit-redesign.md`）：
- L2224-2236 提问卡原位替换输入框（2026-09-09，用户拍板方向 A，文生图 mockup 定稿）：

### 六、打包、平台与依赖

- L656-693 *PyMuPDF 整体替换为 pypdfium2（2026-09-14，许可治理批，sidecar 内部件+测试+打包）：
- L2547-2592 打包分发（2026-09-07 已实施，取代原「生产分发限制」备注）：PyInstaller one-file 冻结
- L2593-2594 ~~钥匙串用 macOS `security` CLI 子进程~~（2026-08-29 已移除：Key 改存 app.db，见铁则 2；
- L2595-2623 客户端版本检查+更新提示一期（2026-09-15，Rust 壳+前端，零新依赖；含版本号同源修复）：

---

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
   **契约 additive 扩展（2026-09-08 等待态逃生口）**：cancel 端点扩到
   `waiting_input`——无活 worker（暂停存活于 checkpoint），不走取消事件，直接
   `db.cancel_waiting_run`（条件 UPDATE `status='error'+error_code='cancelled'+
   interrupt=NULL+last_seq 回写`，与 resume_run 同款抢占——并发 resume/cancel
   一对一必有一个赢、输家 409）→ `retire_pause_marker`（暂停消息「（等待你的
   输入…）」→「（任务中断）」）→ 端点发 `agent.error`（code=cancelled，
   seq=last_seq+1）。此前等待态是单出口死胡同：无超时、发消息 409、cancel 仅
   running——模型问了个用户答不了的问题就把会话钉死。前端两件：useRun.cancel
   守卫放宽（目标 run=running?runId:interrupt.runId；waiting 路径 202 后本地
   dispatch settle-error + invalidate 兜底——SSE 半开时终态事件到不了，且
   convergeRun 的 !running 守卫清不掉 interrupt，不能只靠对账）；InterruptCard
   （审批卡+问答向导卡）头部加弱化「放弃并停止」链接（onAbandon，ChatView 注入
   cancel）——等待期输入框禁用，卡内是唯一出口。checkpoint 不清（与 running
   取消同口径，langgraph 自愈悬空 tool_calls）。
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
   **压缩与窗口机制二批（2026-09-13，review 发现 1/2 修复）**：①**窗口取值四层兜底**
   （`agent._apply_window_profile`，build 时先于压缩中间件构造）：用户手选（context_window
   存档真值）> langchain_deepseek 注册表已知名（deepseek 系自带 1M 等）> **models.dev
   社区注册表本地缓存**（新模块 `app/model_registry.py`：免费无 key、拍平成
   {model_id: input} 存 `data/model_registry.json`；只在用户主动联网动作〔保存模型/
   测试连接/获取模型列表〕后台 fire-and-forget 刷新、24h TTL、失败保旧缓存；
   **lookup 纯读缓存零联网，run 路径永不联网**）> 保守默认 17 万。静态厂商建议值
   机制**已删**（前端 VENDOR_PRESETS 的 contextWindow 与「展开预填」逻辑一并移除）——
   动因=过期值有害（GLM-5.1 预设 256K > 官方 204.8K，配了照样撞线）且厂商每次更新
   窗口都得跟版发程序；行业实践=数据活社区库（Cline←models.dev、LiteLLM 仓内 JSON），
   程序只消费。②**撞线学习**（`_NoThinkingRetryCompletions` 增 on_overflow_window
   回调）：超限归一化时从文案解析服务商披露的真实上限（两种主流措辞正则 + sanity
   区间 16K~2M，宁缺勿错）→ 写回共享模型实例 profile（**内存态不落库**，「用户没做过
   的选择不落库」同款铁则；rebuild 后重学，每进程最多撞一次线）。未知模型名因此
   统一预设 17 万**进比例档**（85%/10%）——此前 profile None 走「17 万固定线+保留 6 条」，
   学习校准 profile 后无法回馈档位（构造时定死），预设后比例档每轮活读 profile、学习
   立即生效。③**摘要调用输入上限 200K**（`_SUMMARY_INPUT_CAP`）：deepagents 工厂默认
   trim=None——压缩触发时摘要生成单发全部被逐出历史（≈窗口 75%，1M 模型一次 75 万
   token、XML 序列化不吃前缀缓存全价新鲜计费）。修法=`_make_summarization_middleware`
   自建实例（复刻库默认档仅改 trim），经 **deepagents 同名原地替换机制**接进主栈
   middleware= 与两个 SUBAGENTS spec 的 middleware 列表、GP 自动按名继承主栈同名件
   ——实例 `.name` 恰为 "SummarizationMiddleware"（公开别名直接构造），库行为守卫
   测试钉死（升级改语义当场红）；窗口 ≤256K 时逐出 ≈192K<上限行为不变，完整历史
   仍落盘 conversation_history 不丢信息。测试：test_model_registry.py 七例 +
   test_agent 四层取值/工厂/同名替换守卫/接线守卫/学习三例；前端帮助文案同步
   四层语义。
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
   **契约 additive 扩展（2026-09-12 异常恢复批，断点续跑/退出拦截/全工具超时/
   孤儿清扫）**：①`POST /api/runs/{rid}/continue`——error 终态且 error_code ∈
   `db.RESUMABLE_ERROR_CODES`（interrupted/llm_unavailable/llm_auth；cancelled
   尊重停止意图、internal 续跑大概率原地再错，都不提供）的 run 从 checkpoint
   断点续跑：无新输入（run_stream 新参 `continue_from_checkpoint=True`→
   stream_input=None，与断流重试同机制，悬空 tool_calls 由 PatchToolCalls 自愈）、
   不写用户消息、agent.started 照发、start_seq/thinking/model 沿用 run 行存档、
   token_usage 经 _usage_json_final 自动分段累计。前置链=404→非 error 409→
   code 不在集合 409→**非会话最新 run 409**（防 thread 前进后续旧 run 分叉）→
   `agent.checkpoint_exists(cid)` 预检（agent.db 损坏/重建后 thread 缺失提前
   挡掉）→`db.continue_run` 条件 UPDATE 抢占（输家 409）→spawn 失败
   finish_run_if_running 收尸。前端：ErrorCard 对可续 code 加主按钮「从断点继续」
   （useRun.continueRun 乐观 started{continuation}，仿 decide）；**历史中断
   turn 的续接入口**——错误卡是内存态刷新即失，转录最后一条「（任务中断）」
   assistant 消息挂 interruptAction 按钮（MessageList 定位、ChatMessage memo
   比较器同步），getLatestRun 进 ['runs','latest',cid] 缓存，code 可续显示
   「从断点继续」否则「重新执行」。
   ②**退出拦截**：running 态关窗/cmd+Q 先弹确认（误关=杀半小时任务是零摩擦
   破坏路径）。窗口关闭=前端 `@tauri-apps/api`（本批新增依赖）onCloseRequested
   →查 `/runs/active` **只数 running**（waiting_input 暂停存 checkpoint、重启后
   仍可裁决，退出无害不打扰）→有则 ExitGuard 弹窗、无则 destroy()；cmd+Q=
   Rust `RunEvent::ExitRequested`→`api.prevent_exit()`+emit app:exit-requested
   →前端同款确认→`confirm_exit` 命令置 SidecarManager.allow_exit 再退。
   capabilities 加 core:window:allow-destroy + core:event:default。
   ③**_ToolTimeoutMiddleware 从清单制改兜底制+取消感知**：重工具 600s 不变、
   **其余全部工具默认 120s**（此前清单外工具 hang=取消边界永不到达、会话 409
   钉死到重启）、task 无硬上限只参与取消、ask_human 不包；等待循环 0.5s 粒度
   查 CANCEL_EVENTS（经 runctx.run_id）→置位抛 `_ToolCancelledError` 中止节点
   （superstep 不落 checkpoint，悬空 tool_calls 下跑自愈=既有取消口径）+入口
   预检防 langgraph 节点重试空转；**异常与取消竞态归类兜底**——_run_agent_stream
   与 run_stream 两处外层 except 在 _classify_error 前先查 cancel_event.is_set()
   →按 cancelled 收尾（修掉竞态误归类 internal 的既有缺口）。
   ④**孤儿 sidecar 清扫**：sidecar lifespan 就绪写 `data/sidecar.pid`（优雅
   关停删）；Rust run_supervisor 启动先 `sweep_orphan_sidecar`——pidfile→
   pid 存活检查→**命令行身份核验**（tender-agent-sidecar 或 uvicorn+app.main:app，
   防 pid 复用误杀）→SIGTERM≤2s→SIGKILL；壳被强杀（kill -9/OOM）时的残留进程
   不再永久占用资源（Windows tasklist 只见镜像名：bundled 可核、dev 漏扫接受）。
   配套提示三件：interrupted 文案去黑话（sidecar 重启→应用服务重启，任务被中断）、
   ErrorCard 可续中断附安抚行「产出已保存、重开不会从零开始」、409 toast 透传
   服务端 detail（「正在等待你的回答/确认」能指路）；对账失败可见化——
   restoreSnapshot 首败 6s 自动重试一次、再败置 traceSyncIssue（活卡过程区出
   提示行+「重新同步」出口）。测试：test_run_continue.py 三例（端点矩阵/
   continue 模式）+test_pidfile.py+test_agent 超时中间件四例（默认档兜底/
   取消感知/task 无档/预检）+runReducer traceSyncIssue 两例；明确不做=SSE 断连
   静默（重连+对账闭环，正确）、streamText 断连洞（终态即修复）、Retry-After
   自适应退避、agent.db 损坏自动重建、LLM 死等 180s 内提前取消。
   **agent.db checkpoint 安全清理（2026-09-13 磁盘治理批，纯 sidecar 内部件）**：
   动因=langgraph SqliteSaver 每 superstep 写一份「全量消息历史」checkpoint
   （单链平方增长）+子代理每条 task 派发再开独立链（ns=tools:<tid>，整本 run
   数十条），实测 agent.db 1.86GB（308 条子代理链 1.6GB 占 98%、主图全部会话
   仅 39MB、单链尾 blob 最大 2.1MB）；磁盘问题不影响进程内存（未开 mmap）。
   安全性前提=**运行时只读链尾**：全 sidecar 对 checkpoint 的读取仅
   checkpoint_exists 的 get_tuple 与 recover_agent_memory 的 get_state（都取
   最新份）；历史回看走 app.db 的 messages/run_traces，与 agent.db 无关。
   新模块 `app/checkpoint_prune.py`（原则 P0-P7 落为代码约束，模块头+测试
   test_checkpoint_prune.py 六例逐条钉死）：P0 主图最新 3 份恒保留（链尾=会话
   记忆锚点+两份父链保险）；P1 只删早于保留窗的主图中间份与子代理链；P2
   可续态排除（running/waiting_input/最新 run error 且 code∈RESUMABLE_ERROR_
   CODES 的会话一行不动）；P3 checkpoint_id≥保留窗起点的行不删（frontier——
   取消态在途子代理链，删了退化为整节重写；checkpoint_id=time-ordered uuid
   字典序=时间序）；P4 writes 只删随删 checkpoint_id、保留集一行不动；P5 每
   thread 先 SELECT 算集合再分批双限定 DELETE、单会话失败只记日志；P6 删后
   wal_checkpoint(TRUNCATE)+主文件+WAL>300MB 且无占用 run 时 VACUUM（SQLite
   删行只留空页，删而不缩=白做）；P7 删行数/字节与 VACUUM 前后体积入日志。
   孤儿 thread（app.db 无会话行）整链全删。触发点=lifespan 里 recover_stale_
   runs 之后、recover_agent_memory 之前（后者首建 saver 长连接，清理先行=
   独占写窗口；崩溃残留 run 已标 interrupted=可续自动落 P2 排除）；失败不
   阻断启动。明确不做：设置开关/UI（内部运维件常开+门槛）、按时间保留策略
   （保留窗是结构性的）、动 app.db、改 saver 行为（库外旁路清理）。
   **HITL 代答 tool.result 修复（2026-09-12 二批，SSE 契约零改动）**：症状=回答
   ask_human 后活卡状态行整个续跑段卡「正在执行 · 向你提问」（run 本身正常在跑，
   纯显示层谎言）；历史「已询问 N 个问题」组的「你的回答：」行从来没显示过
   （summary 恒空）同根。根因三层实证：①langchain `HumanInTheLoopMiddleware`
   的 interrupt 在 after_model 伪节点抛出，resume 后 respond/reject 裁决被合成为
   「代答」ToolMessage（content=回答原文、tool_call_id 沿用原调用、reject 则
   status=error）从**同一伪节点**的 updates 下发（真链路 create_deep_agent 实验
   实证，模型节点不重发该调用）；②events 适配层 `_TOOL_EVENT_NODES={"model",
   "tools"}` 把伪节点一律跳过 → ask_human 永远收不到 tool.result；③前端
   started{continuation} 把 paused 全部复活成 running 等终态 → activeStatusLabel
   取第一个 running 非 task 步骤=ask_human 恒占。修复三件：events 加
   `_HITL_NODE_PREFIX` 唯一放行（只翻 ToolMessage 防历史重写 AIMessage 重复
   tool.called；PatchToolCalls/Summarization 等其余伪节点维持跳过——2026-09-08
   跨 run 重放守卫不动）；agent `_find_pending` 放开 paused 可回填（与前端
   fillStep 同口径）；`_seed_resume_trace` 续跑段（resume/continue）起步从既有
   run_traces 行 deepcopy 承接步骤树+todos（否则新段树里没有 ask_human 步骤可
   回填、段尾合并落不了「已答+回答」）。前端零改动（fillStep/revive 既有语义
   即收敛）；连带收益=断点继续与续跑段的活树快照不再只剩本段步骤。测试：
   test_events 三例（代答翻译/reject 带 error/AI 重写不重复）+ test_hitl
   respond 续段端到端一例（事件+落库双侧收敛）+ runReducer 复活→代答落终态
   一例；明确不做=error 段落库 trace 里 running 死步的统一收尾（存量疣、
   continue 段复活/重跑语义待单独批次）。
   **压缩总结泄漏正文修复（2026-09-12 三批，SSE 契约零改动）**：症状=正文编写
   run 期间整段「SESSION INTENT/SUMMARY/ARTIFACTS/NEXT STEPS」内部总结稿涌进
   聊天正文与过程卡旁白（用户实拍全文即证据）。根因实证：langchain
   `SummarizationMiddleware` 的压缩总结是一次**中间件内部模型调用**，打了
   `lc_internal_call` 标记并靠 `InternalCallTransformer` 从 run.messages 滤掉——
   但该过滤器只挂 v2 协议事件路径，我方 `agent.stream(stream_mode=["messages",
   "updates"])` 走 v1 通道，且该通道下 invoke 也被流式回调拉着逐 token 上抛 →
   总结全文当 agent.token 流出（英文思考同漏进 reasoning 通道）。触发背景=本地
   首次真实压缩：模型 profile `deepseek-flash`（自建网关别名）不在 langchain_deepseek
   注册表（认 deepseek-v4-flash 等、自带 1M 窗口）且用户未配 context_window →
   deepagents 兜底档「17 万 token 固定触发+保留 6 条」（注册表模型为窗口 85%
   比例档=85 万）；该会话贯穿 parse→analysis→outline 全程起步 9.8 万，正文准备轮
   搬入 ~4 万（技能文件/目录 registry/8 路检索结果）后冲线。修复=events.py
   `iter_stream` messages 分支前置 `_is_internal_call(meta)`（导入上游公开
   INTERNAL_CALL_METADATA_KEY/internal_call_metadata，进程令牌精确比对防伪造、
   键在令牌不符放行——与上游同口径）命中即 continue（token+reasoning 都不产出、
   主/子代理两侧同口径；iter_stream 是 worker 唯一事件源，SSE/旁白封段/最终
   回复/_last_narration 兜底/落库 trace 一处收口）。压缩机制本身零改动
   （162K→34K、历史落盘 conversation_history、任务无缝继续，行为正确）。
   运维两项：重启 sidecar 生效（触发线上的 run 跑完即换）；用户可选在设置给
   deepseek-flash 配「上下文窗口」（后端为 v4-flash 则 1M）→ 触发线升 85 万，
   整本任务基本不再压缩。测试：test_events +4（真标记丢弃（含子代理 ns）/
   无标记照常/伪造令牌放行/**真实 langgraph 流守卫**——过滤押注「v1 messages
   流的 (chunk, meta) 会带节点内 invoke 的 config metadata（含 lc_internal_call）」
   这一上游假设，手造 meta 的单测锁不住：mini 图+假流式模型按 _create_summary
   同款 invoke 形状走真 stream，langgraph 改 metadata 合并/回传当场红）。已知
   残留=历史 trace 里已封的总结旁白（纯观感，
   不自动清理）；写作指引/节 docx/ask 文案全查过无别处污染。

   **契约 additive 扩展（2026-09-13 交付物呈现信号）**：新事件
   `deliverable.created`（payload：run_id/conversation_id/kind("artifact"|"file")/
   artifact_id?/path?/display_name?/seq）。动因与设计=用户问「正文写完了自动打开
   正文？」，初版按文件名/类型写死前端规则被用户否决（「写死了机制」）；行业调研
   定方向——Claude artifacts（官方原文「创建即在右侧专用窗口显示」）/Cowork/
   ChatGPT Canvas 一致走「**产物通道自带呈现语义**」：什么东西值得展示由**产出侧
   声明**，UI 不带任何文件名/业务规则（Codex/WorkBuddy/Manus 则是变更清单+人工
   审阅路线，不自动开）。落地=**声明权在发布管线成功点**（确定性、不靠模型纪律）：
   publish.py 两条发布路径（publish_artifact JSON 产物 / publish_file_artifact
   文件型 tender.volume=整本，同日合入——整本经产物身份获得呈现信号，
   docx_assemble_volume 不再直接 note kind=file：工作台整本行已随 tender.volume
   隐藏，防打开隐藏行）的成功分支 note kind=artifact；短路分支（内容未变）不声明
   ——没新东西不打扰，与 artifact.created 短路语义天然对齐；kind=file 通道保留给
   未来不走产物系统的文件型交付物（path 相对 work/、与「本轮文件」chips 同格式）。
   收集层=`app/deliverables.py`：
   按 run_id 分桶 deque（append/popleft 原子无需锁；contextvars 只能父→子传播
   写不回 worker，工具线程 note→收尾 drain 跨线程靠模块级队列）。事件语义=
   **瞬时呈现信号**：不落库、不重放、错过不补（刷新/断线后转录
   产物卡+文件 chips 兜底，与 Claude artifacts 历史行为一致）；不进 bus
   _MUST_DELIVER（呈现性质、积压可丢）；与 artifact.created 分工——后者仍是
   run/段边界登记对账事件，不动。前端：runReducer 新 case 转 Effect
   `present-deliverable`（不驱动渲染状态）→ useRun options.onDeliverable（经 ref
   转发防 SSE 重订阅）→ ChatView prop → **App 守卫**：slotOriginRef 标记单槽来源
   （user/auto/null，ref 非 state 防回调失稳）——用户手开的文件/产物/原件永不
   被抢（Canvas「自动打开被打扰」社区抱怨的教训），auto 内容可被更新的交付物
   接力替换，打开走既有 openArtifact/openWorkbenchFile('auto')（transient 展开
   面板不写收起偏好）。非当前会话
   天然不触发（SSE 按会话建连），切走视图 ChatView 卸载即跳过、回来不补开。
   **二批（同日，用户拍板改定呈现时机）**：首版「产出即开」（_publish 发任意
   事件前冲刷、段尾尾排水——交付物一产生就开面板）用户用后改为 **run 正常完成
   时才开**：agent.py 移除冲刷/尾排水，completed 分支 drain 取**最后一个**声明
   在终态 agent.completed 紧前发一次（多个声明只开最新的——先目录后整本自然选
   整本，逐个发=毫秒内连环换页无意义）；error（含取消）/interrupt（等待输入）
   段不呈现、随段丢弃（finally 清桶）——那时该看错误卡/提问卡，暂停段之前的
   声明不跨段（续跑完成由续跑段新声明/转录产物卡兜底）。前端零改动（事件形状
   与守卫不变，只是到达时机后移）。测试：test_deliverables.py 六例（无 run 跳过/
   FIFO+clear/契约互证/发布短路对齐/completed 终态呈现最新一个+紧邻终态事件/
   error 段丢弃）+ runReducer.test.ts 两例（file/artifact 转场/
   未知 kind+重复投递）；events.gen.ts 已再生。

   **路径可靠性批（2026-09-15，四件+配套，断 r_eedd621716b5 事故链）**：当日
   实证=59 节整本 run 两次 402（DeepSeek 欠费）中断→续跑 checkpoint 整波重放
   （59 节派发 86 次、13 节完整重写一两遍）→重派描述膨胀 150-324 字超
   `_MAX_ORIG_DESC=200` 被拼装器整体放行→写手自选章节子目录路径
   （body/总体技术方案/x.docx）而合册约定是平铺 body/x.docx→合册 46/59→
   模型删三个章节目录+第三遍重写 10 节自救，48.6min 运行+21min 挂机（正常
   ~25-30min）。历史路径事故同根（24 次 path_not_found/指引 404/派发塌陷）：
   路径=必须逐字节复现的长字符串是 LLM 弱项，防线点状各管一段新链路就绕过。
   四件（全 sidecar，须重启）：①**拼装器富描述仍注入路径锚点**——>200 字描述
   改为「首行探针匹配命中→原文末尾追加最小锚点块（任务前缀/输出路径/今天日期
   三行，含 _ENRICH_MARK 幂等）」，语义信任原文不重复拼；首行对不上维持放行；
   「节名→输出路径」推导抽 `dispatch_enrich.resolve_section`（SectionTarget
   NamedTuple）单点供全量拼装与重派守卫共用。②**重派守卫**
   （agent `_ReplayGuardMiddleware`，wrap_tool_call 挂主栈、清单同步守卫同款
   「拒绝+意图词泄压+次数保险丝」）：task+tender-body-writer+节名对账命中+
   规范节文件 is_file 且 mtime>本 run 起点（db.get_run created_at 解析+2s 余量，
   continue 沿用原起点=续跑段写的也算本轮）且描述无意图词（重写/覆盖/更新/修订/
   重派）→ 不调 handler 直接回 error ToolMessage 指路 check_pipeline_state；泄压
   阀同 run 拒满 3 次放行（`_REPLAY_GUARD_STATE` worker finally 清）；对不上/
   不存在/历史旧节/异常一律放行。③**路径解析收拢单点**——新 `app/path_resolve.py`
   搬入 norm_candidates（原 agent._path_rescue_candidates）与
   unique_suffix_match（原 workbench._unique_suffix_match），原调用方别名引用
   行为零变化；`PATH_RESOLVER_REGISTRY` 声明式登记表=每个模型可达路径参数→
   解析器点路径（fs 六件套/docx _dest_path/parse _resolve_ws_path/publish
   _resolve_draft/workbench/_resolve；内联解析登记工具体本身），守卫测试
   （test_path_resolve.py）扫 TOOLS 参数名（PATH_PARAM_RE）对账登记+登记可
   import，新工具不接线当场红；REGISTRY_IGNORE 白名单带理由（如
   source_item_id=KB 条目 id）。领域解析器原地不动只登记。④**续跑探活预检**
   ——`_ping_model_sync`+`_status_message` 抽 `app/model_ping.py`（settings 改
   引用），continue 端点在 checkpoint 预检后、db.continue_run 抢占**前**插入
   `_preflight_ping(run.model)`（asyncio.to_thread）：profile 缺失→跳过放行；
   无 Key→409「Key 未配置」；ping 失败→409「模型暂不可用，未启动续跑：{人话}」
   （run 行不动无需收尸）；ping 自身异常→fail-open 放行。配套=tender-body SKILL
   整本段加「断点续跑/中断后重新派发前重调 check_pipeline_state 对账已写节」
   （test_skills 锚点防删）。明确不做（拍板）：docx 工具节名寻址（第二批）、
   任务根虚拟挂载（终极形态立档）、trace 幽灵步骤收尾（维持 09-12 拍板）。
   行业依据=SWE-agent ACI（search-first 不裸打路径）/Claude Code·Codex·OpenHands
   （单根锚定+框架解析）/Anthropic 工具设计（服务端解析、不让模型构造未给过的
   标识符）。测试：dispatch_enrich +2（锚点/首行不中放行）、agent +5（守卫
   四态+valve+wired）、path_resolve 新 5、run_continue +3（409/fail-open/直测）、
   skills +1；824 绿+check.sh 全绿。

   **客户端自适应并发闸 AIMD + 退避抖动（2026-09-15，feat/llm-adaptive-concurrency
   批，SSE 契约零改动）**：动因=**用户可自配任意 OpenAI 兼容网关**（小网关/本地/
   免费档并发额度 1~3 真实存在），整本派发 8 路齐发下排队者 429 或 180s 超时→
   瞬时错误→checkpoint 整波重放→又 8 路齐发→死循环到 llm_unavailable——窄额度
   网关跑不了整本（单节无并行反而正常=用户体感「时好时坏」）。行业调研定案：
   429/超时=**背压信号**非错误（OpenAI Cookbook/LiteLLM 部署冷却/Netflix
   concurrency-limits，AIMD 与 TCP 拥塞控制同源）；Cline/Cursor BYOK 均未做
   （429 原样透传）——我们做=差异化。新模块 `app/llm_throttle.py`：进程内
   per-profile 并发闸（`AIMDLimiter`，Condition 实现）——acquire 在飞满则阻塞
   （不超时，持有者受 180s HTTP 超时约束）；release 四语义：**hard（429，openai
   RateLimitError）limit 减半下限 1 / soft（APITimeoutError）−1 下限 1 / neutral
   （其余异常）只归还 / ok 连续 8 次成功 +1 上限 `_MAX_CONCURRENT_STEPS`（8，
   调用方传入避免循环导入）**；窄网关自动降到真实容量交错推进（慢但走完）、宽
   网关零感知；SDK 内建 max_retries=2 保留（瞬时抖动 SDK 层消化，闸门只接持续
   背压）。落点=`_NoThinkingRetryCompletions.create` 进出点（**LangChain 原生
   rate_limiter 钩子只有 acquire 无 release**——框架不知道调用何时结束，做不了
   并发数闸，调研实证）：进门 acquire、出口**恰好一次归还**（one-shot 非阻塞
   抢锁，二轮 review 修——归路三条：流耗尽生成器 finally、with 块 __exit__、
   显式/GC close；生成器进循环引用时 GC 关闭可能落在别的线程与消费线程并发，
   Event 先查后设有竞态窗口、非阻塞 Lock.acquire 原子恰一人成功）；**流式许可
   持有到流真正结束**（流式 create 立即返回，此刻归还=闸门架空）——归路三保险
   =`_UsageCapturingStream` 新 on_release 回调挂生成器 finally（耗尽/中途异常/
   GC close 都走）+ `__exit__`（with 提前退出）+ **显式 close() 定义**（二轮
   review 修——不走 __getattr__ 委派，委派直接打到内层绕过归还钩子，没人 iter
   过就 close 时生成器 finally 不存在、许可直接漏）；429/超时在 create
   抛错路径按 hard/soft 归还后原样上抛走既有重试链；思考降级内层重试（reasoning_
   effort=none）经嵌套 try 同被出口 except 接住；归还**带结果语义**（正常吐完=OK
   计回升进度、中途异常/提前放弃=NEUTRAL 不算成功样本）。注册表 `for_profile(p.id,
   ceiling=)`：同 profile 跨 run 共享互护网关、rebuild 不清（纯运行态，撞线学习
   同款口径）。**收缩冷却窗 5s（review 修，本批最关键一处）**：同一波并发调用会
   同时失败（8 路齐发撞窄额度网关=本功能要治的场景），逐个减半会把 limit 从 8
   直接砸到 1、而回升到 8 要 56 次连续成功——一次网关抖动=整个 run 打成爬行；
   经典 AIMD 是「每拥塞窗口一次减」非「每丢包一次减」（TCP 同源，行业对应物=
   LiteLLM 部署冷却 `cooldown_time`）；冷却窗内跳过的失败信号同样清零回升进度
   （背压期成功不该推高 limit）；clock 可注入（测试用假时钟控窗）。已知边界
   （review 记录，当前不可达）：包装层挂 `model.client`，langchain `_stream` 走
   `self.client.create` 正常分支即被覆盖；`include_response_headers=True` 或
   LangSmith 网关（lsv2_ key）会改走 `with_raw_response.create` 经 `__getattr__`
   委派绕过闸门——我方两者都不成立，将来若开 response headers 需一并收口。
   配套**退避抖动**：`_jittered_backoff(base)=base×uniform(0.5,1.5)`
   应用于 worker 重试取值点，agent.retry 载荷 wait_seconds 传抖动后真值（防整波
   齐拒后同秒齐重试的重试风暴，OpenAI Cookbook 标配建议）。明确不做：Retry-After
   解析（AIMD 即替代，维持 09-12 搁置拍板）、设置项/监测 UI（用户答不上自己额度，
   自适应就是为了不问；「自动监控层」旧否决仍有效）、titler/KB 抽取/vlm 进闸
   （独立实例单发低频）、SKILL「≤8 任务」锚点与 max_concurrency 动（派发廉价，
   闸门配速；降并发只改纪律锚点、升并发才动常量）。测试：test_llm_throttle 新
   13（减半/−1/回升/封顶/清零/**一波并发失败只减一次**/**冷却窗过期后继续收缩**/
   **跳过收缩仍清零**/阻塞唤醒/回升广播/注册表/Noop）+ test_agent +11
   （429 hard/超时 soft/其余 neutral/非流 ok/流耗尽归还/with 提前退出/GC 弃置
   迭代器归还——防泄漏关键路/幂等多径触发/显式 close 归还/接线源码断言/抖动
   界内；wait_seconds 精确断言改界内）。生效须重启 sidecar。

   **重试可见性批（2026-09-15 二批，A 活倒计时+B 失败源归属，agent.retry
   additive）**：动因=实测 lfans 502 窗口期用户两个困惑——重试提示是静态文字
   （waitSeconds 数据在前端状态里但从未渲染，第 3 次 22s 等待整行静止）；且
   llm_retry 无从知道断在主线程还是子代理（载荷无归属，UI 与 trace 均无展示）。
   机制前提（调研实证）：重试恒为**整流级**——子代理 LLM 调用失败经
   ToolErrorMiddleware（瞬时放行 re-raise）穿到主图 superstep → worker 从
   checkpoint 断点重放，波次中失败=整波重放（402 事故形态）；scope 只标注
   **断在哪一侧**不改变重试粒度。B 侧 sidecar：`_tag_agent_scope`（异常在
   **抛出点**挂 runctx.agent_scope——_SubagentScopeMiddleware 的 finally 在异常
   到达 worker 前已复位 contextvar，worker 侧读不到，只能抛出点挂异常对象）+
   `_exc_agent_scope`（沿 `__cause__` 链深度≤8 读回——langchain 包装统一
   `raise ... from e` 保留 cause 链；裸 httpx 断流不经包装直挂）；挂点两处=
   wrapper create 三 except（建连期）+ `_UsageCapturingStream.__iter__` except
   （**流中途断连**，502 多发生处、裸异常唯一挂点）；`AgentRetry` 契约加
   `scope: Literal["main","sub"]="main"`、retry_payload 透传、`_llm_retry_step`
   args+summary 尾缀「· 主线程/子代理」（trace 行直接可读）。A 侧前端：
   `lib/retryNotice.ts` 纯函数（retrySecondsLeft=ceil 递减钳零/retryScopeLabel/
   retryNoticeText——node 环境无组件渲染测试故抽纯函数）+ runReducer retrying
   状态加 `scope`（`data.scope ?? 'main'` 旧 sidecar 兼容）与 `receivedAt`
   （事件到达时刻=倒计时起点，误差≤SSE 传播延迟）+ ChatView 新 `RetryShimmer`
   （仿 Duration 1s tick；归零后退化为无秒数形态=重试已发出在等响应；waitSeconds
   =0 旧载荷同退化）。events.gen.ts 已再生。测试：sidecar walker 五态（直挂/
   cause 穿透/深链/无标记/环链）+建连与流中两挂点+载荷 scope（sub 经 cause 链/
   缺省 main）+伪步骤文案+contract 取值域；前端 retryNotice 三组+reducer 透传
   与旧载荷默认。明确不做：波中重放白烧 token（C 项结构性无干净解，立档）、
   倒计时与服务端真实时钟对齐（到达时刻起算足够）、取消重试按钮。生效须
   重启 sidecar + 前端重载。

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

- **通用文件工具并发编辑丢更新修复（2026-09-13，fs_guard 全局写锁+原子落盘）**：
  动因=用户报 edit_file 假「String not found」。DB 取证（run r_f7c2c322ec21）：
  模型一 turn 并发 4 条 edit_file 打同一 structure.md（ToolNode 线程池真并行），
  上游 `FilesystemBackend.edit` 是无锁 read→replace→O_TRUNC 写回，事故两类——
  ①**假报错**：old_string 与 write_file 原文逐字节相等仍报 not found（读进了
  他人截断窗口）；②**静默丢更新**：后写整存覆盖先写、工具报成功（step70 报
  done 但文件未变、step73 重试成功也丢、文件尾多出撕裂残行；写作指引.md 另有
  同款铁证=step26 报成功、step30 拿同一原文重改）。59 条 trace 扫描：14 处
  「同批并发编辑同文件」暴露面、6 例 not found（5 例是真模型写错、1 例本并发）。
  行业调研定案：Codex=契约层杜绝（apply_patch 同文件双 hunk 直接报错）、
  Gemini CLI=调度层禁并行（EDIT_TOOL_NAMES 强制串行，最强形态）、opencode=
  edit 工具按路径 semaphore（write/apply_patch 漏保）、Claude Code=事后探测
  （自家 issue 记录同款静默丢编辑，最弱）；langgraph 无 per-tool 并发控制、
  全局 max_concurrency=1 会废 8 路波次→调度路线不可行。修法=**fs_guard 加
  模块级全局单锁 `_WRITE_LOCK`（只罩 write/edit/delete）+ `_atomic_write`
  （uuid tmp 同目录+os.replace）**，各治一半：锁治丢更新（变更互斥串行），
  原子替换治撕裂读（读者永远见完整旧版或新版）；读者（read/ls/grep/glob）
  刻意不上锁（并行热路径）。全局锁而非按路径锁=临界区纯文件 IO 毫秒级、
  跨文件串行代价≈0，省掉锁表增长与路径归一化簿记（docx_ops 按路径锁是因
  操作秒级并发是刚需，量级不同取法不同）；锁永不嵌套故无死锁。覆盖面=主
  代理/全部子代理/general-purpose 共享同一 backend 实例（deepagents graph.py
  三处 FilesystemMiddleware 同源注入），压缩中间件落 conversation_history 的
  写也经此层；edit 报错文案复用上游 perform_string_replacement（单源，模型
  重试行为零变化）；delete 套锁只为与写者定序（unlink/rmtree 本无截断窗口）。
  测试 test_fs_guard +2：并发编辑哨兵（Barrier 8 线程各改一行：全成功/8 处
  全落盘/无 tmp 残件）+ 撕裂读哨兵（写者 80 次整存覆盖、读者自旋读，任意
  时刻内容必须逐字节等于完整旧版或新版）；**反证**=同场景打上游裸
  FilesystemBackend：7/8 成功、1 假报错、仅 3/8 落盘。sidecar 756 绿+check.sh
  全绿。已知边界：工作台 HTTP 保存不经 backend，仍走既有 base_hash 409 探测
  +用户裁决（铁则 4 原生形态），不进本批。**须重启 sidecar 生效**。

- **任务清单陈旧提醒中间件（2026-09-13，机制+纪律）**：动因=整本正文生成 run
  实测主 agent 在写作指引确认门（ask_human ×2 裁决）之后只字未再调 write_todos
  ——40+ 次子代理派发、4 波 24 节全程零回写，TodoPanel 常驻浮层数小时停在
  「4/8 · 确认写作指引进行中」与实际执行完全脱节；且 langchain
  TodoListMiddleware 工具描述原文已要求「实时更新、完成立刻标、不要攒批」仍在场
  失灵——纯纪律管不住的又一例（先例=派发塌方→dispatch_enrich、ask_human 参数
  泄漏→机械归一化），且前端与 sidecar 内存真值逐字一致（修的是「模型不写」
  不是「前端不显」）。修复=agent.py 新 `_TodoFreshnessMiddleware`（仅挂主
  agent，子代理无 todos）：wrap_model_call 无状态推导——收集 write_todos 的
  tool_call_id、倒序找最后一条命中 ToolMessage、其后消息数 ≥
  `_TODO_STALE_THRESHOLD`(10) 即在**末条 ToolMessage 尾部**追加一句中文系统
  提醒（含消息数实数；_annotate 同款 model_copy 手法）——只动请求级 messages
  尾部，不落 checkpoint、不动 system_message，前缀缓存字节不变；末条是
  HumanMessage（run 起点/HITL resume 后）不注入；本 run 从未写清单不提醒
  （不逼聊天类 run 建清单）；模型回写后计数归零提醒自动消失；清单全
  completed 但仍在派发时照提（正是错位场景）。机械层不做语义改写（哪项清单
  对应哪段执行归模型）。配套纪律两句：主 prompt todo 句追加「阶段切换时也要
  回写（裁决续跑后第一轮、每波派发前）」；tender-body SKILL.md 整本分波段
  「一波返回、一句话汇报、再派下一波」补「波间汇报同一轮先回写任务清单」。
  前端零改动（todo.updated 整组替换→TodoPanel 即时刷新，快照对账兜底）。
  测试 test_agent 三例（触发含实数/四不触发含回写消失/前缀引用级保护）+ wired
  守卫（主栈有、SUBAGENTS 无）；sidecar 712 绿。运行中的 sidecar 须重启生效。
  明确不做：程序机械改写 todo 内容（语义归模型）、TodoPanel 滞后提示（拍板
  不加）、提醒频控分带（阈值后每轮都提，波次循环每波仅 1-2 次模型调用，
  实测吵再节流）。
- **清单同步守卫=提醒升级为机制（2026-09-13 二批，治本）**：动因=提醒的固有
  latency 一整波（8 路 ToolMessage 才攒够阈值 10，实测 13:49 才写 13:45 续跑后
  的第一波）且**续跑首拍完全盲区**（回答 ask_human 后第一轮模型调用距基线不足
  阈值、提醒不触发，面板 4 分钟停在「收承诺值 in_progress」而实际已在写正文，
  用户实拍复现；后端事件链路健康——live 树/checkpoint/SSE todo.updated 三方
  对账均新，纯「模型不写」）。行业佐证：纯纪律路线被证伪（OpenCode #28961
  「模型执行中不主动更新 todowrite」同病、关闭不做），社区解法=工具边界有界
  拒绝（opencode-auto-resume 插件：todo 真值 + task_complete 拒绝 +
  maxRetries=3）。修复=`_TodoFreshnessMiddleware` 加 `after_model` 门卫（实现
  手法对齐框架内先例 TodoListMiddleware.after_model 的并行 write_todos 拒绝）：
  尾部 AIMessage 含 task 派发且清单滞后（距基线 ≥`_TODO_GATE_THRESHOLD`(6)，
  或 `_todo_baseline` 识别出「ask_human 代答在最后一次 write_todos 之后」=
  裁决后未回写、计数无关必拦）→ 为批内**每个** task 调用返回 error ToolMessage
  （`〔清单同步守卫〕`文案：先 write_todos 回写、可与派发同轮）——路由层
  （factory.py `pending_tool_calls` 过滤）把这些调用判为已应答不再执行、跳回
  模型节点（HITL 同款既有路径）。全批原子=一波 8 个 task 全拒零漏跑（漏放行
  半个批=带着旧清单继续执行，守卫失效）；**同批豁免**=AIMessage 里带
  write_todos 即全放行（「回写+派发」同轮常态路径，免重试往返，最坏 1 次）；
  **泄压阀**=`_TODO_GATE_VALVE`(3)——基线之后已有 3 条守卫拒绝仍不回写则放行
  （按文案标记从消息序列无状态计数，防病态循环卡死 run，对齐 opencode 插件
  maxRetries）；防御前置=state 异常/无清单（todos 空）/批内无 task 一律放行
  （增强逻辑绝不打断 run）。`_todo_baseline` 纯函数为提醒与守卫共用基线
  （write_ids/ask_ids 收集→倒序找最后 write 结果与代答位置→基线取 max）；
  提醒层（阈值 10）保留覆盖非 task 阶段（解析/分析链）。拒绝消息对 SSE 不可见
  （events 翻译只认真实执行节点，伪节点注入的 ToolMessage 跳过——不产生幻影
  失败卡，前端零改动）。中间件仍仅挂主 agent。测试 test_agent +6（滞后整批拒/
  同批豁免/五静默路径/**代答后未回写计数 0 也拒（当日事故回归）**/泄压阀 2 拦 3
  放/aafter_model 转发——基类默认空实现不委托同步版，漏了异步图静默失灵）；
  sidecar 736 绿 + check.sh 全绿（首轮 test_docx_ops 并发批注偶发失败为负载型
  flake、复跑两轮均过）。运行中的 sidecar 须重启生效。明确不做：程序改写清单
  内容（语义归模型铁律）、拦 ask_human（HITL interrupt 先于工具执行拦不到，
  且波次守卫已覆盖全部观测事故形态）、「完成声称」门（run 收尾语义，另一问题
  域，记录在案）。

  **全仓 review 修复批（2026-09-10，四批 14 条：P1×1+P2×7+P3×6；四 commit=
  5b60cc5/b09de99/4972a0c/fa049c2，check.sh 全绿含 dto.gen.ts 补再生）**：
  四路并行 review（run 管线/docx 工具链/前端/安全面）后按拍板范围修复，缓做
  四件=run worker 独立线程池、样式 id 内容比对重映射、fetch_url/baidu DNS 固定、
  Rust 端口清扫收窄。批次 A（数据正确性+安全）：①element_map 升版 2、读侧
  只认 ≥2——坐标系修复前的折叠坐标旧 map 被版本护栏拒收，注入走既有「幂等重跑
  +md 漂移比对」自动换新坐标（**素材侧存量错位注入的根治**；此前「即刻生效
  无需重传」的说法只对 docx_source_inject 成立）；②KB docx 图片抽取读前查
  ZipInfo.file_size 三道闸（单条 50MB/累计 200MB/张数上限提前到读阶段——zip
  炸弹 OOM 面）；③raw 端点四站恒 attachment+nosniff、FastAPI /docs 关闭、
  Origin 守卫中间件（带 Origin 且非本机白名单 403，堵浏览器模式跨站简单请求）、
  fs_guard 异常补 ValueError。批次 B（docx 交付防线）：assemble_tender 透传
  numbering（重组装不清用户选的编号格式）；docx_source_inject 重复注入拦截
  （itertext 对称 shingle ≥60% 拒，格式件翻倍不可再直达合册）；validate_body
  坏节隔离（单损坏 docx 点名剔除不拖垮全局）；check_pipeline 缺口列头变体匹配
  +dispatch_enrich 册名 sanitize（两处口径分叉收口）。批次 C（run 管线自愈
  边界）：①断流重试假终态收口——tools 节点失败重试复用同 tool_call_id，
  `_find_pending` 放宽回填（error==`_RETRY_RETIRED_ERROR` 标记）+`_revive_step`
  同 id tool.called 复活（保留封段字段），前端 fillStep/幂等分支同口径 parity；
  ②`_FROZEN_CTX` 守卫 clear() 全清改逐条淘汰+四终态清理点 `_frozen_ctx_cleanup`
  （waiting_input 不清、续跑沿用冻结块）；③幽灵 run 收尸（create_run/resume_run
  后落库失败 finish_run_if_running）+超时文案警示「勿立即重写同一文件」。批次 D
  （前端）：等待死卡三出口（convergeRun 带 runId 指认同 run 才清冻结卡；decide/
  send 的 interrupt 409 与 cancel waiting 404/409 强制对账或本地 settle）；run.state/
  snapshot running 清跨窗口续跑残留 interrupt；snapshot merge 不回退未封口思考；
  useAutoSave 闸门统一进 doSave（saveNow 同闸、force 直通，WorkbenchViewer
  finishEdit 拦下留编辑态）；向导 fileNote 只进 decisions；DirectoryEditor 改名框
  Escape 阻断冒泡。测试净增 19 例（sidecar 657/前端 204）。

- **内存/CPU 积累修复批（2026-09-08，行业实践对齐，零契约改动）**：系统排查
  （前端+sidecar 全量泄漏审计）后十项落地。①活树快照拷贝节流——`set_live_trace`
  500ms 窗口内只记 pending 引用不拷贝、下一个结构性事件或读侧超窗才真拷
  （worker 单线程改树、读侧补拷撞并发 deepcopy 异常时沿用旧快照下次再补；
  终态/暂停权威 trace 落库路径不变，快照最多滞后 500ms 而前端对账本就 5s 限频），
  治 8 路并发下「每结构性事件整树 deepcopy」的平方放大；snapshot 端点深拷贝挪
  `run_in_executor`（async def 内禁阻塞）。②`_sync_sub_reasoning` join 后
  `buf[:] = [joined]` 收敛单份——此前子代理思考的 chunk 列表+拼好串双份驻留
  整个 run。③`app/bg.py`＝fire-and-forget 唯一入口（Python 官方强引用集合
  模式：模块级 set + done_callback 移出+异常记日志；五处裸 create_task 收编
  ——防 GC 收走未完成 task 致 `_inflight` 永不清、条目永久 409）+ KB/素材
  解析专用 ingest 线程池（`run_in_ingest`，max_workers=4、复制 contextvars
  对齐 to_thread 语义；与 agent run 默认池分家，一边卡死不饿死另一边）。
  ④`_ToolTimeoutMiddleware`：本地重工具（parse_document/assemble_tender/
  docx 族九个）10 分钟封顶（对齐 Claude Code bash 2min 默认/10min 硬上限的
  机制纪律）——真 handler 在复制 contextvars 的 daemon 线程执行、本线程限时
  等待，超时返回错误 ToolMessage 走既有 error 通道，模型可缩小范围重试、run
  正常收尾（此前卡死工具=worker 永不返回，_LIVE_TRACES/用量桶永久驻留+线程
  池槽位占死）；机制边界明示：Python 杀不掉线程，超时后底层线程滞留至自然
  结束（计数有界）；LLM/HTTP 工具不包（已有 180s）；主代理+两个 SUBAGENTS
  双挂。⑤TIFF/BMP 转码 `lru_cache` 128→8（缓存整图 PNG 字节，扫描件单张
  数 MB，满载常驻从最坏几百 MB 收到 ~20MB）。⑥前端：活卡正文流+暂停旁白
  尾窗封顶（`capStreamingText` 加名词参数「思考/正文」，11GB 修复家族的最后
  缺口——此前只封了思考流两处；终态/历史消息全量渲染不变）、source-raw/
  docx-raw 补 `staleTime: Infinity, gcTime: 10min`（原件不可变；sources
  同名重传在上传/删除三处显式失效 source-raw，docx-raw 靠 run 终态
  `['workbench']` 前缀失效连带——AI 修订后重开必是新字节）、/runs/active
  隐藏期拉长 30s（不用 false：全局 refetchOnWindowFocus 关了会永久停摆）+
  healthz 探测隐藏期跳过。测试：sidecar 609 绿（新增 buf 收敛/节流两窗/
  超时中间件超时+透传+wired/wrap_tool_call 执行上下文守护 + bg 强引用+ingest
  池共 7 例）+ 前端 167 绿。Review 补丁：docx-raw staleTime 降 30s
  （workbench docx 非不可变——run 进行中会修订，Infinity 的中途陈旧窗口无界；
  sources 原件才配 Infinity+显式失效）；/runs/active 的隐藏期收益改为定时器
  唤醒降频（react-query 默认本就跳过隐藏期 interval 拉取，真门控点=healthz
  的裸 setInterval）。

- **ask_human 参数泄漏自愈（2026-09-10，两轮实测两形态）**：deepseek-v4-flash
  偶发把可选参数写成 `options="…"`/`guide_path="…"` 赋值行塞进 question 正文、
  参数本身留空——前端候选项/「打开指引」按钮只读 args 字段，空则按钮整体
  不渲染、伪代码行原样上屏（实测 run 无可点按钮只剩文本框；真凶=skill 教学
  文本自己写赋值简写）。两层修：写侧 `events._salvage_ask_human_args`
  （挂 _hitl_requests 出口——SSE 提问卡与 runs.interrupt 落库同源）+读侧
  `events.normalize_hitl_requests`（sse.py run.state 对账与 conversations.py
  runs/latest 读出过同一遍——修复前已等待中的 run 重连/刷新即自愈，无需重发
  提问）。规则=行首 `options|guide_path [=:：]` 白名单匹配（multiple 未观测
  不收）、**参数已有值不碰**（两处信息冲突无从裁决，保留原文诚实呈现）、
  空值行保留（无可摘取）、options 按「；;」分隔重组逐项剥引号；与
  _deep_unescape 同边界=只改下发 UI 的 args 副本，工具实际执行与模型记忆
  （checkpoint）仍用模型原始输出。教学层同步四文件：ask_human docstring 补
  完整调用示例（参数各归各位）、主 prompt ask_human 段加「候选项与 guide_path
  只写进各自参数」句、document-parse/tender-body SKILL 提问点各加纪律。
  test_hitl +5 例（两形态/变体/不误伤三断言/读侧）。

    **updates 只翻译真实执行节点（2026-09-08）**：工具事件（tool.called/tool.result）
    只从 node∈{model, tools} 的更新产出——中间件钩子伪节点（deepagents
    `PatchToolCallsMiddleware.before_agent`、langchain `SummarizationMiddleware.
    before_model`）的 messages 是**状态重写不是新工作**：新 run 开头发现上一 run
    中断遗留的悬空 tool_calls 时，before_agent 会把整段历史消息原对象+补插的取消
    ToolMessage 一并写进 updates，照译会把上一轮全部工具步骤重放进本轮的 SSE/trace
    （实测中断 run 的下一轮 trace 混入 12~64 个外来 tool_call_id）。todos 提取不受
    白名单影响。加新中间件若在伪节点写 messages，天然被跳过（正是期望行为）。

  - **前缀缓存铁律（2026-09-06 30M token 事故的教训）**：进 system/请求前缀的任何内容
    必须整个 run 内字节稳定——每次调用现算的易变项（时间戳/便签/产物清单）一律 run
    冻结（`_task_context_block_frozen` 先例）或挪请求末尾；模型供应商前缀缓存按字节
    前缀匹配，断点之后全部按未命中全价计费（DeepSeek 命中价约 1/10-1/30）。新加
    「每次模型调用注入 XXX」类功能前先过这道检查。
    领域事件由 server 装配的 eventSink 落库，工具不直接写 UI。

   **产物发布去重与索引重建同步（2026-09-12 四批，SSE 契约零改动，前端零改动）**：
   动因=用户主诉「目录产生后每轮回复都出现投标目录卡」+ 顺带查出 content_seq 账
   对不上。DB/日志/恢复点三方对账实证双因：①模型几乎每 run 重调 assemble_tender
   （真实会话 6 run 里 3 run 共 6 次成功发布，含「再次分析」轮顺手刷新、正文轮改
   目录底稿后重发——重分析后刷新语义成立不设禁令），task-single 单例 + placeArtifacts
   按 source.run_id 挂「最近发布回合」→ 卡逐轮后推；②**meta.json 的 source 是创建
   时化石**（existing 发布路径只写 content.json+索引行，从不回写 meta），启动
   rebuild 从 meta.source 恢复 last_run_id → 每次重启卡回卷到首次发布回合直到下次
   发布；同因 content_seq 复位 1（目录编辑器拿它当版本号做外部更新探测，重启即
   误报「外部已修改」）。修复两件：①publish.py existing 分支**内容未变短路**——
   `read_content_resolved == content_text` 且显示名相同 → 不发布（seq/emitted/
   last_run_id/恢复点全不动，pending_emit 捞不到即无 artifact.created），返回 meta
   附 `_unchanged: True`（仅进程内返回值标记）；assemble_tender/tools-publish 消费
   标记改「[组装完成]/[发布完成]…未重复发布」文案（统计行照带）。比对是**序列化
   文本逐字节**：编辑器紧凑序列化 ≠ 发布 indent=2 → 用户编辑过则永不误短路（宁可
   多发一次，方向保守）。②rebuild_artifact_index 从「清空重插+运行态复位」改
   **同步语义**：幸存行（磁盘包还在）保留五列运行态 content_seq/updated_at/
   last_run_id/last_thread_id/emitted，身份字段仍以 meta 为准（手改 meta 可拾起），
   磁盘新增按默认插入、库有磁盘无删除；全量 DB 丢失回落复位语义。meta.json 刻意
   不回写（保持创建记录语义，DB 幸存行保留已达目的）。既有 quirk 顺带记录：existing
   路径本就不回写 display_name（重发布改名=静默忽略，未扩范围）。测试：test_publish
   +2（noop 三态：同内容+同名→跳过/仅改名→照走完整路径/内容变→照发；rebuild 保留
   五列+删行+插默认行）+ test_assemble_tender 二次组装短路/输入真变重发 +
   test_publish_tool 同内容笔记重发消费草稿；sidecar 696 绿+check.sh 全绿。

   **契约 additive 扩展（2026-09-13 整本标书升格正式产物 tender.volume，文件型产物）**：
   动因=用户问「正本标书、标书解析为什么没有产物卡」——此前流水线唯一登记产物是
   目录，整本=派生物（09-06 拍板）留过程文件、解析/分析=中间输入；用户拍板**升格
   整本为正式产物**（解析/分析维持过程文件）。新契约 `tender.volume/
   tender-volume-docx@1`（task-multi 标注+editable=False+content_type=docx MIME，
   ContractDef 新增可选 content_type 字段默认 json）：包内除 content.json（机器
   元信息：filename/book/size/sha256/merged_sections/images/comments + note 字段
   给模型「派生物勿读回当输入」指引）外还有 **docx 本体**（整本-<册名>.docx）。
   发布入口=`publish.publish_file_artifact`（与 publish_artifact 并行的新函数，
   JSON 路径零改动）：**身份复用键=任务+kind+display_name（册名）**——不走
   task-multi「恒新建」（doc.note 语义不碰），多册各一条、同册重合册覆盖同一条；
   **内容未变短路=zip 内容级比对**（`_zip_content_equal`：namelist 集合+逐部件
   CRC32，忽略 zip 时间戳——python-docx 每次保存时间戳必变、逐字节比对永不相等；
   lxml 序列化确定性使同内容 CRC 稳定）；**明确不设恢复点**（整本是派生交付物非
   用户编辑内容，旧版可由节文件重合册复原，恢复点的受益场景不存在）。发布时机=
   `docx_assemble_volume` 每册落盘后机械发布（每册独立 try/except，失败只加 ⚠️ 行
   不影响合册返回；消费 `_unchanged` 文案「未重复发布」；deliverables.note 同步
   声明 kind=artifact 与呈现信号批对齐）；LLM 的 staging 草稿流进不了二进制=机械
   层天然防手滑。read_artifact 零改动（content.json 是合法 JSON）。API 新端点
   `GET /artifacts/{aid}/file`（包内唯一 docx 流式下发、nosniff、containment 与
   content 同标准）；`_to_api` 的 content_type 从硬编码改查契约注册表。**顺手修
   潜在漏**：workbench 列表与唯一后缀兜底此前不跳 `work/artifacts/` 子树（包内
   从无 .md/.docx 所以没漏过），包内有 docx 后必漏重复行——两处补 `rel.parts[0]
   =="artifacts"` 跳过（与 run_files 口径对齐）。前端：`fetchArtifactFile`（rawFetch
   无超时给大文件）；registry 三处注册 + `.ft-ico--vol` 色板；**VolumeProcessor**
   （只读：统计行〔合并节/图片/待办批注〕+批注>0 时交付提醒行+下载 downloadBlob；
   blob query key 带 content_seq〔重发布即取新字节〕、staleTime 30s/gcTime 2min
   对齐 DocxView 内存治理、DocxPreviewBody 懒加载）；ArtifactPanel body 组 volume
   产物行置顶（册序按目录树 volRank）+品牌色「整本 · 最终稿」徽章（FINAL_TAIL
   常量与 wbRow 共用），**任务有任一 volume 产物时工作台 `整本-*.docx` 行隐藏**
   （同一内容不重复两行；旧任务无产物维持文件行，重跑合册即补卡）。tender-body
   SKILL.md 第 4/5 步同步（合册即自动发布、收尾指引用户从产物卡打开/下载）。
   已知取舍：册改名=另立新卡旧卡保留（内容仍可打开）；多册个别册发布失败时工作台
   整本行整体隐藏（产物卡仍在，罕见场合接受）；旧任务存量整本无卡，重跑一次合册
   即补上。测试：test_publish +3（新建/zip 等价短路+内容变覆盖/册名身份键）+
   test_docx_ops 合册发布与二次未变断言 + test_artifacts file 端点/契约清单 +
   test_workbench 跳过子树；sidecar 746 绿 + 前端 tsc/oxlint/build 绿（ruff 对
   本批文件零告警；test_deliverables.py 两处 I001 是并行批次文件未动）。

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

   **检索工具挑选纪律批（2026-09-15，纯提示词零逻辑）**：search_company_assets
   docstring 纪律段补两条——①招标带时间限定（近三年/近三个会计年度/自某日
   以来/N 个月内，适用任何材料）先换算成具体时间范围、再对齐材料自身时间
   锚点（财报年度/合同验收签订日期/证书发证与有效期），不满足不采用；动机=
   freshness 的「资料较旧」标签是写死满 3 年的通用提醒，与招标语境错位
   （2026-09 时 2023 年财报恰是「最近三年」要的却被标较旧），纪律里明确
   「以换算范围为准不被标签带偏」。②材料与招标要求不契合（案例行业/业务
   类型、证书种类等级）不凑数宁缺点名。两个拍板：判断纪律放工具 docstring
   （知识库查找职能、全调用方生效），非 tender-body SKILL；**不写硬代码**
   ——年份过滤/契合评分是把语义伪装成机械（「最近三年」口径本身模糊归
   模型）。search_references 刻意不加（用户手挑块+备注已是挑选依据+数字已
   禁用）。枚举招标措辞形态而非材料类型（举例即边界，写窄了模型照着窄化）。

   **prompt 一致性批（2026-09-16，全 prompt 面逐个审计后 7 处点状修复，纯文案）**：
   审计方法=主/子代理 system prompt+6 技能+21 references+24 工具 docstring+后台
   LLM 调用逐个精读，并用 run_traces 真实数据交叉验证遵守度；发现三类问题，
   本批修前两类（第三类主 prompt 分节重构经必要性评估用户拍板剔除）。①**三处
   教写内联占位文字的活跃指令**（占位是 validate_body 判不过+合册⚠️的对象，
   教写=让照做的写手自查必挂）：docx_source_inject docstring 与运行时返回语
   「未定值【待补：…】」→ 批注出口；dispatch_enrich 承诺清单缺失兜底「缺项
   一律写【待澄清：…】」——实测它与同载荷内联方法论的禁令句**同一条任务描述
   里自相矛盾**（模型二选一）→ 批注出口；tender-analysis SKILL「正文内联标注」
   与 clarifications.md「正文内联「【待澄清：…」」两处旧口径 → Word 批注口径。
   ②**两句承诺/作用域错配**：主 prompt「重跑覆盖前自动留恢复点」加限定（整本
   tender.volume 发布明确不设恢复点——承诺须对齐机制）；humanizer 句加作用域
   （只润模型生成文字，素材底稿/招标原件保真不润——重写素材会掉使用率校验）。
   ③**写手方法论禁令改条件式**：「已随任务描述给出、不要 read_file 它」在富描述
   分支（>300 字只附路径锚点、不内联方法论，09-15 最小块拍板）不成立——实测
   r_eedd621716b5 正是此态（写手无方法论可用，58 次读指引自救）；措辞改
   「段在则不要再读、段缺则开工前自读一次」（程序零改动，保留最小块设计）。
   防回流测试四处：source_inject 返回语不含【待补且含 docx_comment_add /
   dispatch 兜底不含【待澄清（首个 promise=False 用例）/ tender-analysis 两文件
   不含「正文内联」/ 主 prompt 机制对齐两关键词+写手「若该段缺失」条件式锚。
   缓存影响（用户问询后明确）：前缀缓存按请求开头逐字节匹配，改 system prompt/
   docstring=全部会话旧前缀作废——一次性重暖（全局首个请求全价 ~15-20K token
   + 每个活跃长会话续跑首call历史全价一次），之后恢复；run 内字节稳定铁律
   （冻结任务上下文/天级日期）本批未触碰。生效须重启 sidecar（skills 镜像
   _sync_skills 自动同步+_skill_cache 刷新+agent 重建），升级时点避开正在跑的
   大 run。明确不做：主 prompt 分节重构与去重（必要性=维护性投资非修病，用户
   拍板剔除）、富描述分支补拼方法论（条件式已绕开）、写手 ls/glob 禁令改机制
   （拼「已写节清单」属机制批）。

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
  （同一 assistant 消息一次性发出全部调用，ToolNode 线程池真并行——2026-09-14
  PyMuPDF 替换批起 C 层经 pdfium 全局锁串行、Python/IO 层重叠（PDFium 官方禁
  多线程，见铁律 3 的替换批记录）；主文件失败在概况门前拦停，不串行即停）→
  **解析概况确认门**
  （流式摘要：角色/字符量/页数/标题数/解析档位/顶层章节/警示/降级声明 + ask 确认/停下，
  全部[解析跳过]时不弹门；**数字全部取自 parse_document 返回文案**（跳过同样带全量
  概况），不读 meta.json；档位与出处署名联动））+
  skill `tender-analysis`（七节要点提取，第 0 步=前置检查走 check_pipeline_state（2026-09-03
  机械检查工具化：来源确认/三件套齐备/新鲜度只报事实、零结论，裁决分支留 skill）；
  每节写完跑 validate_analysis 机器校验（coverage/出处引用两层：锚定/文件名∈来源集合/
  L 行号≤原文 md 总行数——杀编造引用，提示不是门禁、收尾前必须全绿；
  **2026-09-04 模型写头已删**：产物不带首行元信息头，修订标记由服务端程序盖）；
  purpose 下沉 references/ 文件级、单项可重跑；**收尾=摆要点停轮（2026-09-13 用户拍板）**：
  汇报摆关键要点（废标/评分框架/资格硬门槛/递交形式，不只报条目数）+待澄清清单逐条
  呈现+提醒在界面「分析」文件过目，本轮结束**不自动衔接目录**（原始请求覆盖后续环节
  也停），继续由用户在输入框指示——**明确不用 ask_human**（分析→目录间无门禁也
  不自动跑；纪律落在 SKILL.md 第 4 步+主 prompt 衔接句双层）；导航硬纪律=先读 work/parse/<文件名>/
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
  路由纪律：**数字版 PDF 永远本地解析**（2026-09-14 起 pdfium 引擎；书签/目录链接结构识别只在本地有）；
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
  =备料对账）→ 停轮汇报指引（摆模式分布/缺口逐条/承诺事项一次列全，提醒在界面
  「写作指引」过目）→ 用户答复后承诺值落 `work/body/关键事实与承诺.md`（事项｜值｜
  说明；**承诺只出自清单，拍板前不写正文**）→ 停轮汇报承诺清单、用户回复继续才
  逐节生成。**2026-09-13 用户拍板：两道 ask_human 门（确认指引/收承诺值）弃用**——
  与 tender-analysis 收尾同款「摆要点停轮」语义（总结要点+提醒查看+用户在输入框
  说继续/给值，不用表单卡；「一口气写完整本」指令也停）；guide_path 参数与
  「打开指引」按钮链路随之无人使用（ask_human 工具本身保留：解析概况门/目录 R1
  拆分门/第 0 步重写范围门仍在用）；纪律=SKILL.md 第 1 步+主 prompt 衔接句双层、
  test_skills 锚点同步换新（弃门守卫：旧两句教学文本不得回流）
  ③逐节生成按指引模式路由（模板填充列待填
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
  改推理撰写出路；**2026-09-15 契约修正批降级为弱提示，见下**）与「不同块 id 同素材文件区间重叠派不同节=弱级提示」（治历史
  马甲块——同区间两个块名不同，失效检查发现不了）；全局模式加「节间两两查重」
  （归一化 10 字 shingle 交集/较小方 ≥50% 点名，短节 <5 shingle 跳过；重构后
  独立于承诺清单跑——清单缺失也照查）。建块侧防线在前端（materialsBlocks.ts
  overlappingBlocks + 建块弹窗 exact/partial 提示，提示不阻断），后端不做（建块
  唯一入口是用户 UI，模型无建块工具）。guide-format.md 素材列「一块只派一节」、
  SKILL.md 第 3 步全局行同步接线。
  `_PROCESS_DIRS` 加 body/（骨架自愈）；agent.py 主 prompt 路由句加 tender-body。
  本批**串行写节**（并发子代理+兄弟摘要、全局跨节审计、语义审阅、字数校准留后续
  批次）；联网检索模式=枚举预留未实现。
  **素材/知识库契约修正批（2026-09-15，块=拷贝授权范围非注入原子）**：动因=正泰
  BPM 任务实证「BPM技术平台介绍」2.4 万字大块在「一块只派一节」约束下只进总体
  架构节、流程设计/数据建模/表单设计等与材料章节一一对应的节零引用（写手检索
  两次命中第一名也按「仅供写法参考」放掉），另实测移动办公写手整块注入又整块
  删除 2.25 万字修订——「整块注入后修订」当义务就是浪费源。与用户四轮讨论定
  契约：①两库内容都可改写进正文，**同主题优先素材库**（块做拷贝底稿，知识库只
  补证书原图/时效核对/块未覆盖的事实；防双吃——注入了块的节不再转述同主题
  文本；无块主题知识库正常转述）；②**块=授权与检索单位非注入原子**，注入粒度由
  写手按节自选；③「一块只派一节」降级为「同一内容区间不得进两节」（防线=节间
  查重，本来就是内容级）。落地六件（全 sidecar，**须重启 sidecar**）：①
  docx_material_inject 加可选 `lines`（逗号/顿号分隔「起-止」容 L 前缀；**授权
  围栏**=请求区间须完全落在块勾选范围内、否则报错带合法区间；防重基数从块全文
  改实际选中元素 itertext 并挪进路径锁内——子区间注入不误伤 disjoint 区间；摘要
  带 scope「整块/L起-L止」）；②validate_body 同块多派降弱提示（文案带区间纪律）、
  block_ids 支持 `blk_…:L起-L止` 后缀按子区间算使用率（治子区间注入被整块口径
  误报「未实质使用」；校验侧宽松、后缀解析失败回落整块，围栏在注入侧硬拦）、
  _residue_names 容后缀取裸 id；③search_references banner/docstring/精读指引改写
  （「仅供写法参考」→「可拷贝内容的授权范围：注入什么由你挑选（整块或块内区间，
  可传 lines）」，数字重核半句保留），search_company_assets docstring 补同主题
  优先级与防双吃；④agent.py 主 prompt 知识库段重写为三句裁决规则+词汇表素材
  条目更新、写手五步/硬纪律加区间自选与「同一内容区间不得进两节」；⑤技能三件
  （SKILL 素材修订 bullet/guide-format 素材列契约重写〔同块多节合法+优先级三句+
  块大不必拆〕/section-writing 第 2、3 步）+dispatch_enrich 名片加「区间：L起-L止」
  字段与区头新文案（写手挑 lines 的依据）。测试：改 4（同块多派语义/banner 断言/
  名片头×2）+ 新 6（lines 子区间只注入选中元素/授权围栏三态/多区间+同区间二次
  拦截/使用率后缀两态/素材列契约锚点+旧句防回流/写手 prompt 锚点）；877 绿+ruff
  零告警。存量说明：已生成的写作指引不自动迁移（旧同块多派行重跑校验从 issue 变
  弱提示）；大块不拆也能喂多节（BPM 形态正名）；写手 prompt 锚定串（直接采用/
  不再调用 search_references/仍须照常注入并改写等）全部保留。明确不做：知识库侧
  建块机制（路 B 否决——注入机制天然长在块上）、素材块 freshness/版本概念、纯
  写法块标记（两开放点挂起）、节间查重阈值、清理存量双库并存（SLA 双份在规则内
  合法——素材库吃内容、知识库吃核对）。

- **投标流水线 Phase 3·第二批（2026-09-06，前端补齐+整本并发铺开）**：①前端三小件
  ——ask_human 加可选 `guide_path` 参数（透传前端、工具体不消费，提问卡渲染
  「打开指引」按钮直开 workbench 文件，InterruptCard/ChatView 两文件）+ run 终态
  （agent.completed/error）invalidate `['workbench']`（run 期间新写的 body 文件结束
  时自动进面板列表）+ WB_NAMES 显示名（**暂停点刷新补齐 2026-09-15**：run.interrupt
  与 run.state waiting_input 对账分支同款补 invalidate `['workbench']`/`['tasks']`——
  技能在等待点提醒用户去界面过目文件，面板却停在 run 开始前的快照是缝隙；暂停
  期间无写入，interrupt 时点刷一次对整个等待期有效，取消/续跑不另补）；②并发铺开——agent.py SUBAGENTS 加
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

- **整本小标题程序编号批（2026-09-16 二批，降级批同函数延伸；用户拍板「编号
  是重复工作不花 token」）**：动因=降级批落地后用户追问「H3/H4 为什么完全没有
  数字编号」——09-10 拍板「节内小标题不自动编号」的三个理由中两个已被降级批
  解决（「程序分不清素材标题与 AI 标题」→合册拷贝面已全部识别并改挂样式；
  「不知道树位置」→编号器在手），「模型自编必错」依然成立→写手零参与、纯程序
  生成。实现=`_restyle_subhead_levels` 降级的同时按**节内出现顺序**拼编号进标题
  文本（与骨架同机制：拼文本、不走 Word 样式自动编号）：chapter/decimal 接续
  节号（5.1.1 / 5.1.1.1，计数器每叶重置、跳级垫 1）、gov 接续中文层级（H3→1.、
  H4→（1））；**不编面**=深度 1 章叶（无节号可嵌套）、none 格式、H5+（防素材
  深标题编出 5.1.1.1.1.1 式深号）、文字自带编号形态（_SELF_NUMBERED 命中，
  防双拼——静默跳过，已知行为）。目录页/导航维持只收骨架（小标题带号但目录
  不列——「编号了的三级题要不要进目录」是另一拍板，未动）。测试：降级批 3 例
  补编号断言（1.1.1/1.1.1.1/1.1.2 表内接续、章叶不编、护栏免编+对照组 2.1.1
  ——前置区不占章号）、新增 gov/none 矩阵 1 例；sidecar 888 绿。生效须重启。
- **整本节内小标题按树深度降级批（2026-09-16，平铺观感治理；用户拍板直取简单方案）**：
  动因=用户实拍整本「5.1 下有很多 H2」——全链路审计：真实任务整本 218 个裸 H2 节内
  小标题与 54 个真节标题（5.1 式，同为 Heading 2）同级平铺，评委视角分不清层级；
  机制上导航/目录是干净的（09-12 demote 已把 218 段全部钉 outlineLvl=9，Word 导航
  窗格与目录域均不收录——用户截图的视图按标题样式列段、不受 olvl 覆盖影响是遗留
  疑点，见「被否/后手」）。根因=样式撞级：节文件里写手纪律「小标题从 Heading 2
  起」（节标题 H1>小标题 H2/H3 层级本来就对），合册把节升为 H2 后小标题未随动。
  方案（用户提出、比我先提的两版都简单）=合册拷贝循环里把拷入面标题段按
  **目标级=clamp(树深度+源级−1, 2, 9)** 改挂输出文档内建 Heading N：深度 2 节下
  H2→H3、H3→H4，章直接挂内容的叶子（培训方案式）维持 H2 观感，树里真有 5.1.1
  三级节时同级=正确语义；源级解析=样式名 heading N/标题 N（改名变体 heading 5 2
  天然命中）/样式 outlineLvl+1/兜底 2。实现 `_restyle_subhead_levels`（级别与目标
  styleId 双缓存），接线守卫=前置区/目录页/格式件章（NON_PROSE 招标件零改动保真）/
  封面页不降，其余叶子拷入面全降（含素材改名标题样式段与表格内标题段）；**在
  `_merge_missing_styles` 之前调**——素材标题样式不再被引用、整本完全不迁入（前批
  剥编号的延伸副产物）；`_demote_extra_headings` 随后照旧钉 olvl=9，导航/目录不收录
  不变，只有视觉层级下沉。节文件零改动（工作台层级本来就对），存量重跑合册即净。
  被否/后手：①给小标题自动编号（5.1.1 式）=09-10 已否不复发（乱编号比没编号糟）；
  ②退出标题样式族（克隆 Heading N 视觉、摘大纲血缘的自定义小标题样式）——治
  「按样式列导航」的查看器（用户截图疑似此形态），因疑点未实证（Word 导航不受
  影响）而缓行，用户实测 WPS 仍刷屏则另批补（十行代码量级）；③剥直挂字体字号
  纯换 pStyle 即可（写手标题无直挂字号；素材小标题带直挂时观感变化小，实测不足
  再议）。测试：翻转 09-12 特征测试一例（素材章标题「样式不动视觉不变」→按深度
  降级）、更新前批武装素材 e2e（标题段改挂 Heading3、样式 3 不再迁入整本）、新增
  3 例（深度 2 降级+表格内同降+节文件未动 / 深度 1 维持 H2 / 前置区与 NON_PROSE
  护栏——守卫测试必须放深度 2，深度 1 时目标级=源级降与不降同形）；sidecar 887 绿。
  生效须重启 sidecar。
- **素材拷入编号剥除批（2026-09-16，「素材自有编号保真」拍板收窄；素材编号标题双通道根治）**：
  动因=用户实拍整本「6.1 数据建模」下小标题渲染「1.1.2.4.1 数据项定义」，溯源链
  闭环：素材库《流程管理(BPM)平台介绍(1).docx》（云枢/奥哲）heading 5 样式自带
  多级编号（样式级 numPr）、标题段又直挂 numPr（真实素材双通道并存，段落级优先
  渲染）——docx_material_inject 拷入节文件、docx_assemble_volume 再迁入整本，
  两层迁移都原样保号；合册自己盖的「第六章/6.1」章序与素材内部五级深号同页
  并存即乱号观感。09-13 批防线的覆盖缺口逐层实证：①`_strip_copy_residue` 只剥
  直挂 outlineLvl 与死书签，不碰 numPr；②`_merge_missing_styles` 迁入标题样式
  的 numPr 原样保留（有特征测试钉死「素材自己的段落照常编号」）；③
  `_NUM_STYLE_GUARD_NAMES` 只剥解析到宿主内建标题/Normal 的绑定，素材编号绑定
  指向迁入改名样式（heading 5 2 2）不触发；④合册 ⚠️ 双重编号探测只查目录树
  节点名文字前缀，节内自动编号不可见；⑤写手 10 个 docx 工具无摘编号通道——
  模型看见了也修不了。修复三件（全 sidecar）：①`_strip_copy_residue` 加
  heading_ids 参数——标题类段落（pStyle∈源标题样式集〔判据=样式名含 heading/标题
  或样式带 outlineLvl，改名变体 heading 5 2 天然命中〕或直挂 outlineLvl）直挂
  numPr 整棵剥；三个拷贝循环（material_inject/source_inject/assemble）循环前
  各算一次 `_heading_style_ids(src)` 传入（剥除发生在 pStyle remap 前，用源样式
  判性）；②`_merge_missing_styles` 迁入副本中标题类段落样式剥样式级 numPr——
  在编号迁移触发前剥，仅被标题样式引用的编号定义随之不迁（numbering.xml 不留
  孤儿）；③validate_body docx 节加提示级「〔自动编号〕N 个标题段带自动编号」
  清点（直挂/样式级两形态都数），不判不过。判据收拢 `_style_is_heading_like`
  谓词（`_heading_style_ids` 重构复用）。**拍板修订**：「素材自有编号保真」
  （09-13，腾励「1.1 奥哲介绍」渲染原样）收窄为版式与内容保真、**编号标题不
  保真**——09-10「节内小标题不自动编号+乱编号比没编号糟」铁则从「合册不加号」
  扩展到「拷入的号也摘掉」。被否两案：只剥段落直挂 numPr 不剥样式级=无效（样式
  照旧出号，BPM 素材正是双通道）；拷入 numPr 一律剥不分标题=正文列表（圆点/
  (1) 型）保真受损——正文列表样式不命中标题判据，编号定义照常迁入。测试：翻转
  09-13 两处特征测试（迁入样式编号保留→剥除，e2e 同步扩双通道+正文列表保真面）、
  新增 `_strip_copy_residue` 单测（标题段剥/直挂大纲段双剥/正文列表保真/不传
  参数旧行为）、validate_body note 一例；sidecar 883 绿（knowledge_api database
  is locked 为负载型 flake、单跑即绿、与批无关）。存量节文件不回填（09-13 同
  口径）：旧节文件重跑合册即净（三循环共用此卫生）；生效须重启 sidecar。
- **临时参考件纪律（2026-09-14，全提示词层零代码）**：动因=用户问「标书写完后
  把类似案例扔进输入框（不进知识库）让模型读取后填充」——机制链路本来就通
  （上传落 sources/ → parse_document → 按行号读区段 → revise/source_inject），
  但流程没为该场景定制：素材先行五步与写手硬纪律都只认素材块，临时案例走
  计划外路径纯靠模型自觉，且 document-parse 的 [untracked] 对账可能把它误引到
  来源确认流（反问主文件还是补充文件）。修订四件：tender-body SKILL.md 概述
  加「临时参考件」定义（=sources/ 里用户明说参考的非招标文件；定位=写法参考，
  不是写作依据也不是素材库资产）+ 第 0 步 [untracked] 裁决分支（用户让当参考
  用 → 不走来源确认流）+ 第 2 步派发意图句给参考路径+行号区间（写手自行按
  区段 read_file，单节就地写主线程自己读）；section-writing.md 新增「临时参考件」
  节（三铁律：只借写法不抄事实——案例项目名/客户名/数字不进正文，残留扫描对
  该类文件没有防线、纪律是唯一防线；冲突以招标为准；叙述内容唯一形态=改写，
  不整段拷贝；案例不进 block_ids、用法在完成摘要说明）；写手子代理 prompt 加
  同款一句（未给参考件不主动翻 sources/）；主 prompt 词汇表补临时参考件定义。
  **刻意不动两处**：docx_source_inject docstring 不扩口径（窄口径让「案例只改写」
  有工具层配合，扩=邀请整段抄案例）；validate_body 不加案例残留/使用校验（案例
  文件名不在素材库元数据，接线成本>收益，纪律层先上、出事故再加机械防线）。
  生效须重启 sidecar。
- **整本交付结构缺口批（2026-09-14，目录页/附件壳节/空容器抑制/前置区编号）**：
  动因=真实任务（东方证券比选）整本质检发现三处结构缺口，run trace 实证模型
  全程按 SKILL 执行、合册返回两次点名——是设计缝隙非模型违规：①两册整本均无
  目录页（招标 3.7.3 要求编制目录；tender-outline 只硬性规定「封面」首节点、
  通篇无目录节点规则，合册端 toc_lines 提取/对账机制从未触发——机制上下游
  齐全、断链在中间）；②4 个物理附件节（营业执照/社保票据/信用截屏/安全测试
  报告）按 09-06「全无命中不建节」拍板在整本里零落点（营业执照是废标级资格件，
  只活在聊天收尾汇报里），且容器「其他资料」子节点全被跳过后章标题光杆空壳
  （合册发容器标题在先、无空容器抑制）；③写作指引写「建节后批注点名」而
  SKILL 写「不建节」——guide-format 示例行措辞过宽被模型泛化到全无命中的行。
  **用户五拍板**（业务原则=交付物必须在文档内自解释，评委/装订的人不看聊天
  记录）：附件全无命中→**建壳节**（标题+一行贴入位「（此处贴入：XXX 复印件，
  加盖公章）」——对齐招标件自印「在此粘贴身份证复印件」惯例、材料贴上即覆盖
  不存在忘删问题 + Word 批注详述，推翻 09-06 第三分支）；目录页→**合册机械
  生成**（树节点只定位置=语义，条目=实收章节=机械，符合 LLM 语义/程序机械
  铁律）；形态=**Word 目录域+缓存静态清单**（应用内预览见清单；Word/WPS 更新
  域即得带页码正式目录；不更新也能交）；空容器→**抑制章标题**（壳节后基本
  不触发的纯兜底）；**前置区不占章号**（目录节点之前的非封面节点如编制索引
  不占章序，正文从目录后第一章起编；树无目录节点维持全编号=旧产物兼容）。
  **存量任务产物不修复**（用户拍板，新机制只对之后的生成生效）。代码
  （docx_ops）：`_TOC_NODE_NAME` 按名识别（对齐封面先例）；无手写节文件→循环
  记锚点、循环后 `_insert_mechanical_toc` 在该位置插入目录页——标题刻意不用
  Heading 样式（防目录域/导航自引用），域三件套 begin/instrText `TOC \o "1-3"
  \h \z \u`/separate/缓存条目/end，**缓存包裹在域内**（更新域整体替换、静态
  页码不做——页码排版后只有 Word 知道）；有节文件→手写优先（并入+toc_lines
  对账照旧，标题不再占章号）；`_tree_nodes` 增产原节点，`_empty_containers`
  预计算子树无将产出叶子的容器（判定与主循环同款：prose 叶恒产出〔缺文件
  照发标题、缺失另有点名〕、NON_PROSE 以文件为准、目录节点恒产出）→主循环
  按对象身份跳过章标题；目录页条目=树序（编号+标题按层级缩进），未产出附件
  节标「（另附）」；unfilled 兜底报告行保留（正常应恒空=壳节漏建探测器）。
  技能：tender-outline generate.md **规则 11**（封面后必有「目录」节点、位置
  =前置区末尾〔缺省紧随封面；「XX 装订/编排于目录前」类要求时排其后，如编制
  索引〕、交付形态固定模板或附件填充、不写节文件）+SKILL.md 提点+示例树/目录
  说明行；tender-body SKILL 三分法第三分支改建壳节+「目录节点不建节不派发」、
  合册段与注意事项目录页段改机械生成描述；section-writing 物理附件节壳节细则
  （废标级资格件绝不许只登记不建节）；guide-format 模式列三分+附件两行示例
  （命中贴图/全无命中壳节）+目录行示例；agent.py 写手 prompt 壳节出路同步；
  check_pipeline 仅注释口径更新（代码零改——NON_PROSE 分类天然不把目录节点
  报缺）。测试：test_docx_ops +4（机械目录页+前置区编号/手写目录不占号/附件
  壳节并入/空容器抑制）+ test_skills 锚点 1 例（旧「线下准备/不建节」口径不得
  回流）；806 绿+check.sh 全绿。**须重启 sidecar 生效**。

- **样式/编号迁移去重与拷贝卫生批（2026-09-13，整本目录乱号根因修复）**：动因=
  用户实拍整本导航「1.3 16.1 工作目标…」式乱号，全链路审计实证一个缺陷族——
  素材/招标件拷贝在注入与合册两层共用 `_merge_missing_styles`/
  `_merge_missing_numbering`，迁移定义只按 styleId 去重：①**同名不查**（D1）：
  「奥哲介绍」所在的腾励标书素材自带 styleId=3 name="heading 2" 挂多级编号
  （素材库 8 个 docx 中 3 个「武装」，腾励带 19 个编号标题样式），迁入后与模板
  内建同名并存——WPS/LibreOffice 按名解析把整本全部二级标题套上连续序号，**正文
  98 行污染**（含全部节内小标题 1.4/1.7…），打印正文同样带号（交付级；旧任务
  商务技术册见「1.1.1.1.3.10 流程校验」六级深编号上限与绑 Normal 的定义）；
  ②**撞 id 异名静默跳过**（H1）：其他资料的 heading 3/4 段绑到先迁入者占用的无关
  样式（'Default Paragraph Font'/'Body Text'），id 先到先得随树序漂移不可预测；
  ③**编号 pStyle 链接不改写**（H2）：迁入多级编号仍指源样式 id，可绑到别人样式；
  ④**直挂 outlineLvl 漏摘**（D2）：`_demote_extra_headings` 只认标题样式，格式件
  段落（附件8/9/11、表1）与被写手改写过的整段正文带直接大纲级别混进导航。
  修复五件（全 sidecar，模板/前端/Rust 零改动）：`_merge_missing_styles` 去重键
  扩为 **styleId+样式名双维**——同 id 同名或定义等价（`_norm_style_xml` 剥
  id/rsid/default）沿用宿主（「素材标题段自动吃宿主定义」09-08 拍板语义保持）、
  同 id **异名**分配新 id 迁入并改写元素与迁入簇引用（pStyle/rStyle/tblStyle、
  basedOn/link/next）、迁入副本**同名改命**（"heading 2 2"…直到唯一——断按名
  合并路径，id 绑定与观感不变）+剥 `w:default`，返回 (moved, id_remap)；
  `_merge_missing_numbering` 增 style_id_remap——迁入 abstractNum 的 lvl/pStyle
  按表改写，且**解析到目标内建标题（heading 1-9/标题 1-9）或 Normal 的绑定一律
  剥除**（「章节编号不走样式绑定」铁则的机械化防线；素材自有样式编号在新 id/
  新名下照常保真——腾励「1.1 奥哲介绍」渲染原样）；新 `_strip_copy_residue`
  接入素材/招标件/合册三处拷贝循环——剥拷入段直挂 outlineLvl（导航元数据非
  版式，「保真」不含它）与 `_` 前缀死书签（_Toc 指向源文档目录域，同段拷多节
  造成书签 id 重复）；`_demote_extra_headings` 判据扩为「标题样式 **或** 直挂
  outlineLvl<9」（兜底存量节文件）；validate_body docx 节加提示级「〔大纲级别〕
  N 段直挂」清点（读视图看不见的污染让模型可见）。验证：新增测试 10 例，sidecar
  709 绿（knowledge_api 偶发 database is locked 为负载型 flake、排除新测试复跑
  亦现、与批无关）；真实任务沙箱重合册——重名组 3→0、直挂大纲 6→0、书签重复
  1→0、LibreOffice 书签 55→49 纯骨架、正文编号污染 98 行→0、素材段落（公司简介
  等 18 段）正确绑回真样式（观感恢复；页数 103→121 系观感归位的正常变化）；真实
  数据已重跑同款合册。存量节文件内部历史重名不回填（与注入修复批同口径：重写/
  重注入才走新逻辑，合册侧兜底保证交付物干净）；**运行中的 sidecar 须重启**
  （旧代码在内存里，模型再调合册会回退污染）。w14:paraId 重复（Word 重存自动
  再分配）与 moveFrom/moveTo 修订形态（现网 0 处）记录在案不处理。

- **读图撑爆上下文 + docx 并发互写坏修复批（2026-09-13，两刀全机械层）**：动因=
  真实 run「资质证书」节写手一 turn 连发 8 条 docx_comment_add，ToolNode 真并行
  执行原地 save 互写坏节文件（BadZipFile），写手转而 read_file 读知识库证书
  PNG「看一眼」——deepagents 后端对非文本文件**把整文件 base64 内联进消息**
  （无分页无截断），1,565,843 字符 → 下一次模型调用 1,113,773 token 撞 1M 上限
  400；压缩自愈正确触发但数学上无解（巨型内容是刚返回的最新一条消息，摘要只
  逐出旧消息；日志实证两次一模一样的 1113773 重试=截断点 cutoff≤0 什么都没删
  ），最后靠「子代理失败→可重派一次」兜底活下来（47 节全成稿）。修两刀：
  ①**fs_guard 读拦截**——GuardedBackend 覆写 read（异步 aread 是协议默认
  asyncio.to_thread(self.read) 委托，覆写一处双路生效），扩展名命中图片
  （png/jpg/jpeg/webp/gif/bmp/heic/heif）/PDF/Office（doc/docx/ppt/pptx）即返
  `ReadResult(error="[读取被拒绝]…")`（error-only 是 schema 合法形态，不打崩
  run），文案带正确出口：图片→docx_image_insert（image 参数直传路径）、pdf→
  parse_document/按页渲染插图、office→docx_section_read/parse_document；自持
  扩展名常量不 import 上游私有映射（升级不断）。文本读零变化（工具层自带 100
  行限+80K 字符截断——唯一无上限的就是二进制分支，本刀已断）。技能/提示词
  从未教模型 read_file 读二进制、docx_image_insert 自读文件不经后端，零冲突。
  ②**docx_ops 同文件并发写防线**——模块级 `_PATH_LOCKS`（按解析后绝对路径
  threading.Lock，条目只增不删）+ `_docx_path_lock` contextmanager 包住七个
  改写工具的「开→改→存」整段（create 含恢复点轮换/comment/image/revise/
  material_inject/source_inject 含重复注入探测的 check-then-act/assemble 按卷
  输出），存盘统一 `_atomic_save`（uuid 后缀 tmp 同目录 + os.replace，
  artifact_store 同款；合册原固定 `.tmp` 名并发互踩一并修掉）。读者零改动：
  原子替换让 section_read/validate_body/合册读节永远看到完整旧版或新版；锁专治
  并行写丢更新（证伪检验：patch 回旧形态跑并发测试，8 条批注只剩 1 条——后
  完成者整存覆盖）。**锁=用户不可见 plumbing（原子落盘同类，用户已认可）**
  ，不违「跨 run 无锁」铁则（那只管后台协调，此处是同进程文件写完整性）。
  测试：test_fs_guard +3（图片/PDF/Office 拒绝与出口、文本不变）、test_docx_ops
  +1 并发回归哨兵（Barrier 8 线程同文件批注：全成功/8 条不丢/无 tmp 残件，
  contextvars.copy_context 逐线程拷贝复刻 ContextThreadPoolExecutor 生产形态
  ——裸 Thread 不带 runctx）；sidecar 736 绿。明确不做：不改写手提示词（锁已
  让并行调用安全，拒绝文案即教学）、不动 deepagents 逐出语义、不按模型视觉
  能力差异化图片拒绝（本产品贴图唯一正道=docx_image_insert）。**须重启
  sidecar 生效**。

- **09-14 表格通道/回读收敛批 review 修复四件（2026-09-14，小批）**：review 挂在
  当日未记录的「写手读取瘦身+富内容工具」批（body 块混排/docx_diagram_insert/
  docx_html_figure/revise 现文块/派发开工纪律——其 AGENTS 记录待补）之上：
  ①`_parse_body_blocks` 行宽超 header **报错不截断**（原 `_pad_row` 把超宽行静默
  裁到 header 列数丢格，违「不猜不吞」；少列补空的宽容保留）②两处无图注出口
  （`_render_and_insert`/`docx_diagram_insert`）的「先删旧图/旧表再重插」是写手
  执行不了的死胡同（无删表删图工具且重插会翻倍）——改为「图注在插入时经
  caption 给出；漏了可接受无图注或批注请用户补；勿重调本工具」③revise 现文块
  段落截断 200→`_VIEW_TEXT_LIMIT`(800)（长段尾部替换结果原本被裁掉，「把结果
  送到眼前」对长段失效）④dispatch_enrich 图示列透传过滤对齐 validate_body 对账
  口径（`[、;；,，]` 切分丢空与「—」，混合记法「表:对比、—」不再把「—」当
  计划项下发）。测试 test_docx_ops +2（超宽行报错/少列宽容/长段现文尾部可见）、
  test_dispatch_enrich 图示透传 +混合项两断言；183 绿+ruff 零告警。**须重启
  sidecar 生效**（工具文案与校验逻辑）。

- **element_lines 坐标系统一（2026-09-10）**：parse/docx.py 表格从整块 append 改
  逐行 extend——此前表格 md 的内嵌换行不占 lines 下标，element_lines 落在折叠
  坐标系、md/outline 落在展开坐标系，表格后所有元素行号累计漂移（实测 13 表
  拉开 140 行），按行号注入必「未映射/错元素」（素材块勾选区间在表格后错位的
  正确性根因）。join 产物逐字节不变、仅映射坐标与最终 md 对齐；注入工具
  （docx_source_inject/docx_material_inject）现场重跑解析拿映射，**对修复前
  上传的素材即刻生效、无需重传**。测试 test_docx_ops 三例（坐标系回归/表格后
  outline 区间端到端/素材块区间注入）。

- **单图插入工具 `docx_image_insert`（2026-09-08，docx 直出管线的放图通道补全）**：
  动因=用户拍板「证书贴正文必须做」——此前独立图片（证书复印件/扫描件/截图）
  进正文无通道（图片只能随素材块/招标件元素级拷贝，知识库证书在正文只能文字
  陈述）。工具（docx_ops.py，@tool 注册 TOOLS）：`dest/image/after/page`——
  dest 走 _dest_path 同口径；图源三类=知识库抽取图
  `knowledge/parse/<stem>/images/img_001.png`（listdir 即清单无 DB；证书扫描
  PDF 抽出=每页一张、文件序号即页序）/任务图 `sources/<文件名>`（容忍任务
  前缀形态）/**PDF 原件按页现场渲染**（复用 parse/pdf.render_page_png，tempfile
  即弃——图片字节进包内 media，兜住 docx 扫描区过滤/60 张截断/JBIG2 抽不出）；
  after=P 序号（revise 同口径 doc.paragraphs[i-1]，可带 P 前缀）留空=节末
  sectPr 前；宽度程序定死全宽（页宽−边距，不给模型尺寸自由度）、居中。
  **修订标记是技术必须**：drawing XML 让 python-docx 生成（add_picture）后
  run 手包 w:ins + 段落标记 pPr/rPr w:ins——纯图片段无 w:t，缺段落标记修订
  会让拒绝视角多出空行（_flatten_rejected 自校验必拒），带上则拒绝修订=
  整段含图消失、语义正确；图片段不挂 Tender Body（正文样式首行缩进会推偏
  图片）。边界：webp 报人话（python-docx 不识别）、docx 原件不作图源（media
  直取排序语义模糊，提示传 PDF/图片版）、图源 resolve 后 workspace containment。
  连带接线：search_company_assets 命中条目含抽取图时附「含图 N 张」+图片路径
  +docx_image_insert 指引（模型由此知道证书有图可贴）；tender-body SKILL.md
  素材修订条「写作工具没有放图通道」过时说法更新为两分（素材块内的图=注入、
  独立图片=本工具）+推理撰写/注意事项接线、section-writing.md 推理撰写段、
  写手 prompt 硬纪律同步两分。零改动即可工作：view_lines 已有〔图×N〕标签
  （.// 深搜不受 w:ins 影响）、合册 _migrate_images 深搜 blip 图片不丢、
  docx-preview 接受视角渲染 w:ins 图片、validate_body 图片段=空行免检。
  已知限制：python-docx 的 doc.inline_shapes 高层视图只认 w:p 直接挂 w:r
  形态，修订包裹后匹配不到（仅测试断言层注意，文档本身合法——Word 对修订
  图片就是 w:ins>w:r>w:drawing 结构）。测试：test_docx_ops.py 六例（落位/
  双修订标记/全宽/自校验不漂移/节末追加/PDF 页渲染+任务前缀+页号越界/容错
  五形态/已修订节续插）+ test_knowledge_tools.py 检索图片行一例，602 全绿。

- **待办批注体系 `docx_comment_add`（2026-09-08 交付防线批，占位文字退出正文）**：
  动因=三路审查结论「占位文字可一路走进交付的合册 docx」——合册此前对
  【待补】【待澄清】零扫描零警告、validate_body 清点是提示级，用户拿合册直接
  打印投标可能带着占位交出去（废标级风险）。用户拍板升格方案：**缺料/待澄清/
  待核验的正规落点=Word 批注**（打印与 PDF 导出默认不带、Word 审阅侧栏可见、
  面板预览可见高亮），正文禁止任何占位文字。技术前提=python-docx 1.2.0 原生
  `Document.add_comment(runs, text, author, initials)`（锚定 run 区间：段落内插
  commentRangeStart/End+reference run，批注本体在 /word/comments.xml）+
  docx-preview 0.4 `renderComments`。新工具 `docx_comment_add(path, text,
  after)`（docx_ops.py，after=P 序号同 revise/image_insert 口径、空=节末；段落
  直接子 run 为空时补零宽锚 run——不往修订子树里插标记；author=灵燕智能）。
  配套四层：①**读视图**view_lines 段行尾〔批注：…〕（截 40 字）+头部「待办
  批注 N 条」——模型回读节文件能看到自己留的待办；接受视角投影
  （section_text_lines/section_lines_labeled）零污染（批注元素无 w:t）；
  `section_comments_labeled(doc)` 定位清点（P 标签+文本，表格内/跨段锚定落「?」
  兜底防漏）。②**合册**：`_merge_missing_comments(src, dst, elements)`——随
  段落 deepcopy 拷入的 commentRangeStart/End/commentReference 引用源 comments
  part 的 id，按拷贝元素实际引用迁条目（跳过被丢弃的节标题段锚）、分配整本
  未用新 id 重映射（与 _merge_missing_numbering 同构）、源查不到的陈旧标记摘除
  防悬空；合并行追加「（含批注 N 条待处理）」；**内联占位兜底扫描**——
  body_contract.PLACEHOLDER_MARKS（【待补/待澄清/待补充 三前缀，validate_body
  与 docx_ops 共享真值）按接受视角逐行扫，命中出 ⚠️ 行点名「应改用批注」。
  ③**validate_body 口径切换**：docx 节内联占位从 notes 清点升级为 **issue**
  （文案给改法：删文字+改用 docx_comment_add）；批注清点进 notes
  （`[待办批注/占位] 共 N 处`，收尾点名）；md 节是旧任务兼容形态（无批注
  能力）维持清点不判不过；空节 issue 文案同步改。④**纪律接线**：tender-body
  SKILL.md（第 2 步缺料段/注意事项「唯一允许的内联标记」句重写为「正文禁止
  占位文字、待办全走批注」/第 4 步合册批注迁移/第 5 步收尾点名对象改批注）、
  section-writing.md（通用纪律/子代理三处）、agent.py 写手 prompt 硬纪律
  （缺料/待澄清→加批注带回）、guide-format.md 的【缺】保留（指引表是 md，
  合法占位）。历史节文件不自动迁移（重写该节才走新逻辑，与注入修复批同口径）。
  测试：test_docx_ops.py（锚定/视图/投影干净/修订自校验不漂移/错误路径 +
  合册迁移两节 id 重映射无悬空 + 内联占位 ⚠️）+ test_validate_body.py 四例
  （docx 占位=issue、表格 T 定位、终稿视角、批注清点）。

- **整本最终稿标识+交付提醒（2026-09-08，同批前端）**：ArtifactPanel body 组
  「整本-*.docx」品牌色徽标「整本 · 最终稿」+组内置顶（isFinalDoc 判定单源，
  wbRow/分组/DocxView 三处共用）；DocxView 整本文件常驻警示行「交付前请在
  Word 中接受所有修订、解决全部批注——本预览显示的是接受修订后的效果」（节
  文件不提示：中间产物、提示是噪音）；DocxPreviewBody 渲染选项开 renderComments
  （批注高亮可见，此前面板看着干净但文件带待办的反差不可见）。配套：工具中文
  显示名补全批（并行会话已落 13 条映射，本批删死键 search_knowledge 三处+补
  docx_comment_add=「添加批注」，toolDisplay.test 冻结镜像同步 21 工具）、
  四色徽章图例（DirectoryProcessor 导出 BadgeLegend：MAND=资格/强制条款、
  TPL=格式模板、REQ=商务技术要求、SCORE=评分项——目录查看态头部与
  GuideFileView 说明段两处渲染，四个前缀首次有解释）、KB 冷启动清单
  （kbShared KbHeroEmpty 空态列 7 项投标常用材料：营业执照/资质体系证书/近
  三年合同案例/人员证书/财务审计报告/社保缴纳证明/公司介绍）、素材库空态
  补「仅 .docx」、知识库类型加 `social_security`（社保缴纳证明，fact，
  time_fields=[period]，hint=社保/参保/缴纳证明——投标高频件此前落 other
  不参与时效锚点；加类型零迁移，前端 API 驱动零改动）。

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
  **版式取值换参考件+主题引用防线（2026-09-13）**：版式档改为按用户提供的
  版式参考件（一份高校学位论文格式规范，出处不具名）实测导出——标题降一号（H1 小二→
  三号，H2-4 不变）、标题中西文同族（ascii=黑体，不再 Times 混排）、封面
  两档改加粗、页码改右下角 Times 五号、新增 TOC Heading+toc 1..3（点线
  前导+阶梯缩进）与 Tender Header 样式（不建页眉部件）、页眉距 1.5cm/
  页脚距 1.75cm。**关键修复=ＭＳ 明朝根因**：python-docx 默认模板的
  Heading/Title 等样式天生带 `w:*Theme` 字体引用（OOXML 里 *Theme **优先于**
  同名显式属性），而 theme1.xml 东亚字形是**空串**——显式写的黑体/宋体被
  主题引用压住从未生效，落空时 Word 回退应用默认东亚字体（Mac/无中文语言包
  Office=ＭＳ 明朝），素材合并迁入的带引用样式同病。三层防线：`_set_fonts`
  摘 *Theme 属性、`_harden_theme_and_defaults`（docDefaults 显式宋体+lang
  eastAsia=zh-CN、theme major/minor 东亚字形填黑体/宋体——后者兜改不了的
  素材迁入样式）；模板自检+test_docx_ops 加「无 *Theme 残留+theme 字形
  非空」回归守卫。存量整本要**重跑合册**才吃到（合册每次现读模板）。
  参考件条文写「四边 25mm」与文件实际（上下 2.54/左右 3.18）不符，取文件
  实测值、常量留 MARGIN_V/MARGIN_H 两行可改。**二批（同日，版式库预览复现
  后）**：①python-docx 默认模板还给每个内置标题配了**伴生字符样式**
  （Heading1Char..4Char/TitleChar，Word 2007 旧配色 #365F91 蓝/Calibri/四级
  斜体），段落样式 w:link 指向它们，docx-preview renderStyles 把链接字符
  样式追加在同选择器 CSS 规则**后面**（同优先级后写者赢）→ 预览里标题永远
  旧蓝脸而 Word 本体正常（预览即用户所见，修=伴生样式随段落样式同步硬化，
  `_style_char_twin` 按 styleId 匹配）；四级标题斜体继承一并显式关掉。②
  示例页重排成真实装订顺序三页**封面→目录→正文**（用户点名「封面在目录
  下面很怪」）；分页用段首显式 w:br run——docx-preview 的 split 只认样式级
  pageBreakBefore 与 w:br 元素，不认段落直接格式的 page_break_before。
  模板自检与 test_base_template_layout 同批加伴生样式/斜体守卫。

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
  .docx（上传入口=底部通栏按钮，与素材库/KB 同款）、右=docx-preview 版式
  预览复用 raw 字节端点；上传=入库不自动激活、显式「设为默认模板」生效——
  语义分离防误传即全局生效；头部操作=下载（fetchTemplateRaw 拉当前字节+
  downloadBlob 延迟 revoke，不走 5min 预览缓存）/删除（两步确认 3s 复位，
  素材库教训；内置恒禁用+「内置模板不可删除」））。
  **「应用到任务」换装整链已删（2026-09-08 用户拍板「没有业务意义」）**：
  apply 端点/`restyle_docx`/RestyleReport+RestyleResult DTO/前端弹窗与
  `applyTemplate`/test_apply_restyle_to_task 全部移除，dto.gen.ts 已再生——
  模板只管新节版式（换模板只影响之后新建的节，已写内容不动），不回填已写节。
  **全局位定名「默认模板」（2026-09-08 用户拍板，原「设为当前/当前生效」）**：
  右栏操作按钮恒显示（选中项即默认时禁用态「已是默认」——按钮原先只在非默认
  项上出现，选中默认项时界面无任何设置入口，用户点名缺陷）；列表徽章与提示
  文案同批改「默认」。
  sidecar `app/api/templates.py`：GET /templates（列表）/ POST 上传（20MB
  上限、可打开校验拒损坏件、同名覆盖=新版语义）/ DELETE（内置不可删；删
  默认位回落内置）/ {key}/activate / {key}/raw（FileResponse 不进 dto）。
  存储=data/templates/；默认模板位=app_settings `docx_template`（缺省=内置），
  docx_ops `_active_template_path()`（建节/合册每次现读，改模板即时生效无
  重启；用户模板无 Tender Body 样式时 `_body_style` 返回 None 正文段降级
  Normal 不失败）；list_templates stat 竞态跳行不 500。
  前端：TemplatesView 不再依赖 ['tasks'] 缓存（useTasks 随弹窗删除移除——
  历史教训：**同 queryKey 换 queryFn 会互相污染缓存形状**，Sidebar 任务树会
  拿到 {tasks} 对象崩掉）；上传/删除后连带 invalidate ['template-raw']
  （同名覆盖后预览防旧缓存 5min）。测试 tests/test_templates.py 两例
  （CRUD+激活即生效），602 全绿；前端 tsc+oxlint+vite build 全绿（本机
  node 20.12 撞 rolldown styleText 的旧环境问题已随 .nvmrc 22 消解）。

  **模板库只读工具 list_templates（2026-09-09）**：动因=实测用户问「我们有多少
  模板」，agent 全盘扫 23 步答「没有版式模板库、0 个」——模板在 data/templates/
  与 app/resources/ 都在 workspace 外，文件工具结构上看不见。修法=新工具
  `app/tools/templates.py`（无参只读，返回总数/内置与用户上传数/当前默认/逐项
  清单+换默认的用户出口；错误返回 `[查询失败]` 字符串不打崩 run）；**读侧真值
  下沉 docx_ops**（BUILTIN_TEMPLATE_KEY/NAME、templates_dir()、
  active_template_name()、list_templates_info()→list[dict]）——api/templates.py
  改为消费共享函数（tools 反向 import api 会循环导入：app.tools 包初始化先于
  api 模块执行），既有 HTTP 测试即重构防漂移守卫；`_active_template_path` 内部
  改用同侧 helper（行为不变）。主 prompt 词汇表句加「模板库现状用 list_templates
  工具查询，模板在任务工作区之外、不要用文件工具检索」。只读不写：上传/删除/
  设默认留用户界面（探测+用户裁决铁则）。测试 +3 例（空库/上传+激活翻转/
  错误路径），sidecar 619 绿+前端 186 绿；toolDisplay 显示名「查看模板库」+
  LayoutTemplate 图标+冻结镜像 22 工具同步。

  **「模板库」定名改「版式库」（2026-09-09 用户拍板）**：动因=「模板」二字
  三义歧义（版式资产/招标格式件/日常「拿旧标书当模板」），已实测两次误导
  （「为整本应用模板」→agent 列素材库文件当模板候选；「我们有多少模板」→
  答成没有模板库）。改名范围=**用户/模型可见文案层**：侧栏入口/正文措辞/
  按钮（设为默认版式）/内置名（内置标书基准版式，BUILTIN_TEMPLATE_NAME）/
  TPL 徽章图例（格式模板→格式件（招标方给定），GuideFileView 定性摘要行
  同步「N 份格式件」）/api 错误文案/工具输出与 docstring/主 prompt 词汇表
  （版式库=纯版式资产（原「模板库」）+「不存在把版式应用到整本的工具」；
  守卫句「不要把素材库文件当『模板』候选」**保留日常词**——用户提问用日常
  词、守卫按日常词触发）/工具显示名（查看版式库）。**不改清单**：代码标识
  符（/templates 端点、docx_template 设置键、list_templates 工具名、
  data/templates/ 目录、TemplateInfo/BUILTIN_TEMPLATE_KEY）、「模板填充」
  指引模式词与 NON_PROSE_DELIVERY「模板或附件填充」（body_contract↔guide
  md↔前端三方契约，且指招标方待填件、日常语义正确）、skills 内招标方语境
  的「格式模板/模板」（requirements-format.md、assemble_tender registry
  type=模板）、KB 分类「参考资料/模板范文」（日常语义指参考范本）、
  AGENTS.md 历史记录（定名沿革记录在各文件 docstring）。测试同步：
  test_agent 守卫关键词两条（版式库=…/把版式应用到…）+ test_templates 三例
  断言；sidecar 619 绿+前端 186 绿。

  **封面页机制（2026-09-09，树首节点约定）**：设计拍板=封面进目录树当每册
  树首节点（节点名固定「封面」，`docx_ops._COVER_NODE_NAME`，合册按清洗后
  标题识别），走现有格式跟随/写节文件通路——结构真值在树、合册不做隐藏
  特例（封面字段值是语义判断，不进机械的合册工具）。五件落地：①**tender-
  outline**：generate.md 规则 10+SKILL.md R2 一句+annotation.md 交付形态
  封面条目——默认每册树首建「封面」（分析产物明确不需要才跳过）；有封面
  格式样例且原件 docx→模板或附件填充（拷样例+填空），无样例或 pdf→正文
  编写（排版成形，pdf=照样例复刻版式近似）。②**模板两新样式**：
  Tender Cover（黑体二号 22pt 居中，封面大字行）/Tender Cover Sub（小三
  15pt 居中，落款行），make_base_template.py 再生入库；示例页带两行示例。
  ③**revise 插段放行样式名**：insert_after 条目可选 `style` 字段（样式
  **名**），`_style_id_by_name` 解析为 styleId 传 `_tracked_insert_after`
  （其 style_id 参数早已有）；样式不存在回落 body 样式+返回注记（用户自
  定义版式缺封面样式不失败，与 _body_style 回落同款）。④**合册封面识别**
  （docx_assemble_volume）：树首一级叶子且清洗名=封面→跳过册名 Title 标题
  （封面自带册名）与封面节点自身标题（节文件 Heading1 标题段照旧被
  _is_title_para 剥）、seen_chapter 照常置位（第一章 page_break_before=
  封面独占首页）、`different_first_page_header_footer=True`（首页不同，
  封面页无页眉页脚——无 first 引用时 Word 显示空白首页脚）；无封面树行为
  逐字节不变（存量目录兼容）；封面缺文件两形态照旧点名（prose→缺失正文
  节；NON_PROSE→按附件对待）。⑤**派发块加「今天日期」**（天级，dispatch_
  enrich 输出路径行后）：写手子代理不继承任务上下文块拿不到日期、模型
  自编日期不可信（freshness 换锚同款先例），封面/投标函落款用这行；模块
  docstring「无时间戳」句改「除天级日期行外」（单日内字节稳定，前缀缓存
  无伤），agent.py 写手 prompt 枚举同步。tender-body 侧：guide-format.md
  封面行两态示例+封面行说明（无样例时素材列恒【缺】不检索、缺口进承诺
  提问）、section-writing.md 新「封面」节（排版成形=建节+逐行 insert_after
  带 style；字段值纪律=投标人只从承诺清单、日期只写派发块今天日期）、
  SKILL.md 模板填充二分段补封面一句。check_pipeline/validate_body/
  GuideFileView 零改动（封面=普通叶子+普通指引行）。**页码拍板**：封面
  暗占第 1 页、正文首页显示 2；真分节+页码重设计（正文从 1 起）与目录页
  共用基建、留目录批一起做。已知观察点：docx-preview 对「首页不同」若
  不渲染，面板预览封面页可能显示页码（纯预览层外观）。测试：test_docx_ops
  （模板两样式断言/insert style 命中+未知回落/合册封面六断言/缺文件两形态）
  +test_dispatch_enrich 日期行+test_skills 封面锚点，622 绿；坑=插入段
  在 w:ins 修订包裹里 p.text 读不到，断言须走 _accepted_text 接受视角。

  **章节编号批（2026-09-10，程序化生成、落点在合册）**：动因=整本 docx 章节
  零编号（全链路本无编号逻辑，树格式红线又禁止节点名带号——设计空缺非 bug）。
  方案拍板=编号=树位置的纯函数，在 `docx_assemble_volume` 发标题那一刻拼进
  标题文本，**不走 Word 样式绑定自动编号**（三个实测坑：素材拷入的标题段会被
  Word 一起计数打乱章序、docx-preview 对经典「lvl pStyle 无样式 numPr」写法
  不渲染、节文件单看永远「第一章」）；`_HeadingNumberer`（docx_ops）每册一个
  实例从首章重起，封面不占序，`_is_title_para` 剥节文件自带标题仍按裸名对账
  （编号只进发出的标题段）。**格式可配且任务级**：契约 `tender.directory`
  content 加 `numbering` 字段（Literal chapter/decimal/gov/none，缺省 None
  回落 chapter=第X章全角空格+1.1；decimal=1+1.1；gov=一、（一）1.；none），
  目录编辑界面（DirectoryProcessor）编辑态头部下拉改、查看态显示当前格式
  （非结构变更不触发签名确认条）；dto 层不携带产物内容，dto.gen.ts 无需再生。
  两个拍板：格式件章（投标函等 NON_PROSE）**与正文统一编号**（未产出的不进
  整本自然不占序）；节内小标题**不自动编号+写作纪律**（素材拷入的标题与 AI
  写的标题程序分不清，乱编号比没编号糟）。自带编号探测（探测+提示裁决铁则）：
  节点名匹配 `第X章/一、/（一）/1.1 ` 前缀形态时合册返回 ⚠️ 点名双重编号请修
  目录产物（数字限一两位+空格，避开「2026 年度」年份误报）。skill 接线三处：
  tender-body SKILL 注意事项（建节 title 用裸名/节内小标题不写编号——模型
  自编编号必错，不知道树位置）+section-writing 通用纪律同两条+tender-outline
  无编号红线补「编号由合册自动生成」解释。测试：test_docx_ops 四格式序列/
  封面不占序/格式件统一编号/自带编号 ⚠️/裸名对账不受编号影响，**_DIR_SINGLE
  等夹具同批清成裸名**（原夹具自带「第三章/3.1」会叠加成「第一章 第三章」），
  sidecar 631 绿+前端 tsc/oxlint/build 绿。历史已产出整本不自动改——重合册
  即得编号（派生物语义）。

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

- **派发分组归模型自主规划（2026-09-15，AI 自拆批；取代上批 ①的机械均衡分波）**：
  动因=用户质疑「一节一个子代理」粒度太细——账面核过：粒度不是成本大头（共享前缀
  97% 缓存、输出随内容量与拆法无关），真痛点=节数多→波数多→时间线性涨（波耗时=
  最慢任务）。用户拍板**拆分粒度归模型**（符合「语义判断归模型」铁律；机械
  weight-LPT 是把语义伪装成机械）。行业调研背书：Anthropic orchestrator-workers
  /Claude Code「自己决定派几个」/deepagents task 零粒度约束/Manus 同构；配套惯例=
  数字锚点写提示词（Anthropic effort-scaling：轻任务 1 个代理/复杂 10+）+机械手段
  只做容量层（并发上限，无人管粒度）+覆盖靠程序对账（LangChain「筛 500 之 75 当
  完成」教训——我方 check_pipeline 文件级对账天然兜住）。落地五件：
  ①check_pipeline 删均衡分波参考/_balanced_waves/_MODE_BASE，`[body]` 改
  **待写节清单**（每节一行 `册/名（模式·素材块数）` 零结论；「—」模式显示
  「模式未填」、缺行兜底「指引缺行」；无 ≥4 门槛）；
  ②dispatch_enrich **多节契约**：首行按 `、，,;；＋+&` 分隔多探针（刻意不含
  /——册名斜杠不是节界），逐个 _match_leaf，任一不中先**首行整体单探针兜底**
  （节名自身含分隔符撞库歧义/一真一假名救真节，均收敛回旧版单节行为），仍不中
  才**整体放行不半拼**；
  拼装=共享块一份（纪律/前缀/日期/承诺/方法论）+逐节块每节一份（
  `_section_context_lines` 单点推导，单节输出与旧版逐字节一致零回归）；首行
  只解析节名、意图句放第二行起（顺带修掉旧「整段当探针被意图句打碎静默放行」
  暗坑）；_MAX_ORIG_DESC 200→300（多节首行更长），富描述锚点每节一条带节名；
  `_sibling_lines` 排除集扩为本任务全部节（同任务节互见没必要）、跨册合并候选；
  ③agent.py 写手 spec 改「一个或多个目录节」：首句/逐节纪律（每节独立走
  建节→注入→改写→自查，全部节完成才收尾）/摘要逐节一节一段；**重派守卫
  （09-15 路径批新增）升多节感知**——逐节名检查，任一节本轮已写即拒并点名
  （守卫对多节首行失配即放行=断点续跑整波重放的漏口）；
  ④SKILL.md 第 2 步派发纪律重写（数字锚点+正反例）：轻节（格式跟随/模板填充）
  3~5 个捆一任务连写、推理撰写/素材多重节单独、单任务 ≤~5 节、**同消息并发
  派发防串行退化**（Anthropic 实证不加显式指令模型逐个发起）、每消息 ≤8 任务
  （=并发上限）、不按一级章分批/不按主题扎堆/不做几十节齐发（反例保留）、
  **全覆盖自查**（每节必落入某任务，收尾对账点名）；description 契约=首行节名
  清单（顿号分隔、逐字抄待写节清单、首行禁前导语）+第二行起特殊意图；
  section-writing.md「子代理执行」节同步（含首行契约句改写）；
  ⑤一节一文件/合册/对账/validate_body/兄弟摘要机制零改动（任务→文件映射变了、
  文件粒度不变）。测试：test_check_pipeline 分波 8 例改待写节清单 4 例（负向锚
  「均衡分波」不得回流）+ test_dispatch_enrich +6（多节共享+逐节块+兄弟排除本
  任务节/含分隔符节名整行兜底/一真一假名兜底救真节/全部不中整体放行/意图句
  第二行不破坏匹配/富描述多节锚点）+ test_agent 重派守卫
  多节捆拒 1 例 + test_skills 派发分组纪律锚（负向锚「一节一个」不得回流）。
  明确不做：机械分组守卫（纯纪律，出事故按「纪律先行」路径补防线）；主线程批量
  就地写（串行慢+主线程上下文膨胀触发压缩）；Anthropic 式小评估集（真实任务
  验收代替，trace 三看=多节任务出现且不含重节/波数下降/收尾零漏节）。**须重启
  sidecar 生效**（skills 镜像随启动同步）。

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

- **素材检索复用收口 + 知识库缺口点名（2026-09-10，检索链三态审计后落地）**：
  审计结论=需求/评分链全复用（依据 ID 经 registry 解析成原文+出处进派发，零重复
  检索）；素材链「路由复用、检索重跑」——指引期 search_references 只把块 id 记
  进素材列，派发拼装也只传 id 字符串，写手按素材先行第一步每节再检索一遍（用户
  在确认门拍板的块指派实为参考）；知识库链指引期完全不查（备料对账只对素材库，
  「知识库缺 ISO 证书」要等写手写到那节才经批注暴露）。修法两件：①`dispatch_
  enrich._material_lines` 把素材列 blk id 解析成**逐块名片**（`《标题》（约 N 字
  [，含图 N 处]）｜来源文件：xxx.docx｜id：blk_…[｜备注：…]`，数据源=
  db.mt_list_files+mt_list_blocks、含图数复用 search_knowledge._mt_image_count
  ——**来源文件名必须随行**，check_name_residue 扫旧机构名的 old_names 取自它；
  失效 id 降级「已失效——请自行检索确认」、无 blk id（【缺】/—）维持旧行、
  函数异常降级 id 原文不丢拼装），引导句「可用素材块（直接据此列使用计划并
  注入，无需再检索）」；配套三处文案同步改「选块」语义——section-writing.md
  素材先行第 1 步、SKILL.md 素材修订 bullet、agent.py 写手 prompt 五步表述
  （清单在=直接采用不再 search_references；清单缺失/【缺】/已失效才自行检索
  =查漏出口保留；已派块的节不允许「再搜搜看」，素材不够覆盖走「素材修订+推理
  撰写」组合）。②知识库缺口点名=纯 skill 文案（零代码）：指引生成时对推理
  撰写节在缺口列点名将引用的企业事实/证书（「需：ISO9001/ISO27001、近三年
  同类合同案例」）——**声明本节要什么供用户在确认门对照知识库核对，不是检索
  知识库**；写手仍以写作时 search_company_assets 现场结果为准（查不到照旧批注
  带回）；guide-format.md 示例行与素材/缺口两列说明同步。明确不做：指引期知识
  库真检索（多数节用不到企业事实，会复制素材库重复检索的老毛病）。测试：
  test_dispatch_enrich +2 例（名片解析/无 id 不拼段+失效降级）+ test_agent
  写手 prompt 守卫两条（「直接采用」「不再调用 search_references」），629 绿。

- **知识库材料进正文三处接线（2026-09-10 二批，取代上条②「点名需什么」版与
  「明确不做指引期真检索」裁决——实测 KB 检索 65 次命中但三环节全漏：指引期
  不沉淀/格式件格子不查/复印件一律判线下，命中沉淀不进派发=白查）**：
  ①**指引缺口列升级为「检索沉淀+派发透传」**：指引生成同轮并发跑
  search_company_assets（涉及公司事实的节：资质证书/基本情况/业绩案例/人员
  资格/证书复印件），命中写缺口列【知识库】材料名+关键数字（注册号/有效期
  **照抄原文**，多条分号分隔、含图注明「含图 N 张」）、未命中维持【缺：xxx】；
  `dispatch_enrich._gap_lines` 把缺口列整段透传进派发块「公司材料与缺口」段
  （四类招标编号剥除保零编号契约、CLAR 澄清编号保留原样带回；「—/无」占位
  不拼段）——缺口列是公司事实的唯一调度落点。写手侧填空优先级=派发段
  【知识库】＞现场 search_company_assets＞批注待办，禁止凭印象编（section-
  writing「公司事实填空优先级」节）。②**物理附件三分**（取代一律「线下
  准备」）：缺口列有【知识库】命中（含图）→建节+docx_image_insert 逐张贴图
  产出节文件、库里没有的证书批注点名待线下补；全无命中才登记待填清单。
  ③**派发加「原件定位」行**（`_source_location_line`）：节名对账全部已解析
  outline.json 标题树唯一定位原件区段（附件N/表N 标记双现且核心名相容，或
  清洗核心名全等；同文件相邻 ≤2 行命中合并区间=「表1：报价表」标题壳与正文
  条目两节点形态；0 命中或跨文件歧义不带——定位错比不带更糟），直接给
  docx_source_inject 的 lines 区间（治最重节 71 轮里 ~40 轮在找附件位置）。
  测试 test_dispatch_enrich +7 例（缺口透传/占位不拼/编号剥除 + 定位唯一命中/
  无命中不带/跨文件歧义/相邻壳合并）。

- **写作指引缺口列读者分离（2026-09-13，用户主诉「这段备注真看不懂」）**：
  根因=该列在设计上是**一个字段两个读者**——`guide-format.md` 规定它「随派发整段
  送达写手」（`dispatch_enrich._gap_lines` 机械透传）、同时又是用户唯一可见的缺料
  点名，于是工具名/行号与【缺：…】混写，且【缺】可用代词回指（实测「格式件：
  docx_source_inject 拷第五章格式（L988-L1005）+revise 填应征人名称、单位性质、
  ……【缺：上述公司信息与法定代表人身份证复印件】」——代词指代前半句的工具指令，
  摘出来读不通）。存量规模：实测某真实指引 59 行里 27 行带工具名、2 行代词回指、
  53 行带【缺…】。修法两层（**派发透传零改动**，写手侧语义不变）：①**前端分栏**
  ——`lib/workbenchTable.parseGuideNote(note)` 纯函数按标记切成四段（gaps=
  【缺：…】组，紧跟其后的「——解释」一并归入该条；knowledge=【知识库】到句末；
  clarifies=⚠待澄清 到句末；rest=其余原文，**宽容解析不丢任何内容**，旧格式裸
  「缺：xxx」不强行摘仍落 rest），`GuideDetail` 查看态渲染成「需要你提供」
  「需要你确认」「已从你的资料中找到」三组条目 + 「AI 执行说明」默认收起的
  Collapsible（复用 `components/ui/collapsible.tsx`；内容纯文本无浮层，不触
  overflow 裁剪铁则）。②**生成侧纪律+警示**：guide-format.md 缺口列 bullet 规定
  只写三类内容、**不写工具名与调用参数**（执行链路由模式列+派发说明自动补——依据
  列含 TPL 编号时 `dispatch_enrich` 本就自动加「本节含格式件」与「原件定位」行，
  手写纯属重复）、【缺：…】列**具体字段名禁代词回指**、行号仅在程序定位不到时以
  「原件：<格式名> L起-L止」保留；`validate_body._validate_guide` 补该列读取
  （此前该分支完全不读第 5 列）+两条 **warning 级**检查（工具名正则
  `_TOOL_NAME_RE` / 代词 `_NOTE_ANAPHORA_RE`）——提示不是门禁，存量指引照常可用
  （前端解析器天然兼容新旧两种写法）。测试：workbenchTable.test.ts +8 例（真实
  身份证明行/公司介绍行/待澄清行/破折号归并/裸缺/裸【缺】/空值与纯文本/多条缺口）
  + test_validate_body +2 例；真实数据两向验证（59 行解析零丢字、27 行工具名与
  2 行代词警示准确命中）。

- **写手最小工具集（2026-09-10）**：`agent._BODY_WRITER_TOOLS`（frozenset 13 个
  =docx 七件套+validate_body+check_name_residue+search_references+
  search_company_assets+parse_document+fetch_url——fetch_url 用户明令保留联网
  通道）经 SUBAGENTS spec 的 `tools` 字段收窄（deepagents 语义：spec 带 tools
  **独占**、不带才继承主代理全量；894 轮实测只用这 13 个，22 个工具 schema
  每轮随身携带的固定 token 开销砍掉）；剔除 9 个=ask_human/check_pipeline_
  state/docx_assemble_volume/read_artifact/assemble_tender/publish_artifact/
  update_task_progress/validate_analysis/list_templates（prompt 明令禁止/职责
  归主线程/零调用）。文件七件套由 FilesystemMiddleware 提供、不受 spec.tools
  控制自动随行。test_body_writer_minimal_toolset 三重守卫：名字∈TOOLS 注册表
  （防拼错=静默丢工具）、9 个禁用名不得「顺手加回」、spec 工具集与常量零漂移。

- **整本交付态修复批（2026-09-12，用户主诉「最终产物 docx 目录乱」诊断后三批）**
  ：诊断=骨架没乱（章节顺序/编号与树零错位），乱观感三层——①节文件带修订
  原样合册（实测 603 处 w:ins+605 处 w:del，未在 Word 接受修订前新旧标题成对
  交错）；②131 个节内小标题/素材自带标题用 Heading 样式进大纲（导航窗格/
  自动目录混入杂项、层级常倒挂）；③目录页静态文本只照抄树（正文缺的 6 节
  照列、无页码无目录域）+合册零警告。修法全在合册侧（整本是派生物、节文件层
  审阅入口不动）：①`_accept_revisions_inplace` 元素级「接受全部修订」压平
  （w:del 子树丢/w:ins 剥壳上提/段落标记与 *Change 清除/表格行删除丢弃整行；
  整段删除修订压平后整段消失——格内唯一段删净时留空段保命，OOXML 硬要求
  w:tc 至少一个块级子元素，病态素材会让整本被 Word 判损坏，review 后补；
  批注锚非修订保留）——**整本=交付态**，警示行
  改「解决全部待办批注」（DocxView）；②`_demote_extra_headings` 拷入面里命中
  标题样式的段落显式 outlineLvl=9（发标题的树对账已定、拷入面全是树外内容；
  只改大纲层级视觉零变化，导航窗格只剩章节骨架）；③目录页机械对账（探测+
  提示不门禁）：`_toc_normalize`（剥编号前缀/点线页码/NFKC）+ `_toc_match`
  （相等或双向前缀≥4 字）双向 diff 点名「列了整本没有的/整本有未列的」，
  「目录」「封面」两侧豁免、条目行限 ≤60 字（说明行不进对账）。skill 接线
  三处：SKILL.md 第 4 步合册行为描述更新+注意事项「目录页条目=实收章节
  清单」、section-writing.md 通用纪律「节内小标题逐级递进不倒挂」。已知
  边界（有意接受）：锚在被删修订段上的批注随段消失（=Word 手动接受修订
  同语义，节文件层批注仍全量保留）；历史整本重合册即得。真实任务重合册
  验证：0 修订标记/导航骨架 49 个（=程序编号标题全集）/树外摘出 131 个/
  对账警告精准点名 6 节。测试 test_docx_ops：修订保留测试翻转为交付态断言
  +树外摘大纲+目录对账三例，sidecar 692 绿+check.sh 全绿。

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

  占位行 1:1）。**图片可见性批（2026-09-08）**：动因=云枢素材 87 图、正文 run 25 条
  注入调用 0 次=整本 0 图——docx 纯图片段占位行 `![](图片)`（一段一行）是图的唯一
  md 可见形态，块级含图数=区间内占位行计数（`block_image_count`，段内嵌图/一段多图
  不可见、旧解析无占位恒 0 须重解析）；search_references 命中行/块骨架 N>0 标
  「含图 N 处」+硬话「必须注入——自写无法带图」（docx 直出管线无放图通道，图片只
  随 docx_material_inject 元素拷贝进正文；SKILL/section-writing/写手 prompt 同步
  「禁止跳过注入直接自写」+修订不删〔图×N〕段）。流程=上传（**2026-09-08 收口为仅

- **frontend**：`KnowledgeView.tsx`+`components/kb/`（**2026-09-08 知识库 UI 重做**，
  素材库同日重做后的姊妹批：方向从 4 张 AI 概念图拍板（`docs/prototypes/kb-redesign/`，
  用户拍「档案卡常驻内容页顶部」+「原件预览默认解析文本」）。①1067 行单体拆为
  `components/kb/`：kbDiff.ts（computeKbDiff/diffSummary/defaultChoices/buildAdoptBody
  纯逻辑）/kbShared.tsx（StatusDot/statusText/KbBadge/KbHeroEmpty/WarnLine）/
  DetailHeader.tsx/ArchiveCard.tsx/OriginalView.tsx/ContentPane.tsx/InfoForm.tsx/
  UpdateAdoption.tsx/ItemDetail.tsx，KnowledgeView 只剩容器（左栏+空态+脏守卫+确认弹窗）。
  ②**详情头部卡化**：文件名+徽章行（类型 brand/已确认·程序核对 success/待确认 warning/
  过期临期 chips）+元信息行（识别档位·页数·字数，识别中=进度 spinner；conversion 警示档
  变琥珀色）——旧 FreshnessBar/ParseMetaBar 横幅堆叠整体退役，解析 warnings 保留为正文
  上方警示行；动作排=重新识别/**下载**（fetchKbItemBlob 副本走 downloadBlob a[download]，
  revoke 延迟 10s 沿用 WKWebView 惯例；识别中禁用）/删除（两步）。③**资料档案卡（ArchiveCard）**：内容 tab 顶部常驻（brand tint 卡），
  AI 说明+锚点字段网格（**逐字段带 check_result 核对结果** ✓原文命中/⚠原因 tooltip）+
  检索问题 pills+「去核对/编辑」跳信息 tab；数据=business??suggested 与检索同序；
  人工确认过不显示核对标记（人已拍板）。④**原件预览（OriginalView+ContentPane）**：
  内容区「解析文本/原件」分段切换（kb-seg，默认解析文本），pdf→PdfPreviewBody、
  docx→DocxPreviewBody（React.lazy 复用产物面板渲染体+现成容器样式，文件不出本机）、
  .doc→提示另存；字节走新 `client.fetchKbItemBlob`（与 fetchKbItemRaw 共用底层），
  useQuery `['kb','raw',id]` staleTime Infinity+retrigger 连带失效；**解析失败也能看原件**
  （正是回原文核对场景）。图片条目无切换维持内联。⑤**信息表单重做**：类型下拉按
  fact/writing optgroup 分组、检索问题行式编辑器带 n/10 计数、锚点字段逐项核对状态
  （✓label 旁/⚠detail 灰字行）、AutoCheckBar 保留；**脏状态守卫**=onDirtyChange 上报
  宿主，切 tab/切条目弹 ModalShell 确认（放弃修改/继续编辑，不加锁）；保存成功经
  数据回流自动清脏。⑥**搜索防抖 300ms**+范围扩到内容说明与检索问题（items 已带
  suggested/business，纯客户端）；列表行副行改「类型 · 相对时间」。⑦右区大空态
  KbHeroEmpty（插图徽标+「上传资料」主按钮+「去写作素材库」分流，App 传 onGoLibrary）
  ——9-03 审计 P1 收口。⑧CSS：新 kb-badge/kb-archive/kb-fields-grid/kb-seg/kb-hero/
  kb-pane/kb-info-field 段；**顺手修 StatusDot 失败红点 bug**（代码用 `.kb-dot--error`、
  CSS 只有从未被引用的 `.kb-dot--Color-danger`，解析失败点从未着色）；死 CSS 清理
  （grep 证实零引用后删）：kb-nav、kb-bucket-tabs 族、kb-info-summary、kb-progress-bar、
  kb-decompose-cta、kb-ref-warn、kb-locate-bar、kb-q-adopt、kb-materials/kb-mat-* 全族、
  旧 kb-statement 卡（kb-statement-input 保留）与 kb-meta-bar/kb-meta-badge/kb-freshness
  （被头部徽章取代）。契约零改动（capability/role 仍未前台化）。门禁 tsc+oxlint（新
  文件 0 告警）+vitest 165 绿。⑨**左栏上传入口与素材库统一**（同日用户提议「做成和
  写作素材库里面一样」）：头部 + 图标按钮删除，改列表底部 `.kb-side-foot` 通栏
  墨色主按钮「上传文件」+ 格式提示（KB 比素材库多收图片），`.kb-add` CSS 与顶栏
  cursor:default 规则中的 kb-add 分支一并清掉（规则仅剩 .panel-btn）。
  沿革：左栏平铺+类型下拉+待确认胶囊筛选=五轮收敛 2026-09-04（分组头已删，维持）。
  `MaterialsLibraryView.tsx`（侧栏「写作素材库」
  **一等入口**；**2026-09-08 三栏工作台重做**（方向 3，用户从三张 AI 概念图拍板）：文件｜
  素材块｜详情主从布局——左栏「全部素材」+文件行（状态点、hover 显挑章节/重试/删除两步
  确认；ready+error=重解析行号漂移琥珀点常驻「勾选区间需复核」——原先该警示只活在
  toast），中栏块列表随左栏范围（scope=all 行内显来源文件名/文件态显区间）+排序
  （章节顺序/字数/引用）+服务端 FTS 搜索+搜索行右侧**「新建素材」按钮**（进入该文件
  挑章节；scope=all/未解析/挑章节模式中置灰带提示——2026-09-08 用户令自详情区挪入
  改名），右栏两态=块详情（大标题+元信息+复制正文/
  删除两步/备注标题就地编辑/行号槽正文预览）或挑章节（左树沿用 v2+**点节点右侧实时
  预览治「凭标题盲勾」**、底部已选区间条+建块弹窗沿用 dup 提示；outline 未到不发
  预览请求）。CSS=新 `mtw-*` 段（选中态中性 bg-subtle）；被取代的 kb-lib-* 旧段与
  mt-view-tabs/mt-file-row/mt-picker 壳/mt-block-preview 已删（KbImage 段保留——
  知识库在用）。建块成功跳到新块详情）。

  **主 prompt 资料词汇表+无机制纪律（2026-09-09）**：动因=「为整本应用模板」请求下
  agent 把素材库文件列成「模板库」候选问用户——模板库对 agent 零可见（无工具、主
  prompt 零提及、目录不在可 ls 清单），且「应用模板到整本」机制 09-08 已删，agent
  只能按日常语义把历史标书当模板+发明路。修复=agent.py 主 prompt 两处（非
  `_kb_summary_line`——词汇表须无条件常驻）：①资料词汇表——知识库=公司事实/
  素材库=用户手工挑选的内容块/模板库=纯版式资产只决定新建节与重新合册样式（已核实
  合册 `_new_document` 每次走活动模板，「设为默认后重新生成整本」是真可行路径才写进
  prompt）；不存在「把模板应用到整本/已写章节」的工具，被要求时如实说明+给可行做法，
  禁把素材库文件当模板候选；招标文件格式件（投标函等）不属于两库。②反虚构段加
  「用户请求你没有的能力时如实说明做不到+指出最接近可行做法，不要发明替代路径
  凑合执行」。守卫=test_agent.py `test_system_prompt_glossary_and_no_invented_paths`
  （源码关键词断言，防重构丢）。模板库可见性工具（list_templates）当日已补
  （见模板库段 2026-09-09 记录）。

   **整本预览空白修复（同日实测反馈）**：症状=打开「商务部分」产物卡统计行/横幅
   正常、预览区永久空白无报错；磁盘 docx 完整（size/sha256 与 content.json 一致）、
   端点正常，取字节失败或渲染 reject 都有红字/黄条兜底——是渲染成功后被清空。
   根因=DocxPreviewBody 内存修复批的「cancelled resolve 后 `el.replaceChildren()`
   补清」：同容器两次 renderAsync 并发时（StrictMode 双跑必现、blob 重取换数据
   同样触发，**发布版非 dev 独有**）被取消的旧渲染后完成会把活渲染的 DOM 整体
   清掉；6MB 整本解析秒级、完成顺序极易翻转所以整本高概率中招，小节文件窗口极小。
   修复三件：①DocxPreviewBody 每次渲染写独立子容器 host——活渲染 resolve 后
   `el.replaceChildren(host)` 换装上屏、取消/失败只 `host.remove()` 清自己，旧渲染
   结构性碰不到活渲染；换数据重解析期间旧内容保持可见；解析 >400ms 显示
   「正在渲染版式…」（防小文件闪烁的延迟出现），对外 props/样式契约不变、五个
   使用方同时受益；②VolumeProcessor blob query key `['artifacts',…]` 前缀改
   `['artifact-file', aid, content_seq]`——任何 `['artifacts']` 前缀 invalidate
   不得连带重取几十 MB blob 并重开竞态；③顺手堵后端两暴露面：tools/publish.py
   拒绝 LLM 经 JSON 草稿路径发布文件型契约（content_type≠json 一律拒——会造出
   无 docx 本体的残包，列表可见、/file 410；整本由 docx_assemble_volume 机械
   发布）+ /file 端点优先取 content.json `filename` 同名 docx（历史污染包盲取
   字典序第一会发错册）。实测=playwright 实机开关循环 4/4 + 双册切换渲染稳定；
   test_artifacts/test_publish_tool +2；check.sh 全绿。sidecar 两侧改动须重启生效。

   **转录产物卡跨会话失显修复（2026-09-16，方向 A 用户拍板）**：症状=换会话
   重写整本并真发布（seq 6→7）后聊天里只有「本轮文件」chips、无正式产物卡
   （工具返回还引导「聊天产物卡可预览/下载」、模型文案误称「与上一版一致」）。
   根因=conversation_id 语义两侧错位——产物行的 conversation_id 是 provenance
   （首发会话出处，更新路径永不改，api/artifacts.py 明注「非作用域」），而
   ChatView 转录卡按它当作用域过滤：同任务新会话里重发的产物被永远挡在转录
   外（首发会话「用户请求分析内容」vs 重写会话「重写投标文件技术部分」实证；
   面板侧 deliverable.created/产物面板正常，缺的只是转录卡）。被否方案=后端
   发布时刷新 conversation_id（把作用域堆回产物+首发会话历史卡被抢走+GET
   ?conversation_id= 语义漂移）、按任务全显（各会话转录互相污染）。修复=纯
   前端口径：`filterConversationArtifacts`（lib/artifactPlacement.ts）命中其一
   即进转录——首发会话匹配，或 source.run_id（=last_run_id，真发布即更新）∈
   本会话消息 run_id 集合；卡由 placeArtifacts 按 run 挂回发布回合（落位逻辑
   本就按 run，零改动）。已知边界（拍板接受）：产物再在第三方会话重发后，
   中间会话的卡会退出（无发布历史可依，与尾部兜底同款旧数据处理）；活卡期间
   隐藏/终态回归规则不变。配套（治模型文案混写）：publish_file_artifact 三
   路径返回 `_seq`（与索引 content_seq 同源），docx_assemble_volume 发布文案
   带「（第 N 版）」——把「发了第 N 版」与「仍是第 N 版未重发」钉成一眼可辨
   的两种结局。测试：artifactPlacement.test.ts 四例 + publish/docx_ops 版本号
   断言；881+308 绿；前端 HMR 生效、sidecar 文案须重启。**遗留排查（未做）**：
   同进程同输入两次合册判不等（09:03 seq=6 与 09:17 seq=7 之间章节零改动、
   sidecar 未重启，`_zip_content_equal` 未短路=内容级确有差异；而测试内同进程
   重复合册短路正常）——合册输出疑似含随次变化部件，短路在生产可能从未生效；
   定位须测试环境对同任务连续合册两次 diff 包内部件，修复方向=生成侧确定性
   化而非比对侧忽略。

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

  **工作台显示名单源 wbNames（2026-09-10）**：`lib/wbNames.ts` 的 `wbDisplayName`
  是产物面板行/「本轮文件」chips/编辑器头部三处显示名的唯一真值——固定过程文件
  走业务名（结构事实/资格要求/写作指引…）、`parse/<源>/…` 显示「<源名> 解析稿」
  （治双扩展剥目录后酷似上传原件、被误读成「招标文件是本轮新建的」）、
  outline/fragments 显示「分册 · <册名>」、其余 basename；path 恒为寻址真值
  不动，图标按真实路径取扩展名。RunFiles/DocxView/WorkbenchViewer/ArtifactPanel
  四处换用，wbNames.test.ts 四例。同批：面板覆盖态宽度 1120 封顶删除
  （2026-09-09 用户明令「产物栏不设最大宽度」，上限仅剩窗口宽−360）。

  **写作指引/承诺清单结构化表格界面（2026-09-08）**：产物面板按**文件名分发**
  （basename=`写作指引.md`/`关键事实与承诺.md`，容忍模型 guide_path 前缀变体）
  到 `components/workbench/` 的专用视图（GuideFileView 两栏视图 / PromiseFileView
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

  **指引查看/编辑增强（2026-09-09，文生图设计稿 A+D 组合用户选定，`docs/prototypes/guide-ui/`）**：
  ①查看态**过滤胶囊**（全部/缺素材/块失效/不在目录/待写/已写；单选、0 行禁用；判定单源
  `workbenchTable.guideRowFlags`——与行内警示、头部「缺素材 N 节」同口径，徽章改可点=
  一键过滤）+ **一级章节分组折叠**（`leafTopGroups`：叶子→最顶层祖先、多册分键带册名前缀、
  组序=行序首现、单组不分；折叠只藏行；仅查看态——编辑态恒全量平铺，行索引直通 setCell）。
  ②编辑态素材/依据列加 **CellPicker 选择浮层**（`components/workbench/CellPicker.tsx`：
  fixed 贴触发器+视口回退+Escape 捕获段/外点/滚动关闭——内部列表滚动不算外滚；素材浮层=
  块卡片按标题/来源可搜、点选插入归一化 id 再点移除、50 条截断提示；依据浮层=登记表条目
  四色编号+原文摘录、`sortRefIds` 排序；无目录产物时依据按钮禁用仍可手输）——治「编辑态要抄
  blk_id/翻目录找编号」的能力倒挂。③MatPreview chips 编辑态可点开块内容（改素材时正需要看）；
  缺素材→建块出口=浮层空态「去素材库检索建块」（onOpenLibrary prop 链 App
  `setActiveView('library')`→ArtifactPanel→GuideFileView）。测试 workbenchTable.test.ts +5 例，
  前端 lint/tsc/vitest/build 全绿。

  **实机点测两修复（2026-09-09，Playwright 真实 GUI 测试抓到）**：①浮层秒开秒关——CellPicker
  的 window click 关闭监听与「打开它的那一下点击」竞态，修法=外点关闭先判
  `anchor.contains(e.target)`（触发器/输入框内的点击交触发器自身 toggle，点别的行触发器照常关
  =单浮层）；②toggle 移除逻辑反了——reduce 遍历「其余 id」逐个 replace，把要保留的全删光只剩
  被点的块，修为 `value.replace(被点id, ' ')` 单点移除（素材/依据两处同修）。修复后实测：插入
  →移除往返字节级还原、搜索过滤、Escape 关闭、空态「去素材库检索建块」导航链全通过；真实任务
  文件往返零残留（服务端 GET 校验）。教训：fixed 浮层的 window 级外点关闭必须豁免触发器区域；
  「从列表 toggle」的增删两路都要真点一遍。

  **依据定性增强 F+H（2026-09-09 二批，设计稿 `docs/prototypes/guide-ui/E~H` 用户选定 F+H；
  动因=「为什么要写这一章、有什么依据」太弱——依据列只有编号黑话，定性/原文两层缺失）**：
  三层信息=定性（多重要）→原文（招标文件怎么说）→追溯（已有 chips 弹窗）。零契约改动（指引
  md/sidecar 不动），数据全来自现有产物：**registry 不存分值**（assemble_tender
  `_build_score_registry` 只取评分项/出处两列丢弃分值），但 **SCORE 编号=evaluation.md 评分表
  行序**（两位补零，同构机械对位，BPM 任务 13/13 实测）——前端 `lib/guideBasis.ts` 纯函数：
  `parseEvaluationScores`（表头按名识别「评分项｜分值」、段截断、无表空 Map 降级）+
  `scoreValueBadge/Max`（分值归一化：`10`→10分、`每项1，本项不超过5`→≤5分、`30（公式…）`→30分、
  无数字 null）+ `guideRowBasis`（前缀分类计数+定性规则：单条≥10 或合计≥15=得分主力/有 SCORE=
  得分点/有 MAND=强制条款/仅 TPL=格式件/其余=要求响应；计数按前缀、分值按命中——SCORE 对不上
  评分表仍算评分关联只是无角标，测试抓过此 bug）。前端：H=依据列 chips 下定性摘要行
  （stance 徽章+「2 条评分（最高 10 分）·3 条强制要求」）+ RefChip 分值角标（编辑态 RefCellEditor
  列表项同显分值——选依据时看得到分量）；F=点节名展开行内详情面板（colSpan tr、`GuideRowPanel`：
  定性头+逐条「编号 chip+分值原文+评分要点+登记原文+出处+跳原文」；悬空/无依据/无目录产物三级
  机械兜底；仅查看态——编辑态收起，切换过滤收起）。`SourceEntryCard` 从 SourceTraceDialog 抽出
  共用（卡片不知编号概念，跳原文回调由宿主闭包携带，Dialog 零行为变化）。evaluation 查询=
  `['workbench', taskId, 'content', 'analysis/evaluation.md']` 与既有 workbench 缓存同前缀共享
  失效，retry:false（没跑分析的任务 404 是常态）。测试 guideBasis.test.ts 十例（金样例取 BPM
  真实评分表三形态分值）；实机点测全过（53 行定性全覆盖、展开收起、跳原文定位 L447、无评分行
  降级无角标）。设计图 E（卡片直出）/G（分值重排）否决记录：E 密度失控、G 破坏目录树序且
  187/200 条无分值语言。

  **层级区分两批修复（2026-09-09 三批，用户反馈「目录层级区分不清晰」）**：根因=树深最多 4 层
  （册→一级章→二级章→叶子）而分组只做了一级——大章 35 行平铺、内部二级章节（应用功能设计 8
  节/实施管理 7 节/团队 3 节/服务承诺 2 节）完全不可见；节列每行带「册名/」前缀与分组头重复加噪。
  修法：①`leafGroups`（workbenchTable，取代 leafTopGroups）：叶子键→{top, second}——second=顶层
  之下那层容器、不随深度下沉（三层嵌套仍归第二层）、顶层直挂叶子 second=null；容器不进 Map。
  ②查看态两级分组渲染：一级头升级（bg-muted/50+品牌色左条+font-semibold+13px）、二级头新增
  （缩进 pl-7+bg-muted/20+更轻），折叠键共用 foldedGroups 一池（一级=key、二级=`top/sub` 复合键），
  一级折叠藏整组、二级折叠只藏子组；组内 direct 行（second=null）在前、subs 在后（行序=首现序）。
  ③节列查看态瘦身：多册键剥册名前缀（分组头已表达册），悬停 title 保留全名；编辑态/无分组显示
  原文——数据层（rows/序列化/对账键）始终是完整键零变化。单组且无子组不分（原规则）；实机
  验证 17 一级头+4 二级头、二级折叠 74→66 行。

  **出处上下文就地展示（2026-09-09 四批，用户反馈「查看原上下文点击后不会跳转到上下文，
  不如直接提取展示」）**：来源追溯的「查看原文上下文」跳转链（打开解析 md 只读定位视图）整体
  删除——跳转离开当前界面且定位感知弱；替代=`ParseContextBlock`（SourceTraceDialog.tsx 导出）：
  按出处首个 `L(\d+)` 行号取解析主文件 md 的 line-8~line+12 切片就地内嵌在条目卡片里，目标行
  accent-soft 高亮+行号加粗，头部标「原文上下文 L1047-L1067 · <文件名>」；解析主文件=workbench
  列表 parse/ 下首个 .md（单主文件口径与旧跳转一致），content 走共享 queryKey 缓存。降级：出处
  无行号→「出处未带行号」提示；无任务/无 parse 文件→不渲染；taskId 未传（undefined）→卡片不渲染
  上下文块（null 传值仍渲染=可显示降级文案）。接线三链：SourceEntryCard 加 taskId prop（上下文块
  内嵌）、SourceTraceDialog 加 taskId、DirectoryProcessor 传 artifact.task_id；GuideFileView 的
  openSourceContext 与 DirectoryProcessor 的 openSourceContext+onOpenWorkbench 消费全删
  （ProcessorProps 共享接口保留可选不动）；workbenchAnchor 行号定位链保留但「查看原文上下文」
  已无消费方。实机三链全验证：指引 chip 弹窗（REQ-25→L1055 高亮）、行展开面板（4 条依据各带
  切片）、目录树徽章弹窗（SCORE-13→L461 价格分 30 行高亮）；跳转按钮全消失。

  **行内内容行+查看态五列（2026-09-13，动因=用户「指引还是无法直观看到自己想要做的内容」；
  原型 `docs/prototypes/guide-ui/I~M` 五张，素净标签形态实施）**：内容直出、不再只给编号黑话——
  ①`iterLeaves` 带出目录叶子**节点概述/归位理由**（`DirLeaf.overview/reason`，同一 walk，实测
  真实任务 39/39 节点有值）；②③素材底稿数据=`useQueries` 批量拉本表全部 blk id 的块内容
  （queryKey 与 `useMtBlockContent` 同键共享缓存、staleTime 60s、单块失败静默降级，零后端
  改动零契约改动）。**同批配套布局修复=查看态去掉「缺口/备注」列改 5 列并删表头 `min-w-[900px]`**
  （此前窄面板该列被挤出可视区——而它恰是写作指令最密的列）。

  **写作指引两栏重构（2026-09-13 同日二批，取代上段的五列表格；用户选 N/O 图=左树右详情）**：
  `components/workbench/GuideFileView.tsx` 从单张表格改为**左树右详情两栏**——左栏
  `GuideTree.tsx`（目录真实层级的章节树，含「未分配」=目录有节点但指引没给行、「不在目录」=
  指引有行但目录里找不到；搜索框 + 筛选胶囊），右栏 `GuideDetail.tsx`（选中节点的作业单：查看态
  直出「本节写什么·节点概述」「素材底稿·块首预览」`blockPreviewText` 120 字、备注；编辑态内联
  编辑模式/依据/素材）。树派生抽为纯函数 `lib/guideTree.ts`（`guideTree`=目录层级+指引行→导航树，
  选择键=叶子 leafKey；无目录产物回落平坦行、`leaf:null`；`pruneTree`/`countUnassigned`/
  `leafKeysOf`/`offTreeRowsOf`），共用件 `guideBits.tsx`。上段的「内容行」实质全部保留、只是
  从表格行内挪进右栏详情。**文件格式零改动**（仍 `| 节 | 模式 | 依据 | 素材 | 缺口/备注 |`
  md 表、序列化唯一）；`guideTree.test.ts` 锁层级/对位/未分配/无目录回落/「不在目录」判定。

- **「任务即房间」导航重构（2026-09-13，用户拍板）**：会话只从任务内诞生，主区按
  「有会话选中 / 没有」二态分派。①**删草稿态**——`components/TaskPicker.tsx` 删除、
  ChatView 的 `initialSend` 草稿链路全删，无会话时不再渲染输入框；②**任务首页
  `components/HomeView.tsx`**（冷启动落此页，不再自动进最新会话）：卡片列已有任务 +
  「继续上次」一行，建任务入口就在本页——「开始新投标」卡点击翻卡内命名创建、往本页
  任意位置**拖招标文件 = 以文件名直接建任务**（`onCreateTask(title, files)` 交 App
  `handleCreateTask`：建任务自带首个会话 → `setPendingFiles(files)` 转交 ChatView 上传）；
  弹窗形态（原 NewTaskDialog）已弃。③侧栏「新建任务」= 导航到首页（`setSelectedId(null)`），
  不再弹窗；ChatHeader「＋ 新会话」只在有任务时出现。④`lib/clipboardFiles.ts`（InputComposer
  粘贴上传路径专用）：浏览器粘贴图片的通用自动名（image.png 等）在前端改名保共存
  （任务文件 API 是任务内同名覆盖语义，不改名连贴互相覆盖；Finder 复制粘贴的真实文件名
  保持原名）。

- **拖放进输入框残留覆盖层修复（2026-09-13）**：症状=把文件拖到输入框上松手后，整区
  覆盖层「松开上传到工作区」永久卡住（文件其实已上传、chip 已出现，覆盖层盖住输入区）。
  根因=同批新增的输入框局部拖放反馈（`InputComposer` 的 `dragOver` 态）在 dragover/drop
  都 `stopPropagation`，外层 `UploadDropzone` 既收不到 drop（冒泡段 `onDrop` 不触发）也
  收不到 dragleave（从聊天区一路拖到输入框时指针始终在区内）→ `over` 无人置回 false。
  修法两件：①`UploadDropzone` 加**捕获段** `onDropCapture={() => setOver(false)}`（捕获
  先于冒泡，输入框的 stopPropagation 拦不住）收尾；②dragover 去掉 stopPropagation，改由
  外层按拖拽目标逐帧裁决——`InputComposer` 的 `.box` 标 `data-drag-target`，外层
  `onDragOver` 命中 `[data-drag-target]` 时让位（两层同时亮=双反馈打架）。drop 的
  stopPropagation 保留（防双上传）。实机 Playwright 五场景验证（区内转输入框/直达输入框/
  区内松手/移出/再入）全绿；前端 tsc+oxlint+vitest 264+build 全绿。

- **前端内存修复批（2026-09-13，行业实践对齐，零契约改动）**：3GB 级内存占用的六处收口。
  ①`components/ai/traceLive.ts`——`TraceLiveContext` 标记活卡（RunMessage 运行中/HITL
  冻结卡）内部：子代理思考等长文本在活卡内**恒走尾部封顶**（`TRACE_LIVE_TEXT_CAP` 12000
  字符 + 折叠提示），run 结束后的历史过程区（点开才拉、按需挂载）默认渲染全文——此前
  活卡子代理卡随波次累积、终态整段思考 markdown 常驻是爬升主因。②`PdfPreviewBody`
  画布回收（迟滞带 400px 渲染/2000px 回收）+ dpr 封顶 1.5。③workbench 与 materials
  内容端点加**行/预览预算参数**：`GET /workbench/content` 行切片、`GET /materials
  blocks/{id}/content?preview=N`（sections 按累计预算截断、`chars` 仍为真实总字数）。
  ④多处 react-query gcTime 收窄（ChatMessage/DocxView/OriginalView 等）。


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

- **提问卡原位替换输入框（2026-09-09，用户拍板方向 A，文生图 mockup 定稿）**：
  waiting_input 期间 InterruptCard 从消息流内联（原 `.turn-attach` 挂点，已删）挪到
  **底部输入框槽位原位替换 InputComposer**（ChatView 条件渲染 `interrupt && !running`；
  `.composer` 内 `.interrupt-host` max-width 720 与 `.box` 同宽、`.interrupt-scroll`
  max-height min(60vh,560px) 内滚防长问题撑爆聊天区）——设计语义=过程留在消息流
  （活卡冻结态「等待你的输入」胶囊+「已暂停 · N 步」不变）、回答入口搬到输入区
  （用户视线本来在打字的地方），提交/放弃后输入框原位回归。wizard 草稿 state 仍由
  ChatView 持有（换挂载点不丢状态，SSE 重连恢复机制零改动）。**等待期上传能力保住**
  （确认门补传窗口是文档化设计）：上传钮+待发送 chips 移到卡下 `.interrupt-upload-row`
  细行，chips 抽出 `components/UploadChips.tsx` 共用件（InputComposer 同换）；提交时
  「我上传了文件：…」拼接（wizardNav）不动。InputComposer 的
  `waiting`/`waitingHint`/`disabled` props 随之删除（替换期间 composer 不渲染，纯死
  代码）；纯审批卡与问答卡一起挪（同一渲染条件，行为一致）。

   **PyMuPDF 整体替换为 pypdfium2（2026-09-14，许可治理批，sidecar 内部件+测试+打包）**：
   动因=商用许可自由（PyMuPDF 为 AGPL；本仓自身 AGPL 开源下今天无违规，替换=给未来
   闭源商用分发留路）；铁则=**全程不读 MuPDF/PyMuPDF 源码**（含 sdist），算法参考仅
   MIT 实现（pdfminer.six 分组思路/pdfplumber 边线表格），未动用「效果不佳可参考
   mupdf 源码」的授权。三批落地：①渲染/图片侧先行（`app/parse/pdfium_kit.py` 全部
   pdfium 交互收口+**全局 RLock**——PDFium 官方明确禁多线程、跨文档也不许并发
   〔pypdfium2 文档与 Issue #303 实证；4.30 为 SWIG 绑定非 ctypes〕；知识库 images.py
   切 Pillow 解码/尺寸；docx 插图页数；PyInstaller spec 加 `collect_dynamic_libs
   ("pypdfium2")`——原生库漏收是社区实测坑，冻结冒烟项 `pypdfium2(native)` 兜底，
   实打包验证过）②结构层自研（`pdf_text.py` 文本块=get_text("dict") 平替：行层走
   pdfium C 级分段 count_rects/get_rect+get_text_bounded，**纵向聚行传递闭包+行内
   x 序拼接/大间隙切段**（中文两端对齐逐字定位会打乱 (y,x) 序，合并算法必须顺序
   无关）；`pdf_tables.py` 有框表格=find_tables 平替：路径 bbox→退化维判横竖边
   （**容差 3.5pt**——Word 双线边框两线相距 3.4 会出幽灵列）→共线合并→闭合格
   →连通簇+重叠/垂直相邻簇合并（同一张表隔空行带/交错列分裂形态）→「穿行带竖边
   定列界」extract（跨列合并格自然闭合、缺格补 ""、簇内双向筛线防捞同 x 范围
   邻表）；`pdf.py` 四级识别链改引擎无关模板（纯逻辑单份），引擎原语在
   `pdf_pdfium.py`；旧 mupdf 实现曾逐字节一致性校验后随批 3 拆除）③差分门禁后
   切换+拆除（临时 TENDER_PDF_ENGINE 开关经真实语料五级差分〔L0 档位/L1 结构/
   L2 归一 diff/L3 渲染墨水覆盖/L4 耗时〕全过后翻默认，随后删 pdf_mupdf.py/
   依赖/开关，冒烟项 pymupdf→pypdfium2(native)，`test_pdfium_kit` 加许可守卫
   〔app/ 零 import pymupdf|fitz，防 AGPL 回流〕）。差分实测的关键坑与裁决：
   pdfium 字符盒=**字形墨迹盒**（「一」仅 1.7pt 高，bounded 取文会漏字→垂直外扩
   3pt 兜）；跨行粘连跑伪影（文本含 \r\n 取末段+退化高度矩形丢弃+x 重叠段去重
   ——「颁颁」「Firefofox」双实证）；渲染对比改**区域墨水覆盖**口径（抗锯齿/
   hinting 逐像素差 15% 但结构等价、字体本就嵌入）；mupdf 在中西文边界合成空格
   而pdfium 不加（L1/L2 比对去空白归一）；真实语料 2 份（ISO 证书全过且 pdfium
   快 20 倍；143 页公司介绍 L1/L3/L4 全过、L0 表格 39→27=**无框表格策略差异裁决
   例外**——mupdf stream 策略从文本对齐推断的「表」多为证书排版框/单行文本条，
   内容以文本完整保留〔字符比 0.991、outline 全同〕，无框表格明确范围外）。
   测试夹具同步去 pymupdf：`tests/pdfgen.py`（reportlab 左上原点薄封装+七个档位
   夹具复刻+hand_pdf 手工 PDF〔/Rotate 等页面字典形态〕+solid_png；**reportlab 只在
   showPage 落页、save 丢弃未关闭尾页**——空白页夹具须双 show_page；夹具先对旧
   引擎自证再用于新引擎）。并行 parse 语义变化：C 层真并行→全局锁串行（典型
   3-5 源文件墙钟有界回退，L4 实测大文件反而更快）；render_page_png/插图页数
   并发经 kit 锁天然安全。依赖净变化：-pymupdf（25MB 轮子）、+pypdfium2>=4.30,<5
   +Pillow（运行时）、+reportlab（dev，BSD-3）；运行时依赖树无 AGPL。批 2b 起须
   **重启 sidecar** 生效；差分机为 /tmp 临时件未进仓。

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
    （app/main.py 是相对导入不能直当入口脚本；`--smoke` 冻结自检**十项**：pymupdf/jieba/
    FTS5/trafilatura/**python-docx 默认模板/基准版式模板（app/resources——唯一「漏收集
    不崩溃、只静默退化英文默认版式」的 datas 项，断言专为盯它，2026-09-09 产物过期事故
    的病灶类型）**/openai 懒资源/agent 栈/server 栈/app.main）+ `tender-agent-sidecar.spec`
    （datas 收 `app/skills/**` 与 `app/resources/**`；collect_data trafilatura+**justext**（stoplists 是冻结冒烟
    抓的漏）；collect_submodules 保底 deepagents/langchain 全家/openai——3.x 懒资源代理是
    纯字符串 import_module；**upx=False 硬性**，UPX 压缩产物过不了 codesign）+
    `build_sidecar.sh`（**独立 .build-venv**=uv 管的 python-build-standalone 3.12 按
    uv.lock 装，绝不用日常 .venv——它是 miniforge 软链，conda dylib 指前缀、用户机必炸；
    锁版 pyinstaller==6.14.1；产物落 `src-tauri/binaries/`（gitignore））。
    **多平台化+冒烟门（2026-09-09）**：脚本加 `--target <triple>`（默认本机 rustc host
    triple）与 `--no-smoke`；跨 OS 目标直接拒绝（PyInstaller 不能交叉冻结，指路
    `docs/packaging.md`——各 OS 产物须在各自环境构建，mac/windows/linux 全平台指引+验收
    清单都在那）；同 OS 跨架构（mac arm 机打 x86_64 半边供 universal）经 uv 装对应架构
    托管 CPython（`cpython-3.12-macos-<arch>-none` 按全名/部分名请求均可），PyInstaller
    在 Rosetta 下运行，venv 落 `.build-venv-<arch>` 与本机隔离（gitignore 规则
    `.build-venv*/`）；**构建尾部自动跑产物 `--smoke` 冒烟门**（目标 OS=本机 OS 时；
    实测 ~12s）——此前冒烟靠手动、产物过期无守卫（09-07 产物打到 09-09 缺模板两天
    无人知），现在每次构建即验证；`--inexact` sync 保住 lock 外的 pyinstaller 免每次
    重装。**bash 3.2 兼容铁则**：macOS `/bin/bash` 恒为 3.2（GPLv3 冻结），`$(case ...)`
    内嵌 case 解析不了（模式的 `)` 被当替换结束符、执行期才爆）、`$VAR全角标点` 变量名
    会并入多字节字符（须 `${VAR}`）——脚本里见 `PBS_OS` 处注释。
    `npm run build:sidecar` / `build:release`（先 sidecar 后 tauri build，有意不塞
    beforeBuildCommand）。冒烟基线：89MB 二进制、冷启动至 healthy 11-14s（bundled 探活
    窗口放宽到 60s）。已知坑备案：Windows NSIS 覆盖安装不更新 externalBin（tauri#15134，
    靠版本号变化规避）；未签名 one-file 杀软误报偏高（正式 Developer ID 签名大幅缓解，
    Tauri bundler 会自动逐个签 externalBin 并公证）；~~macOS universal 需 lipo 合成
    sidecar 或发双包~~（2026-09-09 起：官方路径=两个 triple 产物放 binaries/ +
    `tauri build --target universal-apple-darwin`，x86_64 半边可在 arm 机经 Rosetta 构建，
    lipo 合成仅作老版 tauri 的退路）；Linux /tmp noexec 需 `--runtime-tmpdir`。
    签名/公证/CI/自动更新器=后续门未做。

  - ~~钥匙串用 macOS `security` CLI 子进程~~（2026-08-29 已移除：Key 改存 app.db，见铁则 2；
    历史：keyring crate 在此 macOS 写 Data Protection 钥匙串，`security` CLI 不可见）。

  - **客户端版本检查+更新提示一期（2026-09-15，Rust 壳+前端，零新依赖零
    capabilities）**：动因=用户要求「client 版本检查，更新功能」，两步走拍板——
    一期=检查+提示+跳转下载，应用内自动更新（tauri-plugin-updater）二期与签名公证
    绑定（macOS 未签名更新后重启会被 Gatekeeper 拦，已核实：updater 的 minisign
    清单签名与 Apple 代码签名是两回事，但 quarantine 门槛仍在）。**版本号同源修复**
    （前置 bug）：`__APP_VERSION__` 原读 frontend/package.json（恒 0.0.0）→ 改读
    `../src-tauri/tauri.conf.json`（CI 从 tag 同步的唯一真源），设置页此前显示
    0.0.0 即此 bug（check.sh 五处一致性守卫的注释同步改写）。**更新源三层取值**
    （`resolve_manifest_url`）：环境变量 `UPDATE_MANIFEST_URL`（本地测试）>
    `<数据目录>/updater.json` 的 manifestUrl（生产改址免重编译）> 内置常量
    `DEFAULT_UPDATE_MANIFEST_URL`（域名定稿后填入，见下条）；刻意不放设置界面
    （更新源=下载跳转信任根，谁都能改=恶意下载页入口）。清单契约=官网
    `version.json`（version/url 必填 + notesUrl/publishedAt/highlights/changes
    可选；字段可加不可删；漏更=不提示不误报 fail-safe）；**检查源与下载目标解耦**
    （url 现指 GitHub Releases，换官网下载页不动客户端）。Rust 两命令：
    `check_latest_version`（blocking reqwest 5s 超时+UA；清洗=剥 v/数字段校验、
    https-only、changes ≤20 条×200 字符截断，远端内容不合法整次判失败）与
    `open_download_page`（https-only 白名单后 opener 打开；Rust 侧调 opener 不经
    ACL 同 reveal 口径）。前端 `lib/updateCheck.ts`：启动 query 静默查一次（成功
    后 24h 节流、失败不写 lastAt 下次启动重试=每启动最多一次请求）、忽略态折进
    同一 query 缓存（红点/版本卡全局一致；按版本号精确匹配，忽略 0.1.2 后出
    0.2.0 红点回归）、`isNewerVersion` 逐段数值比较（防 0.10.0<0.9.0 字符串坑，
    不合法输入一律 false 宁漏报不误报）。UI=侧栏设置图标红点（bg-warning 8px，
    IconButtonAction 加 relative）+点设置直达「通用」页（SettingsModal 加
    initialSection prop+open 对齐 effect——组件常驻挂载、useState 初值只首次生效）
    +版本卡内嵌状态机（无新版一行含检查时间/检查中/有新版=徽章+highlights+
    changes 逐条 bullet >8 折叠+前往下载+忽略此版本+完整发布说明 ↗/已忽略收成
    一行可恢复/手动失败红字可重试——启动静默失败不上 UI）。App 的 openSettings
    （section?）统一两处设置入口传参。测试：updateCheck.test.ts 10 例（比较/节流/
    时间人话化）+ lib.rs 3 例（normalize/clamp/https 校验）。发版新增手动步骤=
    更新官网 version.json（文档化在 packaging.md §9）。已知边界：清单无签名
    （一期只读版本号+跳转可接受，二期自动更新必须上 minisign）；api.github.com
    不再依赖（自建源，国内直连可控）。

  - **更新源默认常量填入正式地址（2026-09-16，同分支续）**：
    `DEFAULT_UPDATE_MANIFEST_URL` 由空串改为 `https://ddmdj.com/release/version.json`
    （域名上线）。空串时检查报「更新源尚未配置」——正式地址落地后一期功能才真正生效，
    随下个版本发布。

  - **中文 productName 的 MSI 构建修复（2026-09-16，v0.2.0 发版首次触发）**：品牌
    改名批（灵燕智能）落地后**首次带非 ASCII productName 出包**——Windows job 失败，
    Rust 编译与 NSIS 均正常，只有 WiX 的 light 链接挂掉，报 `failed to run ...
    light.exe`（Tauri 默认不回显 light 的 stderr，真正错误要 `--verbose` 才看到
    **LGHT0311：字符串含代码页 1252 里不存在的字符**，定位在 main.wxs 的 Product/Name
    ——即中文产品名）。根因=WiX 默认语言 en-US ⇒ codepage 1252 编不了中文；上游同款
    tauri-apps/tauri#8363 的结论也是「WiX 在此上下文不支持中文字符」。**修法=
    `bundle.windows.wix.language: "zh-CN"`**（Tauri 查 languages.json 得 asciiCode=936
    注入 !(loc.TauriCodepage)，light 带 `-cultures:zh-cn;en-US`，非 en-US 自动补 en-US
    回退内建 UI 串）。**NSIS 侧刻意不动**：实测 tauri-bundler 的 nsis 全程
    write_utf8_with_bom 写脚本 + installer.nsi `Unicode true`，中文名本就安全。
    教训：macOS 本机造不出 WiX 复现**——平台特有的打包配置只能在 CI 上验证**，
    品牌改名这类「改名时无法验证、发版时才炸」的项，留给 CI 首验是唯一路径
    （代价=一次 Windows job 白跑 ~8 分钟）。修复已随 v0.2.0 tag 重打验证。

