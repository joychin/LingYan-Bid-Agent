# 重构手册 · 上：背景、概念与 Workflow

> **自包含重建指南。** 配合《重构手册 · 下：Skill 与 Prompt》+ `schemas/` 四个 JSON Schema，即可在新工程从零重建全部 workflow 与 skill，不需要本仓库其它文件。

## 0. 你只需要带走 6 个文件

| 文件 | 用途 |
|---|---|
| 重构手册-上（本文） | 背景、概念、6 个 workflow 的完整声明 |
| 重构手册-下 | 12 个 LLM Skill 全定义（prompt 完整内联）+ 确定性能力 + Policy 操作 |
| `schemas/artifact-envelope.schema.json` | Artifact 通用契约（含 Ref/EvidenceItemRef/状态定义），直接拷贝 |
| `schemas/evidence-source-artifacts.schema.json` | 来源/装袋/用户交互契约，直接拷贝 |
| `schemas/core-analysis-artifacts.schema.json` | 四类分析产物契约，直接拷贝 |
| `schemas/planning-publication-artifacts.schema.json` | 计划/基线/目录/发布契约，直接拷贝 |

---

## 1. 背景：旧系统的三个伤口（为什么这样设计）

**伤口一：证据不封闭。** 旧系统把关键词召回的片段发给模型，模型输出 `E-xxx` 引用后只做"ID 是否存在于全量 catalog"的检查——catalog 比实际发送的文本大（截断）、ID 存在≠内容支持结论（无 entailment）、局部召回却敢输出"未发现废标项"（coverage 撒谎）。
→ **解法：Evidence Bundle。** 每次调用前把可见证据封成带 hash 的不可变袋子，引用必须落在袋内（可机器验证），袋子自己声明查了多大范围（coverage profile），"未发现"只能在已完成的检查范围内说。

**伤口二：流程不可局部重跑。** 7 个分析组塞在一个 runner 里跑，用户补充一条"漏了联合体条款"只能整体 regenerate——资格、评分全部陪葬，旧结果被覆盖。
→ **解法：Skill 独立 + 粒度下沉到 Bundle。** 每个分析是一个独立 Skill（一次调用、一个袋子、一个产物、一条失败记录）；想缩小范围就换小袋子，不换人。

**伤口三：发布无门禁。** Outline 流水线跑完直接删除并覆盖正式章节表和来源 registry——没有候选、没有审批、没有回滚。
→ **解法：ChangeSet/Approval + legacy 只投影。** 一切正式状态变更经过"候选 → ChangeSet → 审批 → 原子应用"；旧数据库只接收已应用的投影，且无批准权。

---

## 2. 核心概念速览

| 概念 | 一句话定义 |
|---|---|
| **Artifact / Revision** | 有稳定 `artifact_id` 的领域产物及其不可变版本；Payload、输入快照、hash 一经写入不可改。 |
| **Head** | 指向当前推荐/批准 revision 的项目指针；`approved_head` 只能由已应用 ChangeSet 移动。 |
| **Skill** | 能力单元（= 行业的 tool/function）：一次调用，一个 Bundle 进、一个 Artifact 出、一条失败记录。 |
| **Bundle（证据袋）** | 一次 Skill 调用能看到的全部证据，封口、带 coverage 标签、有 hash、不可变。 |
| **EvidenceItemRef** | `{bundle_ref, evidence_id}`——`ev_` 编号只在袋内唯一，跨产物引用必须带袋子出处。 |
| **source_set** | 本轮分析纳入/忽略/排除/解析受阻的文件选择及优先级；≠ 原始文件登记。 |
| **Workflow** | 被运行时解释执行的 DAG 模板（节点+条件边+人审门禁+断点）；编排 Skill，不是 Skill。 |
| **ChangeSet** | 对正式选择的拟议变更：diff、影响、策略判断、审批、应用回执。 |
| **Legacy projection** | 把新 Artifact 投影到旧库/旧导出的适配结果；不是真相，不能批准，必须带投影 hash。 |

**状态三层（绝不混用）**：

