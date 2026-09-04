# 产物查看/编辑重做方案（2026-09-04 定稿）

背景：当前产物的查看与编辑体验不足——目录只能改结构的一半（无跨层级移动、
无右键菜单、无撤销），来源徽章点不开（证据链白费），笔记/工作台是裸 textarea
源码编辑，保存状态不可见。参考老工程 document_helpler 的成熟交互（目录树编辑
操作集、保存状态条+自动保存竞态处理、来源追溯弹窗），结合本仓底座重新设计。

## 已拍板决策（2026-09-04）

1. **标注字段编辑边界**：证据性字段（来源 / 来源位置 / 理由来源 / 交付形态——
   节点「为什么长这样」的推导记录与证据锚）**永远只读**；表达性字段
   （节点概述 / 归位理由）**二期开放编辑**（本方案不含）。
2. **目录编辑画布**：维持在「面板内宽态工作区」（对话不中断，覆盖式浮层裁定），
   不做独立整页。
3. **markdown 编辑器**：CodeMirror 6 源码编辑 + 实时预览分屏（不搬老工程
   Tiptap 富文本——那边真源是数据库里的 ProseMirror JSON，我们真源是
   markdown，富文本互转有损，等于换真源）。
4. **工作台恢复点**：从单一 .bak 对齐到 3 个（与产物一致）。

## 总原则

- **借交互、不搬架构**：老工程的行级版本链 / section_snapshots / SSE 候选树
  均不搬；本仓「无锁 + 乐观探测 + 409 用户裁决 + 恢复点兜底」铁则不变，
  content_seq / hash 仍是探测器不是锁。
- 真值仍是磁盘文件（产物 JSON 契约 / work md），所有改动是 additive：
  新增 2 个轻量 GET 端点，既有端点语义不动（workbench/restore 语义微调见批次 1）。
- 新增依赖（均 MIT）：`@uiw/react-codemirror` + `@codemirror/lang-markdown`
  （批次 3）、`@dnd-kit/core`（批次 4）。UI 组件仍手写零 radix/cva，
  这两条是功能库不违反该纪律。

## 批次 1：编辑基建统一（先行，其余批次踩在它上面）

**目标**：三个编辑表面（DirectoryProcessor / NoteProcessor / WorkbenchViewer）
共用一套自动保存 + 竞态防护 + 保存状态条；补齐笔记查看态跟随；探测轮询降载。

### 1a. `hooks/useAutoSave.ts`（新）

参数化三处差异（产物按 aid+content_seq、工作台按 task+path+hash）：

```
useAutoSave({
  save(content, force): Promise<newVersion>,   // 返回新版本号（seq 或 hash）
  fetchMeta(): Promise<version>,               // 轻量探测（见 1c）
  initialVersion, debounceMs = 800, pollMs = 5000,
})
→ { state, markDirty, saveNow, adoptLatest }
// state: 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'
```

竞态防护抄老工程 `useSectionAutoSave` 的两层（本仓三处现状均缺）：

- **请求序号守卫**：单调递增序号，响应回来时序号已落后则丢弃（旧保存晚回
  不得覆盖新状态的判断）；
- **inflight 串行化**：保存进行中又有新改动 → 挂起最新内容，完成后立即续存，
  永不并发两个保存请求。

外部更新探测语义不变：无本地改动静默跟随（adoptLatest 换基底）、有本地改动
置 conflict 弹「拉取最新 / 保留我的」。**笔记补上此前有意缺失的 5s 探测**
（只读态跟随、编辑态裁决——与目录对齐，AI 重发产物后界面不再显示旧内容）。
卸载冲刷保留现状（先常规后 force，「主导权归用户」）。

### 1b. `components/editors/SaveStateBar.tsx`（新）

老工程四态状态条的薄版，每个编辑表面头部恒显：
`保存中… / 已保存 · 刚刚 HH:MM / 未保存 / 保存失败 · 重试 / 有新版本 · 二选一`。
替代现状各自为政的「保存中…」小字（NoteProcessor）与无指示（工作台）。

### 1c. 轻量探测端点（sidecar，2 个 GET）

- `GET /api/artifacts/{aid}/meta` → `{content_seq, state}`；
- `GET /api/workbench/meta?task_id=&path=` → `{hash, revised, editable, has_restore}`。

冲突探测不再拉全量 `listArtifacts()` / 全文 content。dto 契约同步再生。

### 1d. 工作台恢复点 ×3（sidecar + 前端）

