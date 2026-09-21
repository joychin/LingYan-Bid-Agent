# -*- coding: utf-8 -*-
"""一键灌库：把 demo/assets 里的虚构材料灌进全新的演示数据目录。

用法（在 sidecar 目录下）：
    cd sidecar && uv run python ../demo/seed_demo.py [--fresh]

流程：
    1. 在 demo/demo-data 建全新数据目录（已存在则拒绝，--fresh 先清空）；
    2. 起临时 sidecar（DATA_DIR 指向演示目录、随机端口、无 token）；
    3. 从真实数据目录 sidecar/data/app.db 只读拷贝模型配置与 Key
       （本机复制、不打印、不外发；GET /settings 永不回读 Key）；
    4. 上传 7 份知识库材料 + 1 份素材库历史标书（招标文件不上传，
       留给录制时现场拖入任务）；
    5. 轮询等知识库 AI 抽取、素材库解析全部完成；
    6. 停进程。demo-data 即灌好（库内无绝对路径，目录可整体复用）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
SIDECAR_ROOT = REPO / "sidecar"
REAL_DB = SIDECAR_ROOT / "data" / "app.db"
ASSETS = REPO / "demo" / "assets"
DEMO_DATA = REPO / "demo" / "demo-data"

# 招标文件不上传（录制时现场拖入任务）；历史投标文件进素材库
TENDER_PREFIX = "云澜市一体化政务服务平台"
MATERIALS_MARK = "历史投标文件"

HEALTH_TIMEOUT_S = 90
INGEST_TIMEOUT_S = 20 * 60
POLL_INTERVAL_S = 5


def log(msg: str) -> None:
    print(msg, flush=True)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_real_settings() -> dict:
    """只读打开真实 app.db，取模型配置五键。WAL 库并发读安全。"""
    if not REAL_DB.is_file():
        raise SystemExit(f"未找到真实数据库：{REAL_DB}（请先在日常开发环境正常使用一次）")
    uri = f"file:{REAL_DB}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = dict(conn.execute("SELECT key, value FROM app_settings").fetchall())
    finally:
        conn.close()
    out: dict = {}
    for key in ("model_profiles", "default_model", "model_keys", "background_roles", "baidu_ocr"):
        raw = rows.get(key)
        if not raw:
            continue
        try:
            out[key] = json.loads(raw)
        except ValueError:
            log(f"警告：app_settings.{key} 不是合法 JSON，跳过")
    if not out.get("model_profiles") or not out.get("default_model"):
        raise SystemExit("真实库里没有模型配置（model_profiles/default_model 为空）——请先在应用设置里配好模型再跑本脚本")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="演示目录已存在时先清空重建")
    args = parser.parse_args()

    if DEMO_DATA.exists():
        if not args.fresh:
            raise SystemExit(f"演示目录已存在：{DEMO_DATA}\n确认不要可加 --fresh 重建（会重跑一遍 AI 抽取）")
        log("清空旧演示目录 …")
        shutil.rmtree(DEMO_DATA)

    settings = read_real_settings()
    profiles = settings["model_profiles"]
    keys: dict = settings.get("model_keys") or {}
    profile_ids = {p.get("id") for p in profiles}
    stale = sorted(k for k in keys if k not in profile_ids)
    if stale:
        log(f"忽略 {len(stale)} 个已删除模型的旧 Key 记录：{'、'.join(stale)}")
        keys = {k: v for k, v in keys.items() if k in profile_ids}
    roles = settings.get("background_roles") or {}
    log(f"从真实库读到 {len(profiles)} 个模型配置（Key 只复制不显示）")

    kb_files = sorted(
        p for p in ASSETS.glob("*.docx")
        if p.name.startswith("星灵创科") and MATERIALS_MARK not in p.name
    )
    mt_files = sorted(p for p in ASSETS.glob("*.docx") if MATERIALS_MARK in p.name)
    skipped = sorted(p for p in ASSETS.glob("*") if p not in kb_files and p not in mt_files)
    if not kb_files or not mt_files:
        raise SystemExit(f"demo/assets 里找不到知识库/素材库文件，先跑 gen_demo_docs.py（知识库 {len(kb_files)} 份、素材库 {len(mt_files)} 份）")
    log(f"待上传：知识库 {len(kb_files)} 份、素材库 {len(mt_files)} 份")
    for p in skipped:
        log(f"  不上传（录制时现场用）：{p.name}")

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if k not in ("SIDECAR_TOKEN", "TENDER_HEALTHZ_NONCE")}
    env["DATA_DIR"] = str(DEMO_DATA)
    log(f"起临时 sidecar（{base}，DATA_DIR={DEMO_DATA}）…")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--port", str(port)],
        cwd=SIDECAR_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    client = httpx.Client(base_url=base, timeout=30)
    try:
        deadline = time.time() + HEALTH_TIMEOUT_S
        while True:
            try:
                r = client.get("/api/healthz")
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None:
                raise SystemExit("临时 sidecar 启动即退出（看 data/logs/sidecar.log 排查）")
            if time.time() > deadline:
                raise SystemExit("临时 sidecar 健康检查超时")
            time.sleep(1)
        log("sidecar 就绪")

        # ---- 模型配置 + Key（先配置再上传，抽取才能用上模型）----
        r = client.put("/api/settings/models", json={
            "models": profiles,
            "default_model": settings["default_model"],
            **({"background_roles": roles} if roles else {}),
        })
        if r.status_code != 200:
            raise SystemExit(f"写模型配置失败 {r.status_code}：{r.text}")
        for model_id, api_key in keys.items():
            r = client.put("/api/settings/keys", json={"model_id": model_id, "api_key": api_key})
            if r.status_code != 200:
                raise SystemExit(f"写模型 Key 失败（{model_id}）{r.status_code}：{r.text}")
        baidu = settings.get("baidu_ocr") or {}
        if baidu.get("api_key") and baidu.get("secret_key"):
            client.put("/api/settings/ocr-keys", json=baidu)
        r = client.get("/api/settings")
        check = r.json()
        default_ok = any(
            m["id"] == check["default_model"] and m.get("key_configured")
            for m in check.get("models", [])
        )
        log(f"模型配置就绪：默认模型 {check['default_model']} key_configured={'是' if default_ok else '否'}")
        if not default_ok:
            raise SystemExit("默认模型没有可用 Key——请先在日常环境设置里配好 Key 再跑本脚本")

        # ---- 上传（模型可用性由随后的抽取轮询真验证）----
        kb_ids: dict[str, str] = {}
        for path in kb_files:
            with path.open("rb") as fh:
                r = client.post("/api/kb/files", files={"file": (path.name, fh)})
            if r.status_code != 201:
                raise SystemExit(f"知识库上传失败 {path.name} {r.status_code}：{r.text}")
            kb_ids[r.json()["file_name"]] = r.json()["id"]
            log(f"知识库已上传：{path.name}")
        mt_id = None
        for path in mt_files:
            with path.open("rb") as fh:
                r = client.post("/api/materials/files", files={"file": (path.name, fh)})
            if r.status_code != 201:
                raise SystemExit(f"素材库上传失败 {path.name} {r.status_code}：{r.text}")
            mt_id = r.json()["id"]
            log(f"素材库已上传：{path.name}")

        # ---- 轮询 ----
        log("等待知识库解析与 AI 抽取（几分钟，取决于模型速度）…")
        deadline = time.time() + INGEST_TIMEOUT_S
        while True:
            items = {it["file_name"]: it for it in client.get("/api/kb/items").json()["items"]}
            mt_status = client.get(f"/api/materials/files/{mt_id}/outline").json().get("parse_status")
            kb_states = {
                name: (items.get(name, {}).get("parse_status"), items.get(name, {}).get("extract_status"))
                for name in kb_ids
            }
            kb_done = all(
                st[0] == "ready" and st[1] in ("done", "failed", "skipped")
                for st in kb_states.values()
            )
            if kb_done and mt_status == "ready":
                break
            if time.time() > deadline:
                pending = {k: v for k, v in kb_states.items() if v not in (("ready", "done"), ("ready", "failed"), ("ready", "skipped"))}
                raise SystemExit(f"等待超时：知识库 {pending} / 素材库 {mt_status}")
            line = "，".join(f"{n.removesuffix('.docx')}={s[0]}/{s[1]}" for n, s in kb_states.items())
            log(f"  进度：{line}；素材库={mt_status}")
            time.sleep(POLL_INTERVAL_S)

        # ---- 汇总 ----
        items = client.get("/api/kb/items").json()["items"]
        confirmed = sum(1 for it in items if it["review_status"] == "confirmed")
        pending = sum(1 for it in items if it["review_status"] == "pending_review")
        failed = [it["file_name"] for it in items if it["extract_status"] == "failed"]
        log("")
        log(f"知识库 {len(items)} 条：自动确认 {confirmed} 条、待人工确认 {pending} 条"
            + (f"、抽取失败 {failed}" if failed else ""))
        for it in items:
            log(f"  {it['file_name']}：{it['doc_type_name']}（{it['capability']}，{it['review_status']}）")
        log(f"素材库解析完成（{len(mt_files)} 份，块待录制时现场勾选）")
        log("")
        log(f"灌库完成 → {DEMO_DATA}")
        log("下一步：./demo/record_env.sh on 换入演示数据，然后 npm run dev 录制")
        return 0
    finally:
        client.close()
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                log("警告：临时 sidecar 被强杀，建议重跑一遍确认数据完整")


if __name__ == "__main__":
    sys.exit(main())