| 层 | 取值 | 管什么 |
|---|---|---|
| lifecycle | provisional / approved / superseded / rejected | revision 的采用状态；approved 上游变了**仍是 approved** |
| freshness | fresh / needs_review / stale / historical | 相对当前上下文；Run 失败不改这里 |
| analysis | completed / partial / failed / blocked | 分析完成度；**空 items ≠ "没有发现"** |

**Coverage profile 阶梯**（袋子自己声明，语义层验证）：

```text
candidate_retrieval → targeted_scan → documented_completed_scope → full_scan_with_backcheck
（按问题现装）      （章节定位）      （声明完成范围）            （全文+标题/表格反查，仅废标袋强制）
```

**验证边界**（谁管什么）：

| JSON Schema 管 | Repository/语义/策略管 |
|---|---|
| 字段形状、枚举、局部条件、unknown 不带 confidence | Ref 存在性、hash 匹配、EvidenceItemRef 属于袋子 |
| user 补充无原文位置、user_only 袋无原文证据 | item_id 唯一、block/page 存在、range 顺序 |
| scoring union 各分支必填值 | coverage 是否真达标、评分算术、lineage 语义 |
| | ChangeSet/审批/CAS/不可变/原子应用 |

---

## 3. Workflow 与 Skill：区分和归属

**四问测试**（任一出现"多次/等待"就是 Workflow）：
① 能否用"一个袋子进、一个产物出"描述？② 是否一次模型/确定性调用？③ 失败是一条记录还是多步恢复？④ 中途需要等用户吗？

**分层**：Skill 是被调用者（厨师），Workflow 是调用计划（菜单）；菜单不是菜，但菜单要登记、有版本、能被点。

```text
intake workflow（classifier 节点做意图分类 → 条件边路由）
  → 各 Workflow（DAG：顺序、并行、门禁、等待）
      → Skill 调用（厨师 + 一个袋子 + 一盘菜）
          → Artifact（带 EvidenceItemRef，可审计）
```

**全部能力的归属总表**（这是你要的"哪些是 workflow、哪些是 skill"）：

| 能力 | 归属 | 形态 |
|---|---|---|
| 意图分类与路由 | **Workflow**（intake 的 classifier 节点） | LLM 分类 + 条件边，查表路由 |
| 全量招标准备 | **Workflow** `tender_preparation` | 装袋×7 → 7 个分析 Skill → 计划 → 双门禁 |
| 用户补充后局部重查 | **Workflow** `targeted_reanalysis` | 补充 → 定向袋 → 单 Skill → diff → 影响 |
| 任意问答（"有几个分标项"） | **Workflow** `answer_flow`（2 节点迷你流） | 现装 ad_hoc 袋 → answer_query |
| 目录生成 | **Workflow** `outline_generation` | ItemRef 集 → generate → 覆盖 gate → revise×2 → 复验 |
| 发布与导出 | **Workflow** `publication_export` | 提议 → 审批 → 应用 → 投影 → 报告 → 导出审批 |
| 结构识别 / 四类需求 / 废标 / 评分 / 澄清 | **LLM Skill** ×5 | 各挂一袋，见下册 |
| 问答作答 | **LLM Skill** `answer_query` | 挂 ad_hoc 袋 |
| 文件计划 / 目录生成 / 目录修订 / 发布提议 | **LLM Skill** ×4 | 吃 ItemRef 为主 |
| 意图分类本体 | classifier 节点（intake 内） | 不是独立 Skill |
| 用户补充/编辑/决定记录 | **确定性 Skill** `record_user_input` | 3 种变体 |
| 导入/解析/质量/地图/装袋/合并/diff/影响/覆盖验证/评分投影/快照/ItemRef 收集/编辑应用/就绪报告 | **确定性能力**（平台内置） | workflow 的 platform 节点 |
| 应用 ChangeSet / legacy 投影 / 导出 | **Policy 内置操作** | 副作用执行器，无分析语义 |

---

## 4. 系统全景（唯一主线）