- 存储：`work/<path 同级>/<name>.restorepoints/NNNN.bak`（`.bak` 后缀不匹配
  `rglob("*.md")` 永不进列表；也不进 run_files「本轮文件」收录口径——非 .md）。
  写前 push、保留最近 3 个（对齐 `artifact_store.save_restore_point` 模式）。
- **旧 .bak 收编**：恢复点栈为空且存在旧 `<name>.md.bak` 时，把它收为栈里
  最旧一条（不删用户数据）。
- `POST /workbench/restore` 语义从「与 .bak 互换」改为「当前内容先入栈、
  恢复最近恢复点」——可再撤销语义保留（恢复后再恢复=回到恢复前），深度从 1 变 3。
- 前端「恢复上一版」按钮文案不变；`has_backup` 字段随端点改 `has_restore`。

**验收**：三界面状态条五态一致；编辑中快速连续输入 10s 无「旧响应覆盖新内容」
（vitest 给 useAutoSave 竞态用例）；笔记只读态在 AI 重发后 ≤5s 静默刷新；
探测轮询响应体只含版本字段；工作台连续保存 4 次后恢复点恰 3 个、可连续
恢复两步（pytest 覆盖收编与保留逻辑）。

## 批次 2：目录查看——来源追溯弹窗 + 树搜索（纯前端）

- **来源追溯弹窗** `components/processors/SourceTraceDialog.tsx`（新）：
  目录节点上的来源徽章（MAND/TPL/REQ/SCORE）可点击 → 弹窗展示登记条目
  （registry[id] 的 type / text / 出处，数据已在契约里、登记表折叠区已在消费，
  零后端改动）。样式与浮层纪律走既有 Dialog，不溢出容器。
- **树搜索**：DirectoryProcessor 树顶加过滤框（匹配 目录名称 / 节点概述），
  命中路径自动展开、未命中折叠，显示「N 个匹配」。深目录找节点不再靠肉眼。
- 「跳转原文上下文」动作（弹窗内 → 打开 parse md 定位行号）**依赖批次 3 的
  编辑器行号定位**，接线放批次 3 一起交付；本批弹窗以登记原文自足。

**验收**：点任意徽章弹窗显示原文+出处；搜索两字命中自动展开全部命中路径；
lineage 告警横幅、meta chips 等现有查看能力零回归。

## 批次 3：markdown 编辑器统一（CodeMirror + 分屏）

- `components/editors/MarkdownEditor.tsx`（新）：`@uiw/react-codemirror`
  + `@codemirror/lang-markdown`。能力：语法高亮、行号、内建 undo/redo
  （Cmd+Z，替代受控 textarea 下本就残废的原生 undo）。
- **布局三态**：源码 / 分屏 / 预览（头部切换）。查看态=预览 only（现 ReactMarkdown
  渲染管线复用，GFM、单波浪关闭不动）；编辑态默认分屏，窄面板自动退单栏。
- **受控纪律**：外部内容到达时仅在「内容确实不同且用户未在编辑」才 set
  （防打字被外部刷新打断、防 undo 栈被重置）；用户输入走 onChange 单向同步。
- 接入：NoteProcessor（标题 input 保留，正文换编辑器）、WorkbenchViewer
  （textarea 替换；MACHINE_INPUTS 行数漂移确认闸保留——行数取 CodeMirror
  `doc.lines`，语义不变）。
- **原文定位接线**：`App.openWorkbenchFile(path, anchor?)` 扩展可选
  `{line}`（prop 链 App → ArtifactPanel → WorkbenchViewer）；有 anchor 时
  打开即切源码栏滚到目标行（CodeMirror scrollIntoView + 行高亮闪烁一次）。
  批次 2 弹窗的「查看原文上下文」按钮在本批点亮（解析出处字段的「文件名+L行号」）。
- 滚动同步（分屏左右按比例联动）：**一期不做**，预留。

**验收**：编辑笔记/工作台有高亮+行号+可撤销；分屏预览 ≤100ms 跟随；
机器输入行数闸行为不回归（现有测试不动全绿）；追溯弹窗点「查看原文」
打开 parse md 并定位到行。

## 批次 4：目录树编辑操作集（工作量最大，最后单独一批）

对齐老工程 `simple-tree-panel` 的完整操作集，画布仍为面板宽态工作区：

- **跨层级拖拽**（@dnd-kit/core）：前 / 后 / 内 三种落点（矩形分区判定），
  拖入自身或后代时拦截 + toast；现有同级排序的上移/下移按钮保留。
