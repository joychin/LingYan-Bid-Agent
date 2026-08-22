# 智能标书 Agent 桌面客户端 — MVP PRD（AI 编码代理执行版）

> **给执行者的说明**：本文档是唯一事实来源。技术选型已锁定，**不要更换框架、不要引入本文未列出的依赖、不要自行增加功能**。按里程碑顺序执行（M1→M4），每个里程碑完成后运行其验收命令并确认通过，再进入下一个。遇到库 API 与本文不符时，查官方文档（docs.langchain.com/oss/python/deepagents）而不是猜测。

---

## 1. 产品概述

**一句话定位**：一个 Local-first 的桌面 AI Agent 客户端（Tauri + React + Python sidecar），用户自带 LLM API Key（BYOK），支持多轮对话和 SKILL.md 技能自动调用，领域方向为招投标标书（本 MVP 只验证底座，不做标书业务界面）。

**MVP 唯一目标**：在桌面窗口里，用户能和 Agent 对话，Agent 能按需自动加载 skills（含真实的 tender-toc 解析流水线），全程本地运行、无任何云端服务。

## 2. 范围

### 2.1 做

- 聊天界面：流式打字输出、Markdown 渲染、左侧会话列表
- Skill 自动触发：用户消息 → Agent 自主决定调用哪个 skill（渐进式披露）
- 工具调用时间线：UI 显示"正在调用 convert_tender…"等工具状态
- Settings：Provider / Base URL / Model 配置；API Key 存 OS 钥匙串
- 会话持久化：重启后历史还在
- sidecar 崩溃自动重启

### 2.2 明确不做（禁止实现）

- ❌ 审批/中断 UI（HumanInTheLoop 界面化）
- ❌ 断点续传、崩溃恢复 UI
- ❌ Artifact 管理界面（产物文件在文件系统里自己看）
- ❌ 多工作区/项目管理、用户登录、云同步、多 Agent、RAG、MCP
- ❌ 打包冻结与安装包分发（开发期直接 `uv venv` + `tauri dev` 运行）
- ❌ WebSocket（一律 SSE）

## 3. 技术选型（锁定）

| 层 | 选型 | 约束 |
|---|---|---|
| 桌面壳 | Tauri 2 | Rust 只做：窗口、sidecar 进程管理、钥匙串、IPC command。**零业务逻辑** |
| 前端 | React 18 + TypeScript + Vite + shadcn/ui + Tailwind CSS | 状态用 TanStack Query |
| 桥 | Python 3.12+ / FastAPI / uvicorn | 只绑 127.0.0.1，SSE 推送 |
| Agent harness | `deepagents`（DeepAgents SDK） | 用法见 §5.6（已验证代码，直接抄） |
| LLM | `langchain-openai` 的 ChatOpenAI | BYOK，任意 OpenAI 兼容端点 |
| 持久化 | SQLite（标准库 sqlite3 即可，不引 ORM） | 两个库文件，见 §5.7 |
| SSE 客户端 | `@microsoft/fetch-event-source` | 支持自定义 header |
| 钥匙串 | Rust `keyring` crate | service=`tender-agent`，account=`llm-api-key` |

**禁止引入**：LangChain 手写 Graph、LangServe、PostgreSQL、Redis、Docker、LangGraph 之外的工作流引擎、任何 npm/py 依赖白名单之外的东西（前端另加：react-markdown、@tanstack/react-query、lucide-react）。

## 4. 系统架构

```text
┌─────────────────────────────────────────────┐
│ Tauri 2（Rust）                              │
│  窗口 · spawn/重启 sidecar · keychain · IPC  │
│  ┌───────────────────────────────────────┐  │
│  │ React（webview）                      │  │
│  │  Chat · 会话列表 · 时间线 · Settings  │  │
│  └──────────────┬────────────────────────┘  │
└─────────────────┼───────────────────────────┘
                  │ HTTP + SSE（127.0.0.1:PORT，Bearer token）
┌─────────────────▼───────────────────────────┐
│ Python sidecar（FastAPI + uvicorn）         │
│  /api/conversations… · SSE 事件流           │
│  DeepAgents（skills + tools + checkpointer）│
│  SQLite（会话/消息） + 文件系统（workspace） │
└─────────────────┬───────────────────────────┘
                  │ 用户自己的 LLM API（BYOK）
```

