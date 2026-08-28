#!/usr/bin/env bash
#
# Tender Agent 一键全栈检查：sidecar(Python) + frontend(TS) + src-tauri(Rust)。
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

check_sidecar() {
  cd sidecar
  step uv run ruff check app tests
  step uv run pytest -q
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
  all)      check_sidecar; check_frontend; check_rust ;;
  *) echo "未知目标: $target（sidecar|frontend|rust|all）"; exit 2 ;;
esac

if [ "$fail" -ne 0 ]; then
  echo "\n✗ 检查未全部通过"
  exit 1
fi
echo "\n✓ 全部通过"
