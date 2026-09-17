#!/usr/bin/env python3
"""把发版版本号同步写进全部版本载体（release CI 从 tag 调用，2026-09-17 批次⑥）。

用法：python3 scripts/set_version.py 0.3.0

五处「正式」版本 + package-lock 两处（lock 根版本随 package.json 同步，防漂移——
v0.2.0 时代 package-lock 根版本停在 0.0.0 就是手改 package.json 不跑 npm install
留下的）。tauri.conf.json 是用户可见真值（vite 注入 __APP_VERSION__），其余四处是
构建元数据/healthz 上报，全部从 tag 单点写入。

本仓库工作树内的五处一致性由 check.sh check_versions 守卫；本脚本只负责
「tag 构建时把工作树版本对齐到 tag」，不做回落。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def set_json(path: Path, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_regex(path: Path, pattern: str, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, lambda m: m.group(1) + version + '"', text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"✗ {path} 未找到版本字段（pattern={pattern}）")
    path.write_text(new, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("用法: set_version.py <x.y.z>")
    version = sys.argv[1].lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"✗ 版本号须为 x.y.z 形态（实际：{version}）")

    set_json(ROOT / "src-tauri/tauri.conf.json", version)
    set_regex(ROOT / "src-tauri/Cargo.toml", r'^(version\s*=\s*")([^"]+)"', version)
    set_json(ROOT / "frontend/package.json", version)
    set_regex(ROOT / "sidecar/pyproject.toml", r'^(version\s*=\s*")([^"]+)"', version)
    set_regex(ROOT / "sidecar/app/main.py", r'^(VERSION = ")([^"]+)"', version)

    lock = ROOT / "frontend/package-lock.json"
    if lock.is_file():
        data = json.loads(lock.read_text(encoding="utf-8"))
        changed = False
        if isinstance(data.get("version"), str):
            data["version"] = version
            changed = True
        pkgs = data.get("packages", {})
        if isinstance(pkgs, dict) and isinstance(pkgs.get(""), dict) and pkgs[""].get("version"):
            pkgs[""]["version"] = version
            changed = True
        if changed:
            lock.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"==> 版本已同步为 {version}（tauri.conf / Cargo.toml / package.json / pyproject / main.py / package-lock）")


if __name__ == "__main__":
    main()
