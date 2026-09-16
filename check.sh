#!/usr/bin/env bash
#
# 灵燕智能 一键全栈检查：sidecar(Python) + frontend(TS) + src-tauri(Rust)。
# 提交前 / 改动后快速回归用；将来若上 CI，直接把这里的命令搬进 workflow。
#
# 用法：
#   ./check.sh            # 全部
#   ./check.sh sidecar    # 只查 Python（ruff + pytest）
#   ./check.sh frontend   # 只查前端（oxlint + tsc + vitest + build）
#   ./check.sh rust       # 只查 Rust（cargo check + clippy）
#
set -u
cd "$(dirname "$0")"

run() { echo "\n==> $*"; "$@"; }
fail=0
step() { run "$@" || fail=1; }

check_versions() {
  # 版本号一致性守卫：五处必须同步（tauri.conf.json 由 CI 从 tag 覆写，其余手动）。
  # tauri.conf.json 的版本经 vite 注入设置页 __APP_VERSION__ 与版本检查比较
  # （2026-09-15 起；此前读 package.json 导致脱节即用户可见的错版号）。
  echo "\n==> 版本号一致性（tauri.conf / Cargo.toml / package.json / pyproject / main.py）"
  if ! python3 - <<'EOF'
import json, re, sys

def toml_ver(path: str) -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', open(path, encoding="utf-8").read(), re.M)
    if not m:
        sys.exit(f"无法解析 {path} 的 version 字段")
    return m.group(1)

spots = {
    "src-tauri/tauri.conf.json": json.load(open("src-tauri/tauri.conf.json", encoding="utf-8"))["version"],
    "src-tauri/Cargo.toml": toml_ver("src-tauri/Cargo.toml"),
    "frontend/package.json": json.load(open("frontend/package.json", encoding="utf-8"))["version"],
    "sidecar/pyproject.toml": toml_ver("sidecar/pyproject.toml"),
    "sidecar/app/main.py": re.search(
        r'^VERSION = "([^"]+)"', open("sidecar/app/main.py", encoding="utf-8").read(), re.M
    ).group(1),
}
if len(set(spots.values())) != 1:
    print("✗ 版本号不一致（发版五处必须同步，见 docs/packaging.md）：")
    for k, v in spots.items():
        print(f"  {k}: {v}")
    sys.exit(1)
print(f"  五处版本一致：{next(iter(spots.values()))}")
EOF
  then
    fail=1
  fi
}

check_sidecar() {
  cd sidecar
  step uv run ruff check app tests
  step uv run pytest -q
  # 契约类型漂移防线：重新生成前端 TS 类型，与入库版本 diff（改了 pydantic 契约模型
  # 忘了跑 scripts/gen_ts_types.py 在此挂掉）。生成失败必须显式失败并打印报错——
  # 静默跳过会让这条防线恰好在最需要它的环境（新 clone/缺依赖）失效；成功路径静音。
  if ! gen_out="$(uv run python scripts/gen_ts_types.py 2>&1)"; then
    echo "\n==> 契约 TS 类型生成失败（缺 pydantic2ts/json2ts 依赖或生成器异常）："
    printf '%s\n' "$gen_out"
    fail=1
  elif ! git diff --exit-code -- ../frontend/src/api/events.gen.ts ../frontend/src/api/dto.gen.ts >/dev/null; then
    echo "\n==> 契约 TS 类型与 pydantic 模型不同步（sidecar/scripts/gen_ts_types.py 后提交）"
    fail=1
  fi
  cd ..
}

check_frontend() {
  cd frontend
  step npm run lint
  step npm run typecheck
  # vitest 尚未引入时跳过（package.json 无 test script 即视为未配置）
  if [ "$(node -p "require('./package.json').scripts.test !== undefined")" = "true" ]; then
    step npm run test
  else
    echo "\n==> vitest 未配置，跳过"
  fi
  step npm run build
  cd ..
}

check_rust() {
  cd src-tauri
  step cargo check
  step cargo clippy -- -D warnings
  cd ..
}

target="${1:-all}"
case "$target" in
  sidecar)  check_sidecar ;;
  frontend) check_frontend ;;
  rust)     check_rust ;;
  all)      check_versions; check_sidecar; check_frontend; check_rust ;;
  *) echo "未知目标: $target（sidecar|frontend|rust|all）"; exit 2 ;;
esac

if [ "$fail" -ne 0 ]; then
  echo "\n✗ 检查未全部通过"
  exit 1
fi
echo "\n✓ 全部通过"