**三条铁律（任何实现不得违反）**：
1. Rust 不含任何业务逻辑。
2. **API Key 永远不出现在 HTTP 请求/响应和前端 JS 内存中**。Key 由 Rust 从钥匙串读取，在 spawn sidecar 时通过环境变量注入。
3. 前端只消费本 PRD §5.5 定义的事件 schema，**不得**直接依赖 LangGraph/DeepAgents 的内部流格式。

## 5. Sidecar 规格（Python）

### 5.1 目录结构

```text
sidecar/
├── pyproject.toml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI 入口；接受 --port 参数
│   ├── config.py        # 读环境变量
│   ├── db.py            # data/app.db：conversations / messages / runs
│   ├── agent.py         # DeepAgents 封装（build_agent / run_stream）
│   ├── events.py        # 事件定义 + LangGraph 流 → 事件映射
│   ├── bus.py           # 每会话的内存事件订阅（asyncio.Queue 列表）
│   ├── api/
│   │   ├── conversations.py
│   │   ├── settings.py
│   │   └── sse.py
│   ├── tools/
│   │   └── tender_toc.py   # 三个 @tool（见 §8）
│   └── skills/
│       ├── tender-analysis/SKILL.md
│       └── tender-toc/{SKILL.md, references/prompts.md, scripts/parse_toc.py}
└── data/                # 运行时生成（gitignore）：app.db / agent.db / workspace/ / out/
```

### 5.2 依赖（pyproject.toml）

```toml
[project]
name = "tender-agent-sidecar"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "deepagents",
    "langchain-openai",
    "langgraph",
    "langgraph-checkpoint-sqlite",
    "python-docx",
    "fastapi",
    "uvicorn",
    "pydantic",
    "sse-starlette",
]

# 国内网络必须（pypi.org 直连会 TLS 超时）
[[tool.uv.index]]
url = "https://pypi.tuna.tsinghua.edu.cn/simple"
default = true
```

### 5.3 环境变量（.env.example）

```bash
LLM_API_KEY=sk-...                          # Rust spawn 时注入；手动开发时自己 export
LLM_BASE_URL=https://api.deepseek.com/v1    # 默认 DeepSeek
LLM_MODEL=deepseek-v4-flash
SIDECAR_TOKEN=                              # 随机 token；设置后所有 /api/* 必须带 Bearer
DATA_DIR=                                   # 数据目录，默认 ./data
```

`PUT /api/settings` 修改 provider/base_url/model 后立即生效（重建 agent 实例）；**LLM_API_KEY 不接受 HTTP 修改**，只能通过环境变量（即只能由 Tauri 侧修改钥匙串后重启 sidecar）。

### 5.4 REST API 契约

统一前缀 `/api`，响应均为 JSON。鉴权：若设置了 `SIDECAR_TOKEN`，除 `/api/healthz` 外全部要求 `Authorization: Bearer <token>`，失败返回 401。CORS 允许来源：`http://localhost:5173`、`http://tauri.localhost`、`tauri://localhost`。

```http
GET /api/healthz
→ 200 {"status":"ok","version":"0.1.0"}

GET /api/conversations
→ 200 {"conversations":[{"id":"c_xxx","title":"新对话","created_at":"2026-08-22T21:00:00"}]}

POST /api/conversations        body: {"title": "可选，默认"新对话""}
→ 201 {"id":"c_xxx","title":"新对话","created_at":"..."}

GET /api/conversations/{id}/messages
→ 200 {"messages":[{"id":"m_xxx","role":"user|assistant","content":"...","created_at":"..."}]}
    （按时间升序；只含最终落盘的完整消息，不含流式中间态）

POST /api/conversations/{id}/messages    body: {"content":"用户消息"}
→ 202 {"message_id":"m_xxx","run_id":"r_xxx"}
   副作用：user 消息落库 → 创建 run(status=running) → 后台任务驱动 agent 流式执行
→ 409 {"error":"该会话已有进行中的任务"}   （同一会话同时只允许一个 run）
→ 404 会话不存在

GET /api/conversations/{id}/events       （SSE，见 §5.5）
→ text/event-stream

GET /api/settings
→ 200 {"base_url":"https://api.deepseek.com/v1","model":"deepseek-v4-flash"}

PUT /api/settings      body: {"base_url":"...","model":"..."}
→ 200 {"ok":true}     （不含 key 字段；key 走钥匙串，见铁律 2）
```

