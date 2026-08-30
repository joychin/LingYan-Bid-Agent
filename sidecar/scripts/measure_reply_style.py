"""回复风格 A/B 测量（2026-08-29 排版规范改动的效果验证）。

spawn 隔离 sidecar（独立端口 + 独立 DATA_DIR，复用 test_smoke_e2e 的模式），
对固定探针消息各跑 N 轮真实 LLM 对话，统计最终回复的篇幅/结构密度/
泄漏率/语气指标，打印汇总表并落 JSON（含原始回复文本）供改前/改后对比。

用法（sidecar 目录下）：
  uv run python scripts/measure_reply_style.py --label baseline
  uv run python scripts/measure_reply_style.py --label after
无有效 LLM_API_KEY 时退出码 2。探针均为无文件短消息，不触发解析流水线。
"""

import argparse
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

SIDECAR_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SIDECAR_DIR / ".env"

PROBES = [
    "你都能做什么？",
    "现在这个任务进度到哪了？",
    "公司知识库里能存哪些类型的资料？",
]

REPEATS = 3
POLL_SECONDS = 90

LEAK_SUBSTR = [
    "files/", "out/", "drafts/", "formal/", "threads/",
    "sources.json", "meta.json", "outline.json",
    "parse_document", "document-parse", "tender-analysis", "tender-outline",
    "assemble_tender", "skill", "artifact", "checkpoint", "manifest",
    "run_traces", "propose_promotion", "doc.note", "子代理",
]
LEAK_WORD_RE = re.compile(r"\brun\b", re.IGNORECASE)
LEAK_CODE_RE = re.compile(r"\bR[12]\b")  # 内部阶段代号（R1/R2）不该出现在用户回复
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
GREET_RE = re.compile(r"^\s*(好的|当然|没问题|收到|明白了|了解|OK|Ok|嗯+|哈喽|您好|你好)[,，!！。~]")


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def metrics(text: str) -> dict:
    lines = text.splitlines()
    return {
        "chars": len(text),
        "heading": bool(re.search(r"^#{1,6}\s", text, re.M)),
        "list": bool(re.search(r"^\s*([-*+]|\d+[.、)]\s)", text, re.M)),
        "table": any("|" in ln for ln in lines)
        and bool(re.search(r"^\s*\|?[\s:|-]*-[\s:|-]*\|", text, re.M)),
        "leak": (
            any(w in text for w in LEAK_SUBSTR)
            or bool(LEAK_WORD_RE.search(text))
            or bool(LEAK_CODE_RE.search(text))
        ),
        "emoji": bool(EMOJI_RE.search(text)),
        "greeting": bool(GREET_RE.match(text)),
    }


def one_reply(client: httpx.Client, base: str, content: str) -> str:
    tid = client.post(f"{base}/api/tasks", json={"title": "风格测量"}).json()["task"]["id"]
    cid = client.post(
        f"{base}/api/conversations", json={"task_id": tid, "title": "风格测量"}
    ).json()["id"]
    client.post(f"{base}/api/conversations/{cid}/messages", json={"content": content})
    for _ in range(POLL_SECONDS // 2):
        time.sleep(2)
        run = client.get(f"{base}/api/conversations/{cid}/runs/latest").json()["run"]
        if run["status"] in ("completed", "error"):
            if run["status"] != "completed":
                raise RuntimeError(f"run 失败：{run.get('error')}")
            break
    else:
        raise RuntimeError(f"{POLL_SECONDS}s 内 run 未完成")
    msgs = client.get(f"{base}/api/conversations/{cid}/messages").json()["messages"]
    assistant = [m for m in msgs if m["role"] == "assistant"]
    if not assistant:
        raise RuntimeError("无 assistant 消息")
    return assistant[-1]["content"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="baseline / after 等标记")
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--probe", help="只跑匹配该子串的探针（如「进度」）")
    args = ap.parse_args()

    probes = [p for p in PROBES if not args.probe or args.probe in p]

    env = _load_env()
    api_key = env.get("LLM_API_KEY", "")
    if not api_key or api_key.startswith("sk-placeholder"):
        print("sidecar/.env 无有效 LLM_API_KEY，无法测量", file=sys.stderr)
        return 2

    port = _free_port()
    data_dir = tempfile.mkdtemp(prefix=f"reply_style_{args.label}_")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--port", str(port)],
        cwd=str(SIDECAR_DIR),
        env={**os.environ, **env, "DATA_DIR": data_dir},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    records: list[dict] = []
    try:
        with httpx.Client(timeout=30) as client:
            for _ in range(30):
                try:
                    if client.get(f"{base}/api/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.5)
            else:
                print("sidecar 30s 未就绪", file=sys.stderr)
                return 2

            for probe in probes:
                for i in range(args.repeats):
                    try:
                        reply = one_reply(client, base, probe)
                        m = metrics(reply)
                        records.append({"probe": probe, "reply": reply, **m})
                        flags = " ".join(
                            f"{k}={'Y' if m[k] else 'n'}" for k in
                            ("heading", "list", "table", "leak", "emoji", "greeting")
                        )
                        print(f"[{probe} #{i + 1}] chars={m['chars']} {flags}")
                    except RuntimeError as e:
                        records.append({"probe": probe, "error": str(e)})
                        print(f"[{probe} #{i + 1}] ERROR: {e}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    ok = [r for r in records if "reply" in r]
    print(f"\n== {args.label} 汇总（{len(ok)}/{len(records)} 成功）==")
    if ok:
        print(f"字数中位 {statistics.median(r['chars'] for r in ok):.0f}")
        for k in ("heading", "list", "table", "leak", "emoji", "greeting"):
            rate = sum(1 for r in ok if r[k]) / len(ok)
            print(f"{k:9s} {rate:.0%}")

    out = SIDECAR_DIR / "scripts" / f"reply_style_{args.label}.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细已写 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
