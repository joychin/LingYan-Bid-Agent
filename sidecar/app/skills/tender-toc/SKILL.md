---
name: tender-toc
description: 解析招标文件并抽取目录（TOC）。当用户提供一份《招标文件》（.docx/.doc/.pdf），希望自动生成「投标文件章节规划 /
  目录树」，或抽取招标文件自身的标题大纲时触发本技能。适用场景：招投标、标书编写、投标文件目录生成、招标文件结构化解析。本技能为 Agent
  原生版——不调用任何第三方 LLM 网关，整条流水线（解析招标文件 → 解析出响应文件 → 规划各响应文件目录）由宿主 Agent
  按 references/prompts.md 的提示词逐步完成，脚本仅做确定性工作（docx→Markdown、目录树与来源标注解析、导出
  JSON）。
homepage: https://github.com/chenzhuo/workbuddy-skill-tender-toc
agent_created: true
metadata:
  openclaw:
    emoji: 📑
    homepage: https://github.com/chenzhuo/workbuddy-skill-tender-toc
    requires:
      bins:
        - python3
      pip:
        - python-docx
---

# 招标文件解析 → 目录（TOC）技能（Agent 原生版）

## 概述

把一份甲方《招标文件》解析为可直接用于编制投标文件的「目录 / 章节规划树」，**按响应文件（投标分册/分标）分别规划**，并附带来源标注（lineage）与目录说明。

**本技能不依赖任何第三方 LLM 网关。** 脚本 `scripts/parse_toc.py` 只做确定性工作：
`convert`（docx→Markdown）、`file`（抽招标文件自身大纲）、`build`（组装 JSON）。
中间的「思考」步骤——**S1 解析招标文件（F1/F2/F3）→ S2 解析出响应文件（R1）→ S3 规划各响应文件目录（R2）**——
全部由 **宿主 Agent（你）** 按 `references/prompts.md` 的提示词逐步完成，
并把结果写成 Markdown 文件，最后由脚本 `build` 组装成 `tender-response-docs.json` / `tender-directory.json`。

三种主路径：
- **完整分析（推荐）**：Agent 走完 S1→S2→S3，产出多响应文件目录树（每个响应文件一棵带 lineage + 目录说明的目录）。
- **仅看文档结构**：`file` 子命令免 LLM，直接抽取招标文件自身的标题大纲。
- **兼容旧版单文档**：仅产出 `tender-plan-final.md`（单个合并响应文件），`build` 仍接受。

## 触发场景

- 用户提供招标文件（.docx / .doc / .pdf），要求「生成投标文件目录 / 章节大纲」
- 用户要求「解析招标文件，提取目录 / 结构」
- 用户做标书编制前期，需要从招标文件中梳理响应文件应有的章节结构（尤其分册/分标投标）
- 用户想快速查看一份招标文件自身的目录 / 大纲（file 模式）

## 前置依赖

依赖（python-docx）已由宿主应用预装。脚本执行通过宿主提供的 **工具** 完成——不要自己跑 shell 命令，直接调用：
`convert_tender`（转换）、`extract_toc`（仅抽大纲）、`build_tender`（组装 JSON）。

可选：LibreOffice（soffice）用于 .doc / .pdf → .docx 转换；未安装时仅支持 .docx 原生输入。

> 无需任何 LLM API Key / 网关配置——推理由 Agent 自身完成。

## 执行流程（完整分析）

### 第 1 步：convert（确定性）

调用 **`convert_tender` 工具**，参数为招标文件路径（如 `招标文件.docx`）。

生成 `out/tender-full.md`（完整 Markdown）。若输入为 .doc/.pdf，脚本自动用 soffice 转 docx。

### 第 2 步：Agent 三阶段分析（按 references/prompts.md）

> 所有中间产物一律用 `write_file` 写到 `out/` 目录（与 tender-full.md 同目录）。

**S1 解析招标文件** —— Agent 读取 `tender-full.md`，产出（严禁 ``` 代码块包裹；目录用无编号真实缩进列表）：

1. **F1** → `tender-extraction.md`（结构要求 + 必须章节 + 模板 + 封装/分册方式）
2. **F2** → `tender-index-tight.md`（业务/技术要求清单，raw）
3. **F3** → `tender-scoring.md`（评分标准清单）

**S2 解析出响应文件（R1）** —— Agent 读 F1 结合「封装/分册/装订」要求，识别本次投标需要的响应文件集合，
在 `tender-response-docs.md` 写出骨架：每个响应文件一个顶层 `# 响应文件：XXX` 标题 + scope 段落。

**S3 规划各响应文件目录（R2）** —— Agent 对 `tender-response-docs.md` 中**每个**响应文件就地补全：

- `## 目录`（基于该响应文件 scope，套用 F1/F2/F3 的规划与补缺逻辑）
- `## 来源标注`
- `## 目录说明`

每一步的详细规则、层级规则、来源标注与目录说明格式，见 `references/prompts.md`。

> 为控制开销，Agent 也可把 F1/F2/F3 合并阅读、把 S2→S3 在一次或两次长思考中完成，但**至少**要写出
> `tender-extraction.md`、`tender-index-tight.md`、`tender-response-docs.md` 三个文件（build 步骤依赖它们；
> `tender-scoring.md` 可选，存在则纳入 lineage）。

### 第 3 步：build（确定性，组装 JSON）

调用 **`build_tender` 工具**（无参数）。

读取 Agent 产出的文件（`out/` 目录），解析每个响应文件的目录树 + 来源标注 + 目录说明，导出：