### 5.5 SSE 事件契约（前端唯一消费格式）

每条消息格式：`event: <type>` + `data: <json>`。前端重连策略：重新 `GET messages` 拉全量 + 重新订阅（MVP 不做 Last-Event-ID 补发）。每 15 秒发一次 `event: ping` 心跳。

```jsonl
event: agent.started    data: {"run_id":"r_xxx","conversation_id":"c_xxx"}
event: agent.token      data: {"run_id":"r_xxx","text":"流式文本片段"}
event: tool.called      data: {"run_id":"r_xxx","tool":"convert_tender","args":{"docx_path":"招标文件.docx"}}
event: tool.result      data: {"run_id":"r_xxx","tool":"convert_tender","summary":"OK\n已生成 out/tender-full.md"}
event: agent.completed  data: {"run_id":"r_xxx","message_id":"m_yyy"}
event: agent.error      data: {"run_id":"r_xxx","error":"错误描述"}
```

### 5.6 DeepAgents 集成（已验证代码，照抄后改造）

以下 API 已在真实环境跑通（Python 3.12，DeepAgents 当前版本）：

```python
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
# 生产用 SqliteSaver：
# from langgraph.checkpoint.sqlite import SqliteSaver
# checkpointer = SqliteSaver.from_conn_string(str(DATA_DIR / "agent.db"))

model = ChatOpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    model=os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
    timeout=180,
)

agent = create_deep_agent(
    model=model,
    backend=FilesystemBackend(root_dir=str(WORKSPACE_DIR)),   # 根 = data/workspace/
    tools=[convert_tender, extract_toc, build_tender],        # 见 §8
    skills=["skills/"],      # 相对 backend root；若启动日志显示未加载，改 ["./sidecar/skills/"]
    system_prompt=(
        "你是标书助理。方法论在 skills 目录中：标书分析用 tender-analysis 技能；"
        "解析招标文件生成投标目录用 tender-toc 技能（按其 SKILL.md 与 references/prompts.md 执行，"
        "脚本步骤用提供的工具，不要自己编命令）。"
    ),
    checkpointer=checkpointer,
)

# 多轮对话：每会话一个固定 thread_id（= conversation id），每次只传新消息
result = agent.invoke(
    {"messages": [("user", "你好")]},
    config={"configurable": {"thread_id": "c_xxx"}},
)

# 流式：用 agent.stream(..., stream_mode=["messages","updates"]) 驱动事件
# 映射要求（以 §5.5 契约为准，LangGraph 内部格式不外泄）：
#   AIMessageChunk 的增量文本  → agent.token
#   updates 中的 tool_calls    → tool.called
#   工具执行返回               → tool.result
#   结束                       → agent.completed（assistant 完整消息落库 messages 表）
```

**注意**：DeepAgents 处于 beta，若签名有出入以官方文档为准，但 §5.5 事件契约不可变。

### 5.7 SQLite（`data/app.db`，标准库 sqlite3，WAL 模式）

```sql
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','error')),
  error TEXT, created_at TEXT NOT NULL);
```

DeepAgents 的 checkpointer 用独立文件 `data/agent.db`，与 app.db 分离，避免锁竞争。

## 6. 前端规格（React）

### 6.1 结构与页面