- **右键菜单**（手写浮层，对齐触发器、不溢出视口）：升级 / 降级、上移 / 下移、
  新增同级 / 新增子级、删除。层级 **5 级封顶**（超出禁用 + tooltip 说明），
  删除子树后选中回退到父节点，删除维持两次点击确认。
- **行内改名**：点标题即改（现为编辑态固定 input）。
- **撤销/重做**：本地快照栈 50 步（ref 存树快照，编辑会话内有效，进编辑态时
  初始化、退出/保存成功后清空——不做跨会话历史，版本管理已砍）。
- **结构性变更确认条**：保存时与进编辑态的初始树快照 diff——节点路径集合
  变化（增/删/移动）= 结构性，保存前弹轻量 inline 确认条（非模态）说明
  「会影响后续 AI 以此目录为准的工作」；仅改名/概述变化不触发。告知不是门禁，
  确认一次后本次保存放行。
- **组件合并**：查看态 TreeNode 与编辑态 EditableNode 两套渲染合并为一套
  （编辑态 = 查看节点 + hover 显操作），消除重复。
- 运行期 `_id` 寻址 + 保存剥离写回的模型不变；契约 schema 不动。

**验收**：拖任意节点到另一父级成功且落盘（重开面板结构正确）；undo 可撤销
一次拖拽；结构性保存前出现确认条、纯改名保存无确认条；两套树组件合并后
查看态徽章/概述/告警横幅零回归。

## 实施记录（2026-09-04，四批全部落地）

- 批次 1-4 按 plan 完成；sidecar 393 pytest + 前端 83 vitest + build/lint 全绿；
  dto.gen.ts 已再生入库（ArtifactMeta）。
- **偏离 1（批次 3）**：未装 @dnd-kit/core——拖拽在现有原生 HTML5 同级拖拽上
  扩展三区落点（上 25%/下 25%/中 50%），+30 行达成同等交互，少一个依赖与
  约 200 行 sensors/DragOverlay 重构（简洁铁则）。
- **偏离 2（批次 4）**：查看/编辑两套节点组件未强行合并为单组件——徽章/概述
  渲染已共享（badgeStyle/类型统一到 directoryTree.ts），骨架保留两套（展开逻辑
  受控/自管不同；查看态刚做搜索+追溯增强，合并重构风险大于重复 15 行的收益）。
- **偏离 3（批次 4）**：undo/redo 保存成功后**不清栈**（计划原文「保存成功/退出
  清空」）——「刚保存完想撤销一步」是合法预期，清栈会逼用户手动改回；退出编辑
  自然清空（组件卸载）。
- 落地文件清单：sidecar（api/artifacts.py meta 端点、api/workbench.py 恢复点栈
  +meta 端点、contracts/dto.py ArtifactMeta、tests/test_workbench.py +
  test_artifacts.py）；前端（hooks/useAutoSave.ts+.test.ts、components/editors/
  SaveStateBar.tsx + MarkdownEditor.tsx、components/processors/directoryTree.ts
  +.test.ts + DirectoryEditor.tsx + SourceTraceDialog.tsx、三编辑表面重写、
  App/ArtifactPanel/ArtifactOpenHost/registry anchor 链路、tokens.css --Color-info、
  workspace.css .md-editor 段、index.css info/warning-foreground 映射）。

## 二期预留（本方案不含）

- 表达性字段编辑（节点概述 / 归位理由）——等结构编辑用顺后再开；
- 分屏滚动同步；
- 工作台机器输入三文件的表格化编辑辅助（先靠分屏预览缓解）。

## 不做清单

- 富文本编辑器（真源不同，理由见拍板 3）；
- 数据库版本链 / 章节快照表 / 版本列表 UI（恢复点兜底已够，版本管理已砍）；
- 实时协同、编辑锁、租约（铁则）；
- 证据性字段编辑（拍板 1）；
- 目录编辑独立整页（拍板 2）。

## 实施顺序与检查

批次 1 → 2 → 3 → 4，每批独立可验收可暂停。批次 1 动 sidecar（2 端点 +
恢复点栈 + dto 再生 `git add`）与前端（hook/组件/三处替换）；批次 2 纯前端；
批次 3 加依赖 + 两处接入 + anchor 链路；批次 4 加依赖 + DirectoryProcessor
重写编辑态。每批收尾跑 `./check.sh`；批次 1 的 sidecar 改动补 pytest
（meta 端点 / 恢复点栈 / 旧 .bak 收编），前端补 useAutoSave vitest。