- `tender-response-docs.json` — **核心交付物**：`{"response_documents":[...], "registry":{}}`，每个响应文件一棵带 lineage / 目录说明的目录
- `tender-directory.json` — 聚合视图：每个响应文件作为顶层节点（`{"directory":[{目录名称, level, children, scope}], "registry":{}}`），便于只需单棵树的下游消费
- `tender-registry.json` — 四类来源登记表（MAND/TPL/REQ/SCORE 单一真相源）

### 仅看文档自身大纲（免 LLM）

调用 **`extract_toc` 工具**，参数为招标文件路径。

生成 `out/tender-file-toc.md` / `out/tender-file-toc.json`（招标文件自身标题大纲）。

## 输出产物（./out）

| 文件 | 内容 | 产出方 |
|------|------|--------|
| `tender-full.md` | docx 转出的完整 Markdown | 脚本(convert) |
| `tender-extraction.md` | F1 结构要求 + 必须章节 + 模板 + 封装/分册 | Agent |
| `tender-index-tight.md` | F2 业务/技术要求清单 | Agent |
| `tender-scoring.md` | F3 评分标准清单 | Agent |
| `tender-response-docs.md` | S2 骨架 + S3 各响应文件目录/lineage/目录说明 | Agent |
| `tender-response-docs.json` | **各响应文件目录树 + lineage / 目录说明 + registry + meta** | 脚本(build) |
| `tender-directory.json` | 聚合单树视图（响应文件为顶层，层级已整体下移）+ registry + meta | 脚本(build) |
| `tender-directory.html` | **人类可读交付物**：自包含 HTML（元信息/目录树/来源登记表，可打印 PDF）；**点击节点上的来源徽章（MAND/TPL/REQ/SCORE）弹出大号弹窗，展示原文片段、原文位置与关联目录节点** | 脚本(build) |
| `tender-registry.json` | 四类来源登记表 | 脚本(build) |
| `tender-file-toc.md/.json` | 招标文件自身标题大纲（file 模式） | 脚本(file) |
| `tender-plan-final.md` | 旧版单文档流程（兼容回退，可选） | Agent |

## tender-response-docs.md 结构（build 输入契约）

```
## 项目信息（可选）
- 项目名称：XX 采购项目
- 招标编号：XXXX

# 响应文件：技术部分
<scope 段落：覆盖范围与划分依据>

## 目录
- 技术方案（附件N）
  - 需求理解
  - 总体设计
- …

## 来源标注
- 技术方案（附件N） :: MAND-03, REQ-11
- …

## 目录说明
- 技术方案（附件N） :: 交付形态=正文编写 | 归位理由=… | 理由来源=MAND-03 | 概述=…
```

- 顶层 `# 响应文件：XXX` 数量 = 响应文件数；每个段内 `## 目录` 为目录树、`## 来源标注`/`## 目录说明` 为标注。
- scope 段落 = 该 `# 响应文件` 段内 `## 目录` 之前的所有文本（脚本自动忽略 `scope：` 前缀）。
- 可选的 `## 项目信息`（二级标题，置于文件顶部）会被提取为 JSON `meta` 字段并显示在 HTML 顶部。

## lineage（来源标注）schema

`registry` 四类来源 ID，是目录节点来源的单一真相源：

- `MAND-xx` = 招标文件规定的必须章节
- `TPL-xx` = 招标方给出的模板 / 格式
- `REQ-xx` = 业务 / 技术要求
- `SCORE-xx` = 评分标准维度

`response_documents[].directory` 中每个目录节点结构：

```json
{
  "目录名称": "技术方案（附件N）",
  "level": 2,
  "children": [ ... ],
  "来源": ["招标文件规定", "需求"],
  "来源位置": ["MAND-03", "REQ-11"],
  "交付形态": "正文编写",
  "归位理由": "…",
  "理由来源": ["MAND-03"],
  "节点概述": "…"
}
```

`交付形态` 取值枚举：`正文编写` / `模板或附件填充` / `混合` / `目录容器` / `待核验`。

JSON 顶层另含两个辅助字段：
- `meta`：来自 `tender-response-docs.md` 顶部可选的 `## 项目信息` 段（项目名称/招标编号等），无则空对象。
- `lineage_check`：`{"unused_ids": [...], "dangling_ids": [...]}` —— `unused_ids`=未被任何目录节点引用的来源 ID；`dangling_ids`=被引用但 registry 中不存在的 ID（悬空，多为 F2/F3 行序漂移或编号拼写错误）。两者均会在 console 与 HTML 提示；均为空即全部来源有归属且可解析。

## 注意事项

- **目录 vs 招标文件自身大纲**：完整分析产出的是「投标文件应有的章节规划（按响应文件分册）」，file 模式产出的是「招标文件原文里的标题大纲」。两者含义不同，按需选路径。
- **招标文件类型校验**：本流水线专用于《招标文件》（甲方发包，含评分标准/结构要求）。若误投《投标文件》（乙方应标，无评分标准），会退化成扁平树、且 lineage 退化，务必先确认文件类型。
- **空目录守卫**：若 `tender-response-docs.md` 未解析出任何响应文件目录，JSON 会写入 `warning` 字段而非静默输出空树。
- **文件类型转换**：.doc / .pdf 经 soffice 转换；转换后的 docx 仅用于解析，不覆盖原文件。
- **旧版兼容**：`build` 同时接受旧版单文档 `tender-plan-final.md`（单个合并响应文件），自动降级为聚合视图。