```text
frontend/src/
├── api/client.ts        # fetch 封装（baseURL、Bearer token）
├── api/sse.ts           # fetch-event-source 封装
├── hooks/useConversations.ts / useMessages.ts / useRun.ts
├── components/
│   ├── Sidebar.tsx          # 会话列表 + 新建按钮 + Settings 入口
│   ├── ChatView.tsx         # 消息流 + 输入框
│   ├── ChatMessage.tsx      # user/assistant 气泡，react-markdown 渲染
│   ├── ToolTimeline.tsx     # 当前 run 的工具调用条（spinner→✓，可折叠看 summary）
│   └── SettingsDialog.tsx   # base_url/model 表单（PUT /api/settings）；
│                            # API Key 输入框仅当运行在 Tauri 时显示（调 command 存钥匙串）
└── App.tsx
```

### 6.2 数据流

- 会话/消息列表：TanStack Query，`queryKey: ['conversations']` / `['messages', convId]`
- 发送消息：`POST …/messages` 成功后本地追加 user 消息，并订阅该会话 SSE
- SSE：`agent.token` 累积到"正在生成"的 assistant 气泡；`tool.called/tool.result` 驱动 ToolTimeline；`agent.completed` → `invalidateQueries(['messages', convId])` 拉取落盘真值
- sidecar 地址与 token：优先从 Tauri command `get_sidecar_info()` 获取；浏览器开发模式回退 `VITE_SIDECAR_URL` / `VITE_SIDECAR_TOKEN` 环境变量

### 6.3 UI 基调

shadcn/ui + Tailwind，浅色主题，工作台布局：左侧 240px 会话栏，右侧聊天区；顶部窄条放标题与设置齿轮。不设计复杂视觉，组件用默认样式微调即可。

## 7. Tauri 壳规格（Rust）

### 7.1 职责（仅此而已）

1. **sidecar 生命周期**：启动时选空闲端口（`TcpListener::bind("127.0.0.1:0")` 后立刻 drop 取端口）→ 生成随机 token（uuid）→ `Command::new(sidecar_python)` spawn，参数 `app.main:app --port <N>`（`--port` 传给 uvicorn），环境变量注入 `SIDECAR_TOKEN / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL` → 轮询 `/api/healthz`（1s 间隔，最多 30 次）→ 失败则 kill 后指数退避重启（上限 3 次，之后向前端发错误事件）
2. **退出清理**：app 退出时杀整个进程树（macOS/Linux：kill 进程组，spawn 时用 `process_group(0)`；Windows：`taskkill /T /F /PID`）
3. **commands**：`get_sidecar_info() -> {port, token}`；`get_llm_settings()/set_llm_settings(base_url, model, api_key)`（api_key 写钥匙串，写完后自动重启 sidecar 使其生效）；`get_api_key_has_value() -> bool`（只返回布尔，永不返回 key 本体）
4. 窗口：1200×800，标题「Tender Agent」

### 7.2 配置要点

- `tauri.conf.json`：devUrl `http://localhost:5173`，frontendDist `../frontend/dist`
- 依赖 crate：`tauri`、`tauri-plugin-shell`（可选）、`keyring`、`uuid`、`reqwest`（healthz 用）
- sidecar python 路径解析：开发期 `../sidecar/.venv/bin/python`（Windows 为 `python.exe`）；工作目录设为 `../sidecar/`

## 8. 现有资产迁移（已存在的代码，直接复制）

源目录：`/Users/chenzhuo/Documents/WorkBuddy/2026-08-22-20-04-15/deepagents-demo/`

1. `skills/` 整目录（tender-analysis + tender-toc）→ `sidecar/app/skills/`
2. `demo.py` 中的三个工具函数（`convert_tender / extract_toc / build_tender` 及 `_run_script / _resolve_path` 辅助函数）→ `sidecar/app/tools/tender_toc.py`，改造点：
   - `TOC_SCRIPT` / `OUTDIR` 路径改为 `data/workspace/skills/tender-toc/scripts/parse_toc.py` 与 `data/workspace/out/`（skills 目录放进 workspace，使 FilesystemBackend 能读到 SKILL.md 与 references）
   - `PROJECT_ROOT` 引用改为 workspace 根
3. `parse_toc.py` 的 CLI 契约（已验证）：`convert <docx> --outdir <dir>`、`file <docx> --outdir <dir>`、`build --outdir <dir>`

