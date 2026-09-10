# Tender Agent — 本地标书 AI Agent 桌面客户端（MVP）

Local-first 桌面 AI Agent：Tauri 2 壳 + React 前端 + Python sidecar（DeepAgents）。
用户自带 LLM API Key（BYOK，默认 DeepSeek），支持多轮对话与 SKILL.md 技能自动调用，
领域方向为招投标标书（tender-analysis / tender-toc）。全程本地运行、无云端服务。
需求与验收详见 `tender-agent-mvp-prd.md`（本仓库唯一事实来源）。

## 架构

```
Tauri 2（Rust）
  窗口 · spawn/重启 sidecar · 钥匙串 · IPC（零业务逻辑）
    └─ React（webview）：Chat · 会话列表 · 工具时间线 · Settings
          │ HTTP + SSE（127.0.0.1:随机端口，Bearer token）
Python sidecar（FastAPI + uvicorn）
  /api/* REST + SSE 事件流（§5.5 契约）
  DeepAgents（skills + tools + SqliteSaver checkpointer）
  SQLite（data/app.db） + workspace（data/workspace/）
    └─ 用户自己的 LLM API（BYOK）
```

三条铁律（任何实现不得违反）：

1. Rust 不含任何业务逻辑。
2. **API Key 永不出现于 HTTP 请求/响应与前端 JS 内存**：key 由 Rust 从钥匙串读取，
   在 spawn sidecar 时通过环境变量注入。
   > 注：PRD §6.1 允许设置页在 webview 输入 API Key（经 IPC command 存钥匙串）。输入过程
   > 会瞬时存在于 JS state / IPC payload，但**不进入任何 HTTP 载荷**，保存后立即清空。
3. 前端只消费 PRD §5.5 定义的事件 schema，不依赖 DeepAgents 内部流格式。

## 目录结构

```
├── sidecar/            Python sidecar（FastAPI + DeepAgents）
│   ├── app/
│   │   ├── main.py     FastAPI 入口（--port；鉴权/CORS/lifespan；日志双写 stderr+文件）
│   │   ├── config.py   env+settings.json 双角色配置（llm/vlm）
│   │   ├── db.py       sqlite3：tasks/conversations/messages/runs/run_traces/artifact_index/kb（WAL）
│   │   ├── db_migrations.py  user_version 编号迁移（schema 变更在此追加）
│   │   ├── agent.py    build_agent + run_stream（实时发布事件/流式断点重试/协作取消）
│   │   ├── events.py   LangGraph 流 → §5.5 事件的唯一映射层 + run 边界 payload 构造
│   │   ├── contracts/  契约单一事实源（events/dto pydantic 模型 → 生成前端 TS 类型）
│   │   ├── bus.py      每会话 asyncio.Queue 订阅表
│   │   ├── api/        tasks/conversations/runs/settings/sse/files/artifacts/knowledge
│   │   ├── tools/      LLM 工具（parse_document/assemble_tender/publish/read/…）
│   │   ├── parse/      确定性解析注册表（docx/pdf/txt/md → md+outline+meta）
│   │   ├── knowledge/  公司资料库（FTS5 jieba 检索/入库管线）
│   │   └── skills/     document-parse + tender-analysis + tender-outline（SKILL.md）
│   ├── scripts/        gen_ts_types.py（契约 TS 类型生成）
│   └── data/           运行时生成（gitignore）：app.db / agent.db / workspace/ / logs/
├── frontend/           React 19 + Vite + Tailwind（shadcn 风格，手写组件）
│   └── src/            api(client/sse/events.gen/dto.gen) · hooks(含 runReducer+vitest) · components
├── src-tauri/          Tauri 2 壳（sidecar 生命周期 / 钥匙串 / commands）
│   ├── src/sidecar.rs  spawn·healthz·指数退避重启·进程树清理·双角色设置
│   └── src/lib.rs      commands：get_sidecar_info / get/set_model_settings / get_api_key_has_value / reveal_in_folder
└── tender-agent-mvp-prd.md
```

## 运行方式（三种）

前置：`uv`（Python ≥3.12）、Node ≥20、Rust stable ≥1.85（本机已用 rsproxy 镜像）。