```text
source_set（选文件）
  → parse / quality / document_map（确定性）
  → evidence bundles ×7 purpose（装袋机）
  → 分析 Skill：structure / requirements×4 / 废标 / 评分（并行，各一袋）
  → detect_clarifications（跨袋引用）+ 用户补充/编辑/决定
  → response_file_plan_candidate
  → [门禁: 采用计划] → Baseline ChangeSet → [门禁: 审批] → approved baseline
  → outline_candidate（只吃 ItemRef，节点自带 refs）
  → 确定性覆盖验证 → revise[scoring] / revise[structure]（只产 edit proposals）→ 复验
  → publication ChangeSet → [门禁: 审批] → 应用 → legacy 投影（回执）
  → 就绪报告 → [门禁: 审批] → export_snapshot
```

---

## 5. Workflow 完整声明（6 个）

声明为 JSON 图 DSL（数据不是代码：可静态校验、可渲染进 Chat/画布、可 diff、符合"不给 LLM 现场写代码"红线）。节点类型：`skill`（调 Skill，`variant` 传 purpose/mode）/ `classifier`（LLM 意图分类）/ `condition`（确定性分支）/ `platform`（内置能力）/ `human_input`（HITL 门禁）/ `sub_workflow`。数据流用 `$params.x` / `$nodeId.output.y`；每节点可声明错误策略；每步 checkpoint 可恢复；同 `after` 的节点并行。

### 5.1 `intake`（入口路由）

```json
{
  "workflow_id": "intake",
  "version": "1.0.0",
  "params": [{"name": "user_message", "required": true}, {"name": "project_context", "required": true}],
  "nodes": [
    {"id": "c1", "type": "classifier",
     "binds": {"text": "$params.user_message", "capabilities": "$params.project_context.capability_list"},
     "intents": ["query", "reanalyze_topic", "full_preparation", "generate_outline", "publish_export", "unknown"]}
  ],
  "edges": [
    {"from": "c1", "to": "answer_flow",          "when": "$c1.intent == 'query'"},
    {"from": "c1", "to": "targeted_reanalysis",  "when": "$c1.intent == 'reanalyze_topic'"},
    {"from": "c1", "to": "tender_preparation",   "when": "$c1.intent == 'full_preparation'"},
    {"from": "c1", "to": "outline_generation",   "when": "$c1.intent == 'generate_outline'"},
    {"from": "c1", "to": "publication_export",   "when": "$c1.intent == 'publish_export'", "gate": "approval"},
    {"from": "c1", "to": "ask_clarification",    "when": "$c1.intent == 'unknown'"}
  ],
  "fallback": {"action": "ask_clarification"}
}
```

LLM 只做"自由文本 → 意图 + 参数"；"意图 → 走哪条路"是纯查表。

### 5.2 `tender_preparation`（全量准备）

```json
{
  "workflow_id": "tender_preparation",
  "version": "1.0.0",
  "params": [{"name": "source_files", "required": true, "type": "array"}],
  "nodes": [
    {"id": "s1", "type": "platform", "capability": "select_analysis_sources",
     "binds": {"files": "$params.source_files"}},
    {"id": "s2", "type": "platform", "capability": "parse_source",
     "after": ["s1"], "params": {"scope": "included_files", "mode": "parallel"}},
    {"id": "s3", "type": "platform", "capability": "build_document_map", "after": ["s2"]},

    {"id": "s4", "type": "platform", "capability": "build_evidence_bundle", "after": ["s3"],
     "params": {"purposes": ["structure", "qualification", "submission", "business_technical", "format", "disqualification", "evaluation"], "mode": "parallel"}},

    {"id": "a1", "type": "skill", "skill": "classify_tender_structure",
     "after": ["s4"], "binds": {"bundle": "$s4.output.structure"}},
    {"id": "a2", "type": "skill", "skill": "extract_requirements",
     "after": ["s4"], "variant": {"purpose": "qualification"}, "binds": {"bundle": "$s4.output.qualification"}},
    {"id": "a3", "type": "skill", "skill": "extract_requirements",
     "after": ["s4"], "variant": {"purpose": "submission"}, "binds": {"bundle": "$s4.output.submission"}},
    {"id": "a4", "type": "skill", "skill": "extract_requirements",
     "after": ["s4"], "variant": {"purpose": "business_technical"}, "binds": {"bundle": "$s4.output.business_technical"}},
    {"id": "a5", "type": "skill", "skill": "extract_requirements",
     "after": ["s4"], "variant": {"purpose": "format"}, "binds": {"bundle": "$s4.output.format"}},
    {"id": "a6", "type": "skill", "skill": "extract_disqualification_clauses",
     "after": ["s4"], "binds": {"bundle": "$s4.output.disqualification"}},
    {"id": "a7", "type": "skill", "skill": "extract_evaluation_criteria",
     "after": ["s4"], "binds": {"bundle": "$s4.output.evaluation"}},

    {"id": "m1", "type": "platform", "capability": "reconcile_requirement_sets",
     "after": ["a2", "a3", "a4", "a5"]},
    {"id": "c1", "type": "skill", "skill": "detect_clarifications",
     "after": ["a1", "m1", "a6", "a7"],
     "binds": {"analyses": {"structure": "$a1.output", "requirements": "$m1.output", "disqualification": "$a6.output", "evaluation": "$a7.output"}, "source_set": "$s1.output"}},
    {"id": "p1", "type": "platform", "capability": "compose_preparation_snapshot", "after": ["c1"]},
    {"id": "p2", "type": "skill", "skill": "propose_response_file_plan",
     "after": ["p1"], "binds": {"preparation": "$p1.output", "clarifications": "$c1.output"}},

    {"id": "g1", "type": "human_input", "gate": "adopt_plan",
     "after": ["p2"], "binds": {"plan_candidate": "$p2.output"}},
    {"id": "p3", "type": "platform", "capability": "calculate_change_impact",
     "after": ["g1"], "params": {"kind": "adopt_baseline"}},
    {"id": "g2", "type": "human_input", "gate": "approval", "after": ["p3"]}
  ],
  "outputs": ["$g2.resulting_refs"]
}
```