## 9. 里程碑与验收

### M1 — Sidecar 独立跑通（无前端无壳）

```bash
cd sidecar && uv sync
export LLM_API_KEY=sk-... LLM_MODEL=deepseek-v4-flash
uv run uvicorn app.main:app --port 8765
# 验收（另开终端）：
curl -s localhost:8765/api/healthz                       # {"status":"ok",...}
curl -s -X POST localhost:8765/api/conversations        # 返回会话 id
curl -s -X POST localhost:8765/api/conversations/<id>/messages \
     -H 'Content-Type: application/json' \
     -d '{"content":"分析评分办法：技术方案40分、商务报价30分、资质业绩20分、售后服务10分；ISO9001与近三年2个同类业绩为废标项"}'
curl -N localhost:8765/api/conversations/<id>/events    # 依次看到 agent.started → agent.token… → agent.completed
# 通过标准：SSE 事件符合 §5.5；assistant 回复含 tender-analysis skill 的表格与末行标记；
#          messages 表有完整落盘；重启 sidecar 后 GET messages 历史仍在（checkpointer 用 agent.db）
```

### M2 — React 聊天 UI（浏览器开发模式，无 Tauri）

```bash
cd frontend && npm install && npm run dev       # vite 5173，sidecar 手动跑在 8765
# .env.development: VITE_SIDECAR_URL=http://127.0.0.1:8765
# 通过标准：能新建会话、流式打字、Markdown 表格正常渲染、
#          触发 skill 时 ToolTimeline 显示工具调用、刷新页面历史仍在
```

### M3 — Tauri 壳

```bash
npm install -D @tauri-apps/cli && npx tauri init && npx tauri dev
# 通过标准：
# 1. 窗口内聊天全流程正常（sidecar 由 Tauri 拉起）
# 2. Settings 里保存 API Key 后 sidecar 自动重启且新 key 生效
# 3. `security find-generic-password -s tender-agent` 能查到钥匙串条目（macOS）
# 4. kill -9 <python pid> 后 UI 显示"重连中"，sidecar 自动重启、会话历史无损
```

### M4 — 端到端 tender-toc（真实资产）

```bash
# 把一份中小型招标文件 .docx 放入 sidecar/data/workspace/
# 窗口内发送：「请使用 tender-toc 技能，对 招标文件.docx 做完整分析，最后组装 JSON」
# 通过标准：时间线先后出现 convert_tender、build_tender；
#          sidecar/data/workspace/out/ 生成 tender-response-docs.json、
#          tender-directory.json、tender-directory.html（浏览器打开结构完好）
```

## 10. 全局验收（MVP 完成定义）

1. `npx tauri dev` 一条命令进入可用产品；全程无云端依赖
2. 对话 + tender-analysis + tender-toc 三个场景在 UI 内跑通
3. 三条铁律复核：Rust 无业务逻辑 / key 不出现在任何 HTTP 载荷与前端内存 / 前端仅消费 §5.5 事件
4. sidecar 被杀后 10 秒内自动恢复，历史不丢

## 11. 已知坑（务必写进实现）

1. **网络**：本机 pypi 直连会 TLS 超时，pyproject 已含清华镜像；npm 需要 `.npmrc`：`registry=https://registry.npmmirror.com`
2. **Python ≥3.12** 是 deepagents 硬要求；用 uv 管理
3. **skills 路径**两种写法（`["skills/"]` vs 带 root 前缀）官方文档自相矛盾，启动时打日志确认已加载，未加载即换写法
4. `.doc/.pdf` 输入需要 soffice（本机已装）；`.docx` 不需要
5. DeepAgents beta：以事件契约为锚，库内部格式变化只改 `events.py` 一个文件
6. uvicorn 不要开 `--reload` 与 Tauri spawn 同时使用（进程树管理会乱）

## 12. 项目根目录约定

在执行目录下创建 `tender-agent/`，内含 `frontend/`、`src-tauri/`、`sidecar/`、`README.md`（含运行方式）、`.gitignore`（node_modules、.venv、data/、target/）。
