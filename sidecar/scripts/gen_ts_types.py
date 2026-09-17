"""生成前端契约 TS 类型（单一事实源 = app/contracts 的 pydantic 模型）。

用法：cd sidecar && uv run python scripts/gen_ts_types.py
产物：frontend/src/api/events.gen.ts / dto.gen.ts（提交入库；改契约后重跑并随改动提交）。
依赖：frontend devDep json-schema-to-typescript（json2ts 二进制，脚本按路径调用）。

check.sh 会在 pytest 后重跑本脚本并 `git diff --exit-code` —— 改了模型忘了重新生成，
检查即红（无 CI 环境下的漂移防线）。
"""

import os
import subprocess
import sys
from pathlib import Path

SIDECAR = Path(__file__).resolve().parent.parent
ROOT = SIDECAR.parent


def _resolve_bin(dir_: Path, name: str) -> Path:
    """跨平台找可执行 shim：Windows 的 console-script 落 .exe、npm .bin 落
    .cmd shim（扩展名探测优先，unix 无这些形态自然落到无扩展名 sh shim）——
    2026-09-17 v0.2.1 五跑实证：写死无扩展名在 Windows 上必找不到。"""
    for cand in (dir_ / f"{name}.exe", dir_ / f"{name}.cmd", dir_ / name):
        if cand.exists():
            return cand
    return dir_ / name


JSON2TS = _resolve_bin(ROOT / "frontend" / "node_modules" / ".bin", "json2ts")

GENERATIONS = [
    ("app.contracts.events", ROOT / "frontend/src/api/events.gen.ts"),
    ("app.contracts.dto", ROOT / "frontend/src/api/dto.gen.ts"),
]


def main() -> None:
    if not JSON2TS.exists():
        sys.exit("json2ts 不存在：先在 frontend 下 npm install（devDep json-schema-to-typescript）")
    pydantic2ts = _resolve_bin(Path(sys.executable).parent, "pydantic2ts")
    if not pydantic2ts.exists():
        sys.exit("pydantic2ts 不在当前 venv：用 uv run 执行本脚本")
    for module, output in GENERATIONS:
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(pydantic2ts),
                "--module",
                module,
                "--output",
                str(output),
                "--json2ts-cmd",
                str(JSON2TS),
            ],
            check=True,
            cwd=SIDECAR,
            env={**os.environ, "PYTHONPATH": str(SIDECAR)},
        )
        print(f"生成 {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
