# Tender Agent · 智能标书 AI Agent 桌面客户端

> **这可能是你能找到的功能最完整的标书编写 Agent**——
> 从招标文件解析、要点提取、目录生成，到**逐节 .docx 直出、合册成整本投标文件**，
> 全部在你的电脑上跑，数据不出本机。

---

## 为什么说「最全」

大多数标书 Agent 卡在「聊一聊、给个大纲」就交差。Tender Agent 跑的是**一条完整到能交付**的流水线：

| 通常别家停在 | Tender Agent 做到底 |
|---|---|
| 把招标文件读一遍、聊要点 | **逐节 .docx 直出**，批注 / 修订 / 表格单元格修订 / 单图插入 / 整本合册 |
| 给个目录就算交差 | **整本 docx 合册**（封面、目录、页眉页脚、版式自动应用），可直接打印 |
| 写完正文要人肉检查 | **写作指引 + 承诺清单**结构化表格界面，承诺项必须经人拍板才能落正文 |
| 写到一半模型挂了整本重来 | **HITL 单回合聚合 + 续跑**，草稿存档、续段从断点接上 |
| 素材复用要人肉拷贝 | **写作素材库**按区间勾出素材块，写作时按节自动注入改写 |
| 多模型要写代码切换 | **BYOK 多模型 UI**（DeepSeek / 智谱 / 百炼 / Kimi / 豆包 / MiniMax / OpenAI），按会话粘性记忆 |
| 整本写完要人肉改格式 | **版式库**（A4 / 字体 / 缩进行距 / 招标格式件保真） |
| 招标件扫描页只能看 | **百度 OCR / PaddleOCR-VL** 兜底 |
| 公司资质要人肉找 | **知识库**（营业执照、资质、人员证书、过往合同，事实层） |
| 出错了用户分不清是模型还是程序 | **错误分类 code**（`llm_unavailable` / `llm_auth` / `cancelled` / `interrupted` / `internal`），UI 按类别给对应动作 |

并且这些能力在**一台机器上、一个 App 里**串成一条流——不是散落的脚本。

---

## 完整工作流

针对一次投标任务，Agent 会按四段流水线协同作业，每个阶段之间有**确认门**让你改方向、补料：

| 阶段 | 技能 | 产出 |
|---|---|---|
| **1. 解析招标文件** | `document-parse` | docx / pdf / txt / md → 带行号的 markdown + 章节大纲 + 结构识别分档（书签 / 目录链接 / 印刷目录 / 中文编号） |
| **2. 要点提取** | `tender-analysis` | 资格 / 模板 / 商务技术要求 / 评分项 四类清单，每条带「章节 + 行号 + 页码」出处 |
| **3. 目录生成** | `tender-outline` | 响应文件目录树（多册并发派发，跨册去重互查） |
| **4. 正文撰写** | `tender-body` | 按目录逐节 .docx（写作指引 → 承诺清单 → 派发写手 → 合册成整本） |

附加技能：

- **`tender-qa`** — 就招标文件问具体问题，产物优先，证据回溯原文
- **`humanizer-zh`** — 中文去 AI 腔润色（按标书场景裁剪重写）
- **`docx` 工具族** — 建节 / 读视图 / 修订标记 / 合册 / 表格单元格修订 / 单图插入 / 批注

---

## 怎么用

### 1. 下载安装

到 [Releases](../../releases) 页面下载与系统对应的安装包：macOS（Apple Silicon / Intel）/ Windows（x64）/ Linux（.deb / AppImage）。`docs/packaging.md` 有打包流水线说明。

### 2. 配模型 Key

首次打开进入「设置 → 模型」：

- **添加模型**：填入 OpenAI 兼容协议的 API Key（DeepSeek、智谱、百炼、Kimi、豆包、MiniMax、OpenAI 等都支持）
- **测试连通**：保存即测，失败会提示
- **后台任务模型**（可选）：把知识库抽取、视觉转写这类小任务路由到便宜模型
- **思考档位**（可选）：low / medium / high，正文撰写一般建议 medium

Key 与配置存在本地 `app.db`，**不会上传任何服务端**。

### 3. 选个模型

右上角下拉切换本次会话用的模型，跨会话粘性记忆。

### 4. 开始一个任务

