# 灵燕智能 · Tender Agent

**本地运行的标书写作 AI 智能体。** 上传招标文件和公司资料，它读原文、理要点、搭目录、逐节写出带出处的投标正文，最后合成一份带修订标记的整本 Word——全程在你自己的电脑上运行，模型 API Key 你自己带（BYOK）。

> Local-first desktop AI agent that turns tender documents into bid proposals:
> evidence-linked section writing, human-in-the-loop commitments, and a
> tracked-changes .docx as the final deliverable. No cloud service, no data leaving your machine.

[![Release](https://img.shields.io/github/v/release/joychin/Bid_Copilot_client?label=%E4%B8%8B%E8%BD%BD)](https://github.com/joychin/Bid_Copilot_client/releases)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-blue)](https://github.com/joychin/Bid_Copilot_client/releases)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-orange)](LICENSE)

## 一条流水线，五步交付

```
 招标文件（.docx / .pdf / 扫描件）
    │
    │ ① 解析      章节结构识别（书签/目录链接/印刷目录/编号多级兜底），
    │             扫描件走可选的百度云 OCR，每页内容带行号锚点
    ▼
 关键要求清单   资质、工期、评分办法、履约、售后…逐项列出，
    │ ② 提取要点  每条注明出自原文第几页、第几行——你确认口径
    ▼
 投标目录       照评分办法组织章节，每节写什么、缺什么材料，
    │ ③ 生成目录  先列清楚再动手——你确认目录
    ▼
 正文（逐节）    有素材的改写你的素材；招标方给了格式件的照原件
    │ ④ 逐节写作  拷贝填空；都没有才推理撰写。多节并行派发，
    │             工期、质保这些承诺值先问你，拍板了才写
    ▼
 整本 Word      封面、标题分级编号、页码、表格按标书惯例排好；
    │ ⑤ 合册交付  AI 改动全部带修订标记，缺料/待办进批注——
                你在 Word 里逐条接受修订、解决批注，就是终稿
```

## 写得快，也要靠得住

快靠模型；靠得住靠的是三件事：

- **每个结论都有出处。** 正文里的要求和数字后面跟着招标原文的章节与行号，写完还有机器校验——引用锚不到原文行号的内容过不了自查，评审对照、自己复核都能直接翻到那一段。
- **重要事项先问你。** 不能拍脑袋的事（工期填多少、质保承诺几年、用哪份资质）它会停下来先问，你确认了才写进正文；问答和审批都发生在对话里，随时可停、可改、可重来。
- **交付一份标准 Word。** 正文、表格、封面、证书图都在一个 .docx 里，版式走标书基准模板；AI 的全部改动带修订标记，审阅权在你手里；待办留在批注里，打印和导出 PDF 不会带出去。

## 三个内容库，越攒越顺

| 库 | 装什么 | 怎么用 |
| --- | --- | --- |
| **素材库** | 过往标书、公司文档，按目录树勾选区间拆成带出处的素材块 | 写正文时按节检索取用：引用保持原文，改写适配本项目；重复块自动检测 |
| **知识库** | 营业执照、资质证书、合同案例、人员证书等公司证明材料 | 传一次，自动识别类型和有效期；投标要什么证明直接查，到期会提醒，证书扫描件可贴进正文 |
| **版式库** | 版式模板（内置一份标书基准版式） | 上传你单位的模板设为默认即可统一观感；只影响之后新建的节，不动已写内容 |

## 架构

```
┌─────────────────────────────────────────────────┐
│  Tauri 2（Rust）  窗口 · sidecar 进程管理 · IPC   │  零业务逻辑
└────────────────────┬────────────────────────────┘
                     │ webview
┌────────────────────▼────────────────────────────┐
│  React 19 + Vite + Tailwind                     │
│  对话 · 任务 · 工作台 · 产物面板 · 三库 · 设置     │
└────────────────────┬────────────────────────────┘
                     │ HTTP + SSE（仅 127.0.0.1 本机回环）
┌────────────────────▼────────────────────────────┐
│  Python sidecar（FastAPI + DeepAgents）          │
│   skills：document-parse / tender-analysis /     │
│           tender-outline / tender-body / tender-qa │
│   工具：解析 · 检索 · 发布 · docx 直出 · 校验 …    │
│   SQLite（app.db）+ workspace 任务文件树           │
└────────────────────┬────────────────────────────┘
                     │ OpenAI 兼容协议
        你自己的模型 API（BYOK，默认 DeepSeek，
        多模型 profile，可选配百度云 OCR）
```

三条铁律（任何实现不得违反）：

1. Rust 壳不含任何业务逻辑。
2. **API Key 只写不读**：Key 在应用「设置」里填写，存本地 SQLite（`app.db`），
   `GET /settings` 永不回读 Key、只返回 `key_configured` 布尔；环境变量仅作开发兜底。
3. 前端只消费 sidecar 的事件契约（`agent.started / agent.token / tool.called /
   run.state …` SSE 事件），不依赖 agent 框架的内部格式。

## 快速开始

### 方式一：下载安装包

到 [Releases](https://github.com/joychin/Bid_Copilot_client/releases) 下载 macOS（.dmg）或
Windows 安装包，启动后在「设置 → 模型」里添加模型并填入 API Key 即可使用。

### 方式二：源码运行（开发者）

前置：Node ≥ 22、[uv](https://docs.astral.sh/uv/)（Python ≥ 3.12）、Rust stable。

```bash
git clone https://github.com/joychin/Bid_Copilot_client.git
cd Bid_Copilot_client
npm install                            # 根：Tauri CLI 等编排依赖
(cd frontend && npm install)           # 前端依赖
(cd sidecar && uv sync)                # Python 依赖（dev 模式 sidecar 从 .venv 启动）
npx tauri dev                          # 桌面客户端一条命令拉起
```

首次启动在应用内「设置 → 模型」添加模型：内置主流厂商预设（DeepSeek / Kimi / 通义 /
智谱 / 豆包 / OpenAI …），任意 OpenAI 兼容协议端点均可，保存即时生效、无需重启。
可选在「设置 → 文档解析」配百度云 OCR（PaddleOCR-VL）Key，用于扫描件整本解析。

### 方式三：浏览器开发模式（无 Tauri 壳）

```bash
cp sidecar/.env.example sidecar/.env    # 填 LLM_API_KEY 等（此模式下 Key 走 env）
npm run dev:browser                     # 同时拉起 sidecar(8765) + Vite，打开 http://localhost:5173
```

> 国内网络：pypi / npm / cargo 镜像已随仓库配好（`.npmrc`、`sidecar/pyproject.toml`、
> `src-tauri/.cargo/config.toml`），克隆后开箱可用。

## 目录结构

```
├── sidecar/            Python sidecar（FastAPI + DeepAgents）
│   ├── app/
│   │   ├── main.py     FastAPI 入口（鉴权/CORS/lifespan/日志）
│   │   ├── agent.py    build_agent + run 流（流式/断点重试/协作取消/HITL 续跑）
│   │   ├── events.py   agent 框架流 → SSE 事件契约的唯一映射层
│   │   ├── contracts/  契约单一事实源（pydantic 模型 → 生成前端 TS 类型）
│   │   ├── api/        tasks / conversations / runs / settings / sse / files /
│   │   │               workbench / artifacts / knowledge / materials / templates
│   │   ├── tools/      LLM 工具（parse_document / docx_ops / 检索 / 发布 / 校验…）
│   │   ├── parse/      确定性文档解析（docx/pdf/txt/md → md + outline + meta）
│   │   ├── knowledge/  知识库（FTS5 jieba 检索 / 入库管线）
│   │   └── skills/     SKILL.md 技能（document-parse / tender-analysis /
│   │                   tender-outline / tender-body / tender-qa）
│   └── data/           运行时生成（gitignore）：app.db / agent.db / workspace / logs
├── frontend/           React 19 + Vite + Tailwind（shadcn 风格手写组件）
├── src-tauri/          Tauri 2 壳（sidecar 生命周期 / 进程自愈 / commands）
├── website/            产品官网静态页（与应用代码独立，不进构建）
└── docs/               打包指引等工程文档
```

## 开发

- `./check.sh` — 提交前全量门禁：sidecar pytest + 前端 tsc / oxlint / build + Rust check / clippy。
- 打安装包与跨平台构建见 [docs/packaging.md](docs/packaging.md)（macOS / Windows / Linux）。
- `./dev.sh` — 交互式开发启动器（tauri / browser / sidecar / frontend / preview 五种模式）。
- 产品官网静态页在 [website/](website/)，本地打开 `index.html` 即可。
- 参与贡献前请先读 [AGENTS.md](AGENTS.md)（分层边界、契约演进与架构决策记录）。

## 许可（License）

本仓库以 **AGPL-3.0** 开源，全文见 [LICENSE](LICENSE)。

要点（与版权相关的场景，不是法律意见）：

- 整体仓库为 AGPL-3.0：复制、修改、再分发须以相同许可提供源码。`skills/` 中的
  方法论与提示词一并受此许可约束。
- 三方组件各有其许可：PDF 解析依赖 **PyMuPDF** 为 AGPL-3.0 或商业双许可，与仓库
  许可天然一致；`sidecar/app/skills/humanizer-zh` 为第三方 **MIT** 技能，其 LICENSE
  与署名声明随文件保留。
- 若需在 AGPL 之外获得商业授权（如闭源集成、SaaS 分发），请联系维护者另行洽谈。
