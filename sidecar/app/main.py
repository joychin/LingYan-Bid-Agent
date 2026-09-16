"""FastAPI 入口。

- 只绑 127.0.0.1，SSE 推送
- 若设置了 SIDECAR_TOKEN，除 /api/healthz 外所有 /api/* 要求 Bearer token
- 启动时初始化数据库、同步 skills 到 workspace
- 支持 `uv run uvicorn app.main:app --port N` 或 `python -m app.main --port N`
"""

import argparse
import json
import logging
import os
import re
import shutil
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config as cfg
from . import db
from .api import (
    artifacts,
    conversations,
    files,
    knowledge,
    materials,
    render,
    runs,
    sse,
    tasks,
    templates,
    workbench,
)
from .api import settings as settings_api

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _setup_logging() -> None:
    """stderr 控制台 + 滚动文件双写。

    Tauri 模式下 sidecar 的 stdio 被置 null（Python 侧日志原本完全丢失），文件落盘是
    进程崩溃/异常退出时唯一的现场来源（data/logs/sidecar.log，5MB × 3 备份）。
    幂等守卫：`python -m app.main` 下模块会以 __main__ 与 app.main 两个名字各执行一次
    模块级代码（uvicorn 按 import string 再导入），无守卫会挂两个 file handler 双写。
    """
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    log_dir = cfg.data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "sidecar.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)


_setup_logging()
logger = logging.getLogger("sidecar")

VERSION = "0.1.0"

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://tauri.localhost",
    "tauri://localhost",
]
# 本地开发兜底：放行任意 localhost/127.0.0.1 端口（Vite 直连、端口回退等），
# 避免浏览器模式因为 origin 不在白名单而整段拦截 /api 与 SSE。
CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

# Origin 守卫（浏览器模式 CSRF 面）：跨站页面对 127.0.0.1 的「简单请求」POST
# （text/plain 免预检）可盲打 /api 状态变更端点。规则：带 Origin 且不在本机
# 白名单 → 403；无 Origin（TestClient/curl/Tauri webview 非浏览器 fetch）放行。
# 生产 Tauri 模式本就有 Bearer token，这里是浏览器开发模式的兜底闸。
_ALLOWED_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?$")
_ALLOWED_ORIGIN_EXACT = frozenset(CORS_ORIGINS)


