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
    # 启动纪律（2026-09-17 批次④）：lifespan 完成前 uvicorn 不 listen，Rust 探活
    # 窗口（dev 30s / bundled 60s）超时即杀进程——关键路径只留「不做就不可用」的
    # 步骤（库初始化/索引对账/状态恢复/记忆恢复/目录迁移），逐项 try/except 降级
    # （单个坏文件不再让整个 sidecar 起不来）；随库体积线性涨的 KB 重活后移到
    # yield 前注册的后台任务，healthz 提前秒级可达。
    from . import artifact_store

    try:
        # meta.json 是权威、索引与磁盘对账同步：幸存行保留运行态列
        # （content_seq/last_run_id 等，2026-09-12——复位会让产物卡回卷+编辑器误报）
        rebuilt = db.rebuild_artifact_index(
            artifact_store.list_from_disk(),
            lambda m: str(artifact_store.content_path(m["artifact_id"], m)),
        )
        if rebuilt:
            logger.info("artifact 索引已从 meta 重建：%d 个", rebuilt)
    except Exception:
        logger.exception("artifact 索引重建失败（本次不重建，下次启动重试）")
    for _name, _recover, _warn in (
        ("runs", db.recover_stale_runs, "启动时标记 %d 条崩溃残留的 running run 为 error"),
        ("kb", db.recover_stale_kb, "启动时标记 %d 条崩溃残留的知识库条目为 failed"),
        ("mt", db.recover_stale_mt, "启动时标记 %d 条崩溃残留的素材文件为 failed"),
    ):
        try:
            _recovered = _recover()
            if _recovered:
                logger.warning(_warn, _recovered)
        except Exception:
            logger.exception("启动状态恢复失败（%s，跳过本项）", _name)
    from .knowledge.autocheck import autocheck_sweep
    from .knowledge.ingest import migrate_parse_dir_layout as kb_migrate
    from .knowledge.ingest import rebuild_kb_index
    from .knowledge.materials_lib import migrate_parse_dir_layout as mt_migrate

    # 解析目录键迁移（2026-09-17 stem→文件名全名）：须在 autocheck/rebuild 之前
    # （两者按新路径读 md）；幂等，失败不阻断启动（旧布局的前缀产物仍可读，最坏
    # 退化=碰撞组维持共享现状，下次启动重试）
    try:
        kb_migrate()
        mt_migrate()
    except Exception:
        logger.exception("解析目录布局迁移失败（下次启动重试）")
    # agent.db checkpoint 安全清理（2026-09-13）：每 superstep 全量快照 + 子代理
    # 独立链让库平方级增长（实测 1.86GB）。此刻是独占写窗口——recover_stale_runs
    # 已把崩溃残留标为可续（清理侧自动排除这些会话）、recover_agent_memory 还没
    # 首建 saver 长连接。原则与实现见 app/checkpoint_prune.py 模块头（P0-P7）。
    # 只删行不 VACUUM（2026-09-17）：大库 VACUUM 全库重写分钟级、会顶穿探活窗口，
    # 延迟到下方后台任务做
    from .checkpoint_prune import prune_agent_db

    try:
        prune_agent_db(allow_vacuum=False)
    except Exception:
        logger.exception("agent.db checkpoint 清理失败（不影响启动，下次启动重试）")
    # checkpoint 是记忆真值，messages 表是恢复源：agent.db 丢失/损坏的会话在此重建记忆
    from .agent import recover_agent_memory

    await recover_agent_memory()
    _sync_skills()
    if not cfg.sidecar_token():
        logger.warning("SIDECAR_TOKEN 未设置：/api/* 将不要求鉴权（仅限本机开发，勿用于真实数据目录）")
    logger.info("sidecar ready: base_url=%s model=%s", cfg.llm_base_url(), cfg.llm_model())

    # ---- 后台延迟任务（yield 前注册、lifespan 让出事件循环后开跑） ----
    import asyncio

    from . import bg

    def _deferred_kb_maintenance() -> None:
        # KB 重活后移（原 yield 前串行）：存量锚点核对逐条读 md、检索段全量重建
        # 逐条重读 md + jieba 分词，成本随库体积线性涨。autocheck 在 rebuild 之前
        # （改库即被重建收口，顺序保持）；reindex 幂等，晚几秒只影响检索命中、
        # 不影响条目可见性
        try:
            autocheck_sweep()
        except Exception:
            logger.exception("存量锚点核对失败（下次启动重试）")
        try:
            _n = rebuild_kb_index()
            logger.info("KB 检索段后台重建完成：%d 条", _n)
        except Exception:
            logger.exception("KB 检索段重建失败（下次启动重试）")

    async def _deferred_vacuum() -> None:
        # VACUUM 出启动关键路径：先探体积（小库=常态与测试环境直接退出，不空等），
        # 大库等 2 分钟（避开冷启动高峰）且无活跃 run 才做；有 run 在跑就本次跳过
        # （探测+跳过，不排队不等待，下次启动再试）。saver 连接 timeout=120 兜
        # VACUUM 期新 run 首次 checkpoint 写的锁等待
        from .checkpoint_prune import vacuum_needed

        if not vacuum_needed():
            return
        await asyncio.sleep(120)
        if db.list_active_runs():
            logger.info("有活跃 run，本次跳过 agent.db VACUUM（下次启动重试）")
            return
        try:
            prune_agent_db()
        except Exception:
            logger.exception("agent.db 延迟 VACUUM 失败（下次启动重试）")

    _bg_tasks = [
        bg.spawn_background(asyncio.to_thread(_deferred_kb_maintenance)),
        bg.spawn_background(_deferred_vacuum()),
    ]

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
    # 收尾取消后台延迟任务（真 VACUUM 数十秒、不该撞上关停；取消经 await 落定，
    # 不留 pending 任务给事件循环）
    for t in _bg_tasks:
        t.cancel()
    if _bg_tasks:
        await asyncio.wait(_bg_tasks, timeout=5)
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