单组失败不拖垮其它组（各自 analysis_status）；blocking 澄清未解决时 g2 拒绝放行。

### 5.3 `targeted_reanalysis`（局部重查）

```json
{
  "workflow_id": "targeted_reanalysis",
  "version": "1.0.0",
  "params": [
    {"name": "topic", "required": true, "enum": ["disqualification", "qualification", "evaluation"]},
    {"name": "supplement_text", "required": true}
  ],
  "nodes": [
    {"id": "n1", "type": "skill", "skill": "record_user_input", "variant": {"kind": "supplement"},
     "binds": {"text": "$params.supplement_text", "applies_to": "$params.topic"}},
    {"id": "n2", "type": "platform", "capability": "build_evidence_bundle",
     "after": ["n1"], "params": {"purpose": "$params.topic", "include_supplements": ["$n1.output"]}},
    {"id": "n3a", "type": "skill", "skill": "extract_disqualification_clauses",
     "after": ["n2"], "when": "$params.topic == 'disqualification'", "binds": {"bundle": "$n2.output"}},
    {"id": "n3b", "type": "skill", "skill": "extract_requirements",
     "after": ["n2"], "when": "$params.topic != 'disqualification'",
     "variant": {"purpose": "$params.topic"}, "binds": {"bundle": "$n2.output"}},
    {"id": "n4", "type": "platform", "capability": "compare_artifacts", "after": ["n3a", "n3b"]},
    {"id": "n5", "type": "platform", "capability": "calculate_change_impact", "after": ["n4"]},
    {"id": "n6", "type": "human_input", "gate": "approval",
     "after": ["n5"], "when": "$n5.moves_approved_head"}
  ],
  "outputs": ["$n5.output"]
}
```

旧 revision 保留；已批准基线只进 needs_review 或 ChangeSet 影响，不静默覆盖。

### 5.4 `answer_flow`（任意问答，2 节点迷你流）

```json
{
  "workflow_id": "answer_flow",
  "version": "1.0.0",
  "params": [{"name": "question", "required": true}, {"name": "scope_hint", "required": false}],
  "nodes": [
    {"id": "q1", "type": "platform", "capability": "build_evidence_bundle",
     "params": {"purpose": "ad_hoc_query", "query": "$params.question", "scope": "$params.scope_hint"}},
    {"id": "q2", "type": "skill", "skill": "answer_query",
     "after": ["q1"], "binds": {"bundle": "$q1.output", "question": "$params.question"}}
  ],
  "outputs": ["$q2.output"]
}
```

