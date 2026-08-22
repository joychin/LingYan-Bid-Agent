"""FastAPI 入口。

- 只绑 127.0.0.1，SSE 推送
- 若设置了 SIDECAR_TOKEN，除 /api/healthz 外所有 /api/* 要求 Bearer token
- 启动时初始化数据库、同步 skills 到 workspace
- 支持 `uv run uvicorn app.main:app --port N` 或 `python -m app.main --port N`
"""

import argparse
import logging
import os
import shutil
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config as cfg
from . import db
from .api import conversations, settings as settings_api, sse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sidecar")

VERSION = "0.1.0"

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://tauri.localhost",
    "tauri://localhost",
]


def _sync_skills() -> None:
    """把 app/skills/ 幂等同步到 data/workspace/skills/（FilesystemBackend 的 root）。"""
    src = cfg.skills_source_dir()
    dst = cfg.workspace_dir() / "skills"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        logger.info("skills 已同步到 %s", dst)
        for p in sorted(dst.glob("*/SKILL.md")):
            logger.info("  [skill] %s", p.relative_to(dst))
    else:
        logger.warning("未找到 skills 源目录 %s", src)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg.data_dir().mkdir(parents=True, exist_ok=True)
    (cfg.workspace_dir() / "out").mkdir(parents=True, exist_ok=True)
    db.init_db()
    recovered = db.recover_stale_runs()
    if recovered:
        logger.warning("启动时标记 %d 条崩溃残留的 running run 为 error", recovered)
    _sync_skills()
    if not cfg.sidecar_token():
        logger.warning("SIDECAR_TOKEN 未设置：/api/* 将不要求鉴权（仅限本机开发，勿用于真实数据目录）")
    logger.info("sidecar ready: base_url=%s model=%s", cfg.llm_base_url(), cfg.llm_model())
    yield


app = FastAPI(title="Tender Agent Sidecar", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    token = cfg.sidecar_token()
    if token and request.url.path.startswith("/api") and request.url.path != "/api/healthz":
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {token}":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)


@app.get("/api/healthz")
async def healthz():
    return {
        "status": "ok",
        "version": VERSION,
        # 实例标识：Tauri 探活校验此 nonce，防端口被其他本地服务占用时误判
        "nonce": os.environ.get("TENDER_HEALTHZ_NONCE", ""),
    }


app.include_router(conversations.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(sse.router, prefix="/api")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tender Agent sidecar")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
