# AGENTS.md

本仓库是 Tender Agent（智能标书 Agent 桌面客户端，local-first）的 monorepo。
给在本仓库工作的 coding agent 的约定。需求唯一事实来源：`tender-agent-mvp-prd.md`。

## 结构与分层（重要边界）

```
src-tauri/       Tauri 2 壳（Rust）：只做窗口、sidecar 进程管理、钥匙串、IPC command。零业务逻辑
frontend/        React 19 + Vite + Tailwind（shadcn 风格手写组件）；只通过 HTTP+SSE 与 sidecar 通信
sidecar/         Python sidecar（FastAPI + uvicorn），装配 DeepAgents
```

三条铁律：

1. Rust 不含任何业务逻辑。
2. API Key 永不出现于 HTTP 载荷与前端 JS 内存；key 由 Rust 从钥匙串读取，spawn 时注入 env。
3. 前端只消费 PRD §5.5 事件契约（agent.started / agent.token / tool.called / tool.result /
   agent.completed / agent.error / ping），不依赖 DeepAgents 内部格式。

## 命令

- `npm run dev`（= `npx tauri dev`）：一条命令（Tauri 拉起 sidecar + Vite + 窗口）。
- `npm run dev:browser`：浏览器模式一条命令（concurrently 拉起 sidecar + frontend，连 8765）。
- 纯 sidecar：`cd sidecar && uv sync && uv run --env-file .env python -m app.main --port 8765`。
- 前端：`cd frontend && npm run lint`（oxlint）、`npm run build`（`tsc -b && vite build`，含类型检查）。
- 未配置钥匙串 key 时 sidecar 仍可起，但 agent 调用会报「LLM_API_KEY 未设置」。
- sidecar 有 pytest（`uv run pytest`，覆盖 db 恢复 / 设置校验 / 工具路径 containment）；frontend/Rust 暂无测试 runner。

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
  - 新增工具：在 `app/tools/` 里 `@tool` + zod（或 docstring schema），并加入 `TOOLS`；
    领域事件由 server 装配的 eventSink 落库，工具不直接写 UI。
  - 工具输入路径必须落在 workspace 内（`tender_toc._resolve_path` 做 containment 校验），
    防止文档内容注入诱导模型读取工作区外敏感文件。
  - 启动时把崩溃残留的 `running` run 标记为 error（`db.recover_stale_runs`），
    否则 sidecar 被杀自动重启后该会话会永久 409 死锁。
  - base_url/model 单一真值在 `data/settings.json`（优先级 env > settings.json > 默认值）；
    HTTP PUT /settings 与 Tauri IPC `set_llm_settings` 都写它，Tauri 每次 spawn 前读它注入 env。
  - skills 从 `app/skills/` 启动时同步到 `data/workspace/skills/`（FilesystemBackend root）。
- **src-tauri**（Rust stable ≥1.85）：
  - `src/sidecar.rs`：选空闲端口 → 随机 token → spawn（`process_group(0)`）→ healthz(nonce 校验,1s×30) →
    指数退避重启（上限 3 次）→ 退出杀进程树并 wait 回收。base_url/model 单一真值在
    `data/settings.json`（HTTP PUT 与 IPC 都写它，spawn 前读取覆盖默认值）；
    `stopping` 标志保证应用退出后 supervisor 不再拉起孤儿进程。
  - 钥匙串用 macOS `security` CLI 子进程（`keyring` crate 在此 macOS 写 Data Protection 钥匙串，
    `security` CLI 不可见，无法满足 PRD M3 验收）。
- **frontend**：sidecar 地址解析在 `src/api/client.ts` 的 `getSidecarInfo()`——
  Tauri 环境走 `__TAURI_INTERNALS__.invoke('get_sidecar_info')`，浏览器回退
  `VITE_SIDECAR_URL` / `VITE_SIDECAR_TOKEN`。SSE 用 `@microsoft/fetch-event-source`。

## 已知事项

- 网络镜像必配：pypi=清华（pyproject 内置）、npm=npmmirror（.npmrc）、cargo=rsproxy
  （`src-tauri/.cargo/config.toml`）、rustup=`RUSTUP_DIST_SERVER=https://rsproxy.cn`。
- DeepAgents 锁 0.7.7（`deepagents==0.7.7`）；langgraph 由依赖解析（当前 1.0.5）。
- uvicorn 不要开 `--reload`（Tauri 进程树管理会乱）。
- `.doc/.pdf` 输入需 soffice；`.docx` 不需要。
