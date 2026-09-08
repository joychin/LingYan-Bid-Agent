"""端到端冒烟：spawn 真实 sidecar 子进程跑一轮对话，验证底座关键链路。

覆盖：run 完成、SSE 事件 seq 单调无重复、tool_call_id 无重复、消息落库、
trace 落库（durationMs）。需要 sidecar/.env 里有有效 LLM_API_KEY，否则 skip。

跑法：uv run pytest -m e2e（日常 `uv run pytest` 默认排除，保持秒级）。
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

SIDECAR_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SIDECAR_DIR / ".env"


def _load_env() -> dict[str, str]:
    """只取 LLM 相关配置，语义对齐 `uv run --env-file`（剥行内注释）。仓内 .env 的
    模板行都带 ` # 说明`：裸解析会把注释并进值——SIDECAR_TOKEN 变 truthy 开鉴权
    （冒烟全部 401）、LLM_BASE_URL 带中文注释拼进 URL（httpx header ascii 编码
    崩溃），2026-09-08 e2e 实测两连坑。SIDECAR_TOKEN/TENDER_HEALTHZ_NONCE 是
    Tauri 壳的鉴权 plumbing，被测 sidecar 一律不注入。"""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("SIDECAR_TOKEN", "TENDER_HEALTHZ_NONCE"):
                    continue
                env[k.strip()] = v.split(" #", 1)[0].strip()
    return env


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.e2e
def test_smoke_run_lifecycle(tmp_path):
    env = _load_env()
    api_key = env.get("LLM_API_KEY", "")
    if not api_key or api_key.startswith("sk-placeholder"):
        pytest.skip("sidecar/.env 无有效 LLM_API_KEY，跳过冒烟")

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--port", str(port)],
        cwd=str(SIDECAR_DIR),
        env={**os.environ, **env, "DATA_DIR": str(tmp_path)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        # 等 sidecar 就绪
        with httpx.Client(timeout=5) as c:
            for _ in range(30):
                try:
                    if c.get(f"{base}/api/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.5)
            else:
                pytest.fail("sidecar 30s 未就绪")

            tid = c.post(f"{base}/api/tasks", json={"title": "smoke 任务"}).json()["task"]["id"]
            cid = c.post(f"{base}/api/conversations", json={"task_id": tid, "title": "smoke"}).json()["id"]

            # 后台线程订阅 SSE，收集 (event, data)
            sse_events: list[tuple[str, dict]] = []
            stop = threading.Event()

            def _listen():
                try:
                    with c.stream("GET", f"{base}/api/conversations/{cid}/events", timeout=180) as r:
                        event = None
                        for line in r.iter_lines():
                            if stop.is_set():
                                break
                            if line.startswith("event: "):
                                event = line[7:]
                            elif line.startswith("data: ") and event and event != "ping":
                                try:
                                    sse_events.append((event, json.loads(line[6:])))
                                except ValueError:
                                    pass
                                event = None
                except httpx.HTTPError:
                    pass  # run 结束后由 stop 控制；读流异常不阻塞断言

            t = threading.Thread(target=_listen, daemon=True)
            t.start()

            c.post(
                f"{base}/api/conversations/{cid}/messages",
                json={"content": "只回答两个字：收到。不要调用任何工具。"},
            )

            # 轮询终态（真实 LLM 一轮，宽限 120s）
            status = None
            for _ in range(60):
                time.sleep(2)
                run = c.get(f"{base}/api/conversations/{cid}/runs/latest").json()["run"]
                status = run["status"]
                if status in ("completed", "error"):
                    break
            stop.set()
            assert status == "completed", f"run 终态 {status}：{run.get('error')}"

            # SSE 断言：seq 单调无重复；tool_call_id 无重复
            seqs = [d["seq"] for _, d in sse_events if isinstance(d.get("seq"), int)]
            assert seqs, "SSE 未收到任何带 seq 的事件"
            assert seqs == sorted(seqs), f"seq 非单调：{seqs}"
            assert len(set(seqs)) == len(seqs), f"seq 重复：{seqs}"
            call_ids = [
                d["tool_call_id"] for e, d in sse_events
                if e == "tool.called" and isinstance(d.get("tool_call_id"), str)
            ]
            assert len(set(call_ids)) == len(call_ids), f"tool_call_id 重复：{call_ids}"

            # 落库断言：assistant 消息 + trace（durationMs）
            msgs = c.get(f"{base}/api/conversations/{cid}/messages").json()["messages"]
            assistant = [m for m in msgs if m["role"] == "assistant"]
            assert assistant and "收到" in assistant[-1]["content"]
            assert isinstance(assistant[-1].get("durationMs"), int)
            assert assistant[-1]["durationMs"] > 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