只读：不动 approved head；回答必须带范围声明（"已查范围内未发现"≠"全文不存在"）。

### 5.5 `outline_generation`（目录生成）

```json
{
  "workflow_id": "outline_generation",
  "version": "1.0.0",
  "params": [{"name": "baseline_ref", "required": true}, {"name": "plan_item_id", "required": true}],
  "nodes": [
    {"id": "o1", "type": "platform", "capability": "collect_itemrefs",
     "binds": {"baseline": "$params.baseline_ref", "plan_item": "$params.plan_item_id"}},
    {"id": "o2", "type": "skill", "skill": "generate_outline_candidate",
     "after": ["o1"], "binds": {"itemrefs": "$o1.output"}},
    {"id": "o3", "type": "platform", "capability": "validate_outline_coverage", "after": ["o2"]},
    {"id": "o4", "type": "skill", "skill": "revise_outline_candidate",
     "after": ["o3"], "when": "$o1.output.has_evaluation", "variant": {"mode": "scoring"},
     "binds": {"outline": "$o2.output", "mode_inputs": "$o1.output.score_items"}},
    {"id": "o5", "type": "skill", "skill": "revise_outline_candidate",
     "after": ["o3"], "variant": {"mode": "structure"},
     "binds": {"outline": "$o2.output", "mode_inputs": "$o1.output.constraints"}},
    {"id": "o6", "type": "platform", "capability": "apply_outline_edits", "after": ["o4", "o5"]},
    {"id": "o7", "type": "platform", "capability": "validate_outline_coverage",
     "after": ["o6"], "params": {"final": true}}
  ],
  "outputs": ["$o7.output"]
}
```

覆盖结论只出自确定性 gate（o3/o7）；LLM 只产候选和 edit proposals。**不重新全文抽取**——全部 ItemRef 来自准备阶段产物。

### 5.6 `publication_export`（发布与导出）

```json
{
  "workflow_id": "publication_export",
  "version": "1.0.0",
  "params": [{"name": "outline_candidate_ref", "required": true}],
  "nodes": [
    {"id": "e1", "type": "skill", "skill": "propose_outline_publication",
     "binds": {"candidate": "$params.outline_candidate_ref"}},
    {"id": "e2", "type": "human_input", "gate": "approval", "after": ["e1"]},
    {"id": "e3", "type": "platform", "capability": "apply_changeset",
     "after": ["e2"], "params": {"on": "$e1.output"}},
    {"id": "e4", "type": "platform", "capability": "apply_legacy_projection", "after": ["e3"]},
    {"id": "e5", "type": "platform", "capability": "compose_readiness_report", "after": ["e4"]},
    {"id": "e6", "type": "human_input", "gate": "approval",
     "after": ["e5"], "when": "$e5.output.has_blocking == false"},
    {"id": "e7", "type": "platform", "capability": "export_project_package", "after": ["e6"]}
  ],
  "outputs": ["$e7.output"]
}
```

e3 是全系统唯一能移动 approved head 的地方；e4 只投影不批准，回执带投影 hash，同 source/hash 重放幂等。

---

## 6. 新仓库落位

```text
new-repo/
├── contract/
│   ├── schemas/          ← 拷贝 4 个 Schema
│   ├── fixtures/         ← 测试夹具（可选，本仓库 examples/ 14 个可一并拷走）
│   └── validate.py       ← 校验脚本（本仓库 validate_v2_contracts.py）
├── skills/               ← 按 6 个 workflow + 下册定义建 12 个 LLM Skill 文件夹
│   └── <skill>/
│       ├── skill.json    # name/description/inputSchema（MCP 形状）+ 本域扩展
│       ├── system.md     # 从下册拷入
│       ├── user.md
│       └── fixtures/
├── workflows/            ← 本文 6 个 workflow.json 原样放入
└── runtime/              # 注册表加载校验（节点引用/binds 匹配/无环）、装袋机、门禁执行器、审计
```

启动校验：加载 skills → 校验 workflows（节点引用的 skill 存在、binds 名字与 inputSchema 匹配、无环、gate 可达）→ 汇总能力清单给 intake classifier 和 Chat/⌘K。