侧栏「新建任务」→ 给项目起个名 → 进入新建会话 → 把招标文件拖到「来源」区。
之后 Agent 会按 document-parse → tender-analysis → tender-outline → tender-body 的顺序自己往下走。

### 5. 写正文

进入「正文」阶段后，Agent 会先给出一份**写作指引**（每节用什么模式、引用哪些素材、依据哪些招标条款），确认后再写。每节一个 .docx 文件，最后可一键**合册**成整本投标文件——含封面、目录、页眉页脚、版式自动应用。

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│  Tauri 2 桌面壳（Rust）                                       │
│  - 窗口 / 系统集成（reveal in folder / 文件关联）             │
│  - sidecar 进程生命周期（spawn / healthz / 指数退避重启）    │
│  - **零业务逻辑**，只做壳                                    │
└──────────────────────────────────────────────────────────────┘
                              │  IPC + 内部 HTTP
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  React 19 + Vite + Tailwind 前端                              │
│  - 聊天 / 任务树 / 产物面板 / 工作台 / 设置                  │
│  - 只走事件契约（SSE 增量），不依赖 agent 内部格式            │
└──────────────────────────────────────────────────────────────┘
                              │  HTTP + SSE（127.0.0.1 + Bearer）
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Python sidecar（FastAPI + uvicorn）                          │
│  - DeepAgents 0.7.7 + subagents + middleware                 │
│  - SKILL.md 技能注册表（document-parse / tender-*）          │
│  - 任务级 workspace（每个投标项目一个目录）                    │
│  - 工具族：parse_document / docx 工具族 / 知识库 / 素材 / …  │
│  - SQLite：app.db（业务）+ agent.db（langgraph checkpoint）  │
└──────────────────────────────────────────────────────────────┘
                              │  HTTPS
                              ▼
                ┌────────────────────────────┐
                │  你自带的 LLM API（BYOK）   │
                └────────────────────────────┘
```

三条铁律（任何实现不得违反）：

1. **Rust 不含业务逻辑**——壳就是壳。
2. **API Key 只写不读**——Key 存本地 `app.db` 的 `app_settings` 表，从不回显到 HTTP 响应/前端内存。
   `GET /settings` 只回 `key_configured: true/false`；环境变量只作兜底读取。
3. **前端只走事件契约**——不依赖 DeepAgents 内部流格式，SSE 是唯一的实时通道。

---

## 三种运行模式

前置：`uv`（Python ≥3.12）、Node ≥20、Rust stable ≥1.85。

```bash
# A. Tauri 桌面（推荐，一条命令）
npx tauri dev

# B. 浏览器开发（适合改前端时热更快）
npm run dev:browser    # 一条命令：sidecar(8765) + Vite 一起起
# 分开也行：
#   cd sidecar && uv run --env-file .env python -m app.main --port 8765
#   cd frontend && npm run dev