```bash
# 1) 纯 sidecar（无前端无壳）
cd sidecar
uv sync
uv run --env-file .env python -m app.main --port 8765
# 另开终端：curl localhost:8765/api/healthz

# 2) 浏览器开发模式（sidecar 手动起在 8765）
npm run dev:browser        # 一条命令：同时拉起 8765 sidecar + Vite（Ctrl+C 一起退出）
# 或分开：cd sidecar && uv run --env-file .env python -m app.main --port 8765
#         cd frontend && npm run dev
# 连接地址在 frontend/.env.development 的 VITE_SIDECAR_URL

# 3) Tauri 桌面（推荐，一条命令）
npx tauri dev
# sidecar 由 Tauri 自动拉起（随机端口 + 随机 token），key 从钥匙串读取注入
```

首次使用前把 API Key 存进钥匙串（Mac 钥匙串 App / 终端）：

```bash
security add-generic-password -U -s tender-agent -a llm-api-key -w '<你的 key>'
# 或：窗口内「设置」→ 保存 API Key（仅 Tauri 环境显示该输入框）
security find-generic-password -s tender-agent   # 验证
```

## 网络镜像（本机直连超时，必配）

- **pypi**：`sidecar/pyproject.toml` 内置清华镜像。
- **npm**：根与 frontend 的 `.npmrc` 已配 `registry.npmmirror.com`。
- **cargo**：`src-tauri/.cargo/config.toml` 配 `rsproxy.cn` 镜像。
- **rustup**：`RUSTUP_DIST_SERVER=https://rsproxy.cn`（升级 Rust 时用）。

## 验收要点（对应 PRD 里程碑）

- M1：`curl` 走通 healthz / 会话 CRUD / SSE（started→token→tool→completed）；重启后历史仍在。
- M2：新建会话、流式打字、Markdown 表格、ToolTimeline、刷新后历史保留。
- M3：`npx tauri dev` 一条命令；`kill -9 <python pid>` 后 10 秒内自动恢复；钥匙串可查。
- M4：把 `招标文件.docx` 放入 `sidecar/data/workspace/`，窗口内让 tender-toc 走完整流水线，
  `data/workspace/out/` 生成 `tender-response-docs.json` / `tender-directory.json` / `tender-directory.html`。

## 已知坑（PRD §11，均已实现应对）

1. skills 路径两种写法（`skills/` vs 带 root 前缀）以启动日志实测为准（当前 `skills/` 可用）。
2. DeepAgents beta：库内部格式变化只改 `sidecar/app/events.py` 一个文件；deepagents 锁 0.7.7。
3. uvicorn 不要开 `--reload`（与 Tauri 进程树管理冲突）。
4. 解析支持 `.docx`（python-docx）与 `.pdf`（PyMuPDF 原生提取，无需 LibreOffice）；`.doc` 不支持（提示另存为 .docx）。
5. **钥匙串**：`keyring` crate 在此 macOS 写入 Data Protection 钥匙串、`security` CLI 不可见，
   故改为 Rust 调 `security` CLI 子进程读写 login 钥匙串（满足 PRD M3 验收）。
6. sse-starlette 对 dict 的 `data` 会输出 Python repr（单引号非 JSON）——sidecar 在
   `app/api/sse.py` 预先 `json.dumps`，保证 `data: <json>` 契约。

## 许可（License）

本仓库以 **GNU AGPL-3.0** 开源，全文见 [LICENSE](LICENSE)。

要点（与版权相关的场景，不是法律意见）：

- 整体仓库为 AGPL-3.0：复制、修改、再分发须以相同许可提供源码。本项目含
  `skills/` 中的方法论与提示词，一并受此许可约束。
- 三方组件各有其许可：其中 PDF 解析依赖 **PyMuPDF** 为 AGPL-3.0 或商业双许可，
  与仓库许可天然一致；`sidecar/app/skills/humanizer-zh` 为第三方 **MIT** 技能，
  其 LICENSE 与署名声明随文件保留。
- 若需在 AGPL 之外获得商业授权（如闭源集成、SaaS 分发），请联系维护者另行洽谈。
