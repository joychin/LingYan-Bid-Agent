#!/usr/bin/env bash
#
# 灵燕智能 一键全栈检查：sidecar(Python) + frontend(TS) + src-tauri(Rust)。
# 提交前 / 改动后快速回归用；tag 出包路径（release.yml 的 win/mac job 前置）跑的就是本脚本。
#
# 用法：
#   ./check.sh            # 全部
#   ./check.sh sidecar    # 只查 Python（ruff + pytest）
#   ./check.sh frontend   # 只查前端（oxlint + tsc + vitest + build）
#   ./check.sh rust       # 只查 Rust（cargo check + clippy + test）
#
set -u
cd "$(dirname "$0")" || exit 1

# printf 而非 echo：bash 内建 echo 原样打印 "\n" 字面量（不转义）——全部输出点
# 统一 printf，勿新增 echo（2026-09-17 复审收尾补齐 7 处残留）
run() { printf '\n==> %s\n' "$*"; "$@"; }
fail=0
step() { run "$@" || fail=1; }

check_versions() {
  # 版本号一致性守卫：五处必须同步（tauri.conf.json 由 CI 从 tag 覆写，其余手动）。
  # tauri.conf.json 的版本经 vite 注入设置页 __APP_VERSION__ 与版本检查比较
  # （2026-09-15 起；此前读 package.json 导致脱节即用户可见的错版号）。
  printf '\n==> %s\n' '版本号一致性（tauri.conf / Cargo.toml / package.json / pyproject / main.py）'
  PY="$(command -v python3 || command -v python)"
  if ! "$PY" - <<'EOF'
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
  cd sidecar || exit 1
  step uv run ruff check app tests
  step uv run pytest -q
  # 契约类型漂移防线：重新生成前端 TS 类型，与入库版本 diff（改了 pydantic 契约模型
  # 忘了跑 scripts/gen_ts_types.py 在此挂掉）。生成失败必须显式失败并打印报错——
  # 静默跳过会让这条防线恰好在最需要它的环境（新 clone/缺依赖）失效；成功路径静音。
  if ! gen_out="$(uv run python scripts/gen_ts_types.py 2>&1)"; then
    printf '\n==> %s\n' '契约 TS 类型生成失败（缺 pydantic2ts/json2ts 依赖或生成器异常）：'
    printf '%s\n' "$gen_out"
    fail=1
  elif ! git diff --exit-code -- ../frontend/src/api/events.gen.ts ../frontend/src/api/dto.gen.ts >/dev/null; then
    printf '\n==> %s\n' '契约 TS 类型与 pydantic 模型不同步（sidecar/scripts/gen_ts_types.py 后提交）'
    fail=1
  fi
  cd .. || exit 1
}

check_frontend() {
  cd frontend || exit 1
  step npm run lint
  step npm run typecheck
  # vitest 尚未引入时跳过（package.json 无 test script 即视为未配置）
  if [ "$(node -p "require('./package.json').scripts.test !== undefined")" = "true" ]; then
    step npm run test
  else
    printf '\n==> %s\n' 'vitest 未配置，跳过'
  fi
  step npm run build
  cd .. || exit 1
}

check_rust() {
  cd src-tauri || exit 1
  step cargo check
  # 单测必须有机行入口（2026-09-17 批次⑥）：sidecar.rs 尾部的崩溃分类/数据目录
  # 迁移单测此前在全仓任何路径（本地 check.sh 与 CI）都不会被执行，秒级成本
  step cargo test
  step cargo clippy -- -D warnings
  cd .. || exit 1
}

target="${1:-all}"
case "$target" in
  sidecar)  check_sidecar ;;
  frontend) check_frontend ;;
  rust)     check_rust ;;
  all)      check_versions; check_sidecar; check_frontend; check_rust ;;
  *) printf '未知目标: %s（sidecar|frontend|rust|all）\n' "$target"; exit 2 ;;
esac

if [ "$fail" -ne 0 ]; then
  printf '\n✗ 检查未全部通过\n'
  exit 1
fi
printf '\n✓ 全部通过\n'