# C. 纯 sidecar（只想用 API / 接别的客户端）
cd sidecar && uv sync && uv run --env-file .env python -m app.main --port 8765
curl localhost:8765/api/healthz
```

国内网络需要配镜像：`sidecar/pyproject.toml` 已内置清华源；`frontend/.npmrc` 用 npmmirror；`src-tauri/.cargo/config.toml` 用 rsproxy。

---

## 工程结构

```
.
├── sidecar/                  Python sidecar（FastAPI + DeepAgents + SQLite）
│   ├── app/
│   │   ├── agent.py          build_agent + run_stream（流式事件 / 协作取消 / HITL）
│   │   ├── events.py         LangGraph 流 → SSE 事件的唯一映射层
│   │   ├── contracts/        契约单一事实源（pydantic → 自动生成 TS 类型）
│   │   ├── db.py / db_migrations.py   SQLite + schema 版本化迁移
│   │   ├── api/              tasks / conversations / runs / files / artifacts
│   │   │                     / knowledge / materials / workbench / templates
│   │   ├── tools/            LLM 工具（parse_document / docx 族 / publish / read / …）
│   │   ├── skills/           document-parse / tender-* / humanizer-zh
│   │   ├── parse/            docx / pdf / txt / md 解析注册表
│   │   └── knowledge/        FTS5 知识库
│   ├── scripts/              gen_ts_types.py（pydantic → TS interface）
│   └── tests/
├── frontend/                 React 19 + Vite + Tailwind
│   └── src/
│       ├── api/              client / sse / events.gen / dto.gen（自动生成）
│       ├── hooks/            useRun + runReducer（带 vitest）
│       └── components/       workspace + 三栏 + 产物面板 + 工作台 …
├── src-tauri/                Tauri 2 壳
│   └── src/                  sidecar.rs / commands
├── docs/
│   ├── user-stories.md       14 个 Epic + 偏离场景的完整用户故事
│   ├── packaging.md          多平台打包流水线
│   ├── designtokens/         设计 token
│   ├── prototypes/           UI 原型
│   └── skill design/         skill 重构手册 + 四个 JSON Schema
├── AGENTS.md                 给 coding agent 的工作约定（边界/铁律/历史决策）
├── check.sh                  一键全栈检查（Python + TS + Rust）
└── LICENSE
```

---

## 文档索引

- **`docs/user-stories.md`** — 14 个 Epic + 47 个偏离场景的用户故事，可直接拆卡
- **`docs/packaging.md`** — 多平台打包流水线（PyInstaller 冻结 + Tauri externalBin）
- **`AGENTS.md`** — 给在这个仓库写代码的 agent 看的工程约定（铁律、架构边界、历史决策索引）
- **`sidecar/scripts/gen_ts_types.py`** — pydantic → TS 类型生成器；改契约必跑 + 入库
- **`docs/skill design/`** — skill 体系的重构手册（背景 / Workflow / 四个 JSON Schema）

---

## 开发与测试

```bash
./check.sh            # sidecar ruff/pytest + frontend lint/tsc/vitest/build + rust check/clippy
./check.sh sidecar    # 只查 Python
./check.sh frontend   # 只查前端
./check.sh rust       # 只查 Rust
```

注意：`check.sh` 里 `gen_ts_types.py` 会重生成前端 TS 类型并与入库版本 diff——
**改了 pydantic 契约模型忘了跑生成器会在这里挂**。

---

## 参与贡献

Issues / PR 都欢迎。新增能力前建议先看 `AGENTS.md` 里的设计铁则与历史决策，能少走很多弯路。

如果你想：

- **加一个 skill**：照 `sidecar/app/skills/tender-*/SKILL.md` 格式 + `references/`；description 只写触发关键词
  （不要把流程概述塞 description 里，实测会让模型走捷径）。
- **加一个 LLM 工具**：写在 `sidecar/app/tools/`，注册到 `agent.py` 的 TOOLS；契约模型放 `app/contracts/` 并跑 `gen_ts_types.py`。
- **改前端组件**：`frontend/src/components/`；样式走 `tokens.css` + Tailwind v4 的 `color-mix()` 派生。
- **改事件契约**：pydantic 模型是唯一真源；`events.gen.ts` / `dto.gen.ts` 自动生成，不要手改。

提交前跑 `./check.sh` 全绿。

---

## 已知限制与未来工作

- **断线补发**：MVP 不做历史事件补发，刷新/重连靠 `run.state` 收敛。详见 AGENTS.md。
- **跨平台打包**：当前 macOS / Windows / Linux 各自要原生机器构建，详见 `docs/packaging.md`。
- **代码签名 / 自动更新**：暂未做，下载安装需要用户手动确认。
- **驾驶舱式全局视图**：侧栏已有运行状态指示，但全局任务看板是 Phase 2+ 候选。

---

## License

[MIT](./LICENSE) © 2026 Tender Agent Contributors

---

## 致谢

- 底层：[DeepAgents](https://github.com/langchain-ai/deepagents) / LangGraph
- 前端：[React 19](https://react.dev) + [Vite](https://vitejs.dev) + [Tailwind CSS v4](https://tailwindcss.com)
- 桌面壳：[Tauri 2](https://tauri.app)
- PDF 解析：[PyMuPDF](https://pymupdf.io)
- docx 解析与产出：[python-docx](https://python-docx.readthedocs.io)
- 通用润色：[Humanizer-zh](https://github.com/op7418/Humanizer-zh)（MIT）

---

> 截图占位：后续在 `docs/screenshots/` 下放 1-2 张主界面图，README 顶部会引用。