def _sync_skills() -> None:
    """把 app/skills/ 幂等镜像同步到 data/workspace/skills/（FilesystemBackend 的 root）。

    copytree 只增不删——源里删掉的文件（如撤并的 shared-rules.md）会在目标侧留化石，
    故复制后清掉源里已不存在的文件与空目录。"""
    src = cfg.skills_source_dir()
    dst = cfg.workspace_dir() / "skills"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        for stale in sorted(dst.rglob("*"), reverse=True):
            rel = stale.relative_to(dst)
            if not (src / rel).exists():
                if stale.is_dir():
                    try:
                        stale.rmdir()  # 仅删空目录（reverse 保证先清子文件）
                    except OSError:
                        pass
                else:
                    stale.unlink()
        logger.info("skills 已同步到 %s", dst)
        for p in sorted(dst.glob("*/SKILL.md")):
            logger.info("  [skill] %s", p.relative_to(dst))
    else:
        logger.warning("未找到 skills 源目录 %s", src)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg.data_dir().mkdir(parents=True, exist_ok=True)
    # §16 任务分组目录：任务子目录（sources/work/_meta）按需创建，启动不预建
    db.init_db()
    # meta.json 是权威、索引与磁盘对账同步：幸存行保留运行态列
    # （content_seq/last_run_id 等，2026-09-12——复位会让产物卡回卷+编辑器误报），磁盘消失的行删除
    from . import artifact_store

    rebuilt = db.rebuild_artifact_index(
        artifact_store.list_from_disk(),
        lambda m: str(artifact_store.content_path(m["artifact_id"], m)),
    )
    if rebuilt:
        logger.info("artifact 索引已从 meta 重建：%d 个", rebuilt)
    recovered = db.recover_stale_runs()
    if recovered:
        logger.warning("启动时标记 %d 条崩溃残留的 running run 为 error", recovered)
    # 知识库：残留解析/抽取状态对账 + 检索段重建（磁盘 md 权威，对齐 artifact 索引语义）
    stale_kb = db.recover_stale_kb()
    if stale_kb:
        logger.warning("启动时标记 %d 条崩溃残留的知识库条目为 failed", stale_kb)
    stale_mt = db.recover_stale_mt()
    if stale_mt:
        logger.warning("启动时标记 %d 条崩溃残留的素材文件为 failed", stale_mt)
    from .knowledge.autocheck import autocheck_sweep
    from .knowledge.ingest import rebuild_kb_index

    # 存量待确认条目补跑锚点回文核对（在检索段全量重建之前，改库即被重建收口）
    autocheck_sweep()
    rebuild_kb_index()
    # agent.db checkpoint 安全清理（2026-09-13）：每 superstep 全量快照 + 子代理
    # 独立链让库平方级增长（实测 1.86GB）。此刻是独占写窗口——recover_stale_runs
    # 已把崩溃残留标为可续（清理侧自动排除这些会话）、recover_agent_memory 还没
    # 首建 saver 长连接。原则与实现见 app/checkpoint_prune.py 模块头（P0-P7）。
    from .checkpoint_prune import prune_agent_db

    try:
        prune_agent_db()
    except Exception:
        logger.exception("agent.db checkpoint 清理失败（不影响启动，下次启动重试）")
    # checkpoint 是记忆真值，messages 表是恢复源：agent.db 丢失/损坏的会话在此重建记忆
    from .agent import recover_agent_memory

    await recover_agent_memory()
    _sync_skills()
    if not cfg.sidecar_token():
        logger.warning("SIDECAR_TOKEN 未设置：/api/* 将不要求鉴权（仅限本机开发，勿用于真实数据目录）")
    logger.info("sidecar ready: base_url=%s model=%s", cfg.llm_base_url(), cfg.llm_model())
    # 孤儿清扫锚点（2026-09-12）：壳被强杀（kill -9/崩溃）时 Exit 钩子不执行，本进程
    # 可能残留为孤儿；下次启动 Rust 侧据本文件核身份后清扫（pid 已死/被复用则仅删
    # 陈旧文件）。优雅关停时删除；写失败不阻断启动（清不到只是退化为现状）。
    pidfile = cfg.data_dir() / "sidecar.pid"
    try:
        pidfile.write_text(
            json.dumps({"pid": os.getpid(), "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("sidecar.pid 写入失败（孤儿清扫将退化为不生效）", exc_info=True)
    yield
    try:
        pidfile.unlink(missing_ok=True)
    except OSError:
        pass


app = FastAPI(
    title="灵燕智能 Sidecar",
    version=VERSION,
    lifespan=lifespan,
    # 文档端点免鉴权暴露全 API 形状（/docs、/openapi.json 不在 /api 前缀下吃不到
    # token 中间件）——本地单机也无展示需求，直接关掉。
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # CORS 预检（OPTIONS）不带 Authorization，必须放行交给 CORSMiddleware 处理，
    # 否则带 Bearer 的跨源请求会因预检 401 而整体失败（浏览器报 "Load failed"）。
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path.startswith("/api"):
        origin = request.headers.get("Origin")
        if origin and origin not in _ALLOWED_ORIGIN_EXACT and not _ALLOWED_ORIGIN_RE.match(origin):
            return JSONResponse(status_code=403, content={"detail": "origin not allowed"})
    token = cfg.sidecar_token()
    if token and request.url.path.startswith("/api") and request.url.path != "/api/healthz":
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {token}":
            # 与 HTTPException 的 {"detail"} 信封统一（前端 request 层 detail ?? error 两读兼容）
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


@app.get("/api/healthz")
async def healthz():
    return {
        "status": "ok",
        "version": VERSION,
        # 实例标识：Tauri 探活校验此 nonce，防端口被其他本地服务占用时误判
        "nonce": os.environ.get("TENDER_HEALTHZ_NONCE", ""),
    }


app.include_router(tasks.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(sse.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(materials.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(workbench.router, prefix="/api")
app.include_router(render.router, prefix="/api")


def main() -> None:
    parser = argparse.ArgumentParser(description="灵燕智能 sidecar")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # log_config=None：uvicorn 不再自配 handler，其 error/access 日志传播到 root——
    # 与 app 日志共用同一格式（此前两套格式并存），access log 也随双写落盘。
    # （uvicorn CLI 直接拉起 app.main:app 时 CLI 会先自配 uvicorn logger，app 日志仍进文件。）
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info", log_config=None)


if __name__ == "__main__":
    main()
