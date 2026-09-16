#!/usr/bin/env bash
#
# 灵燕智能 开发启动器：一次选择一种模式启动。
#
# 用法：
#   ./dev.sh            # 交互菜单
#   ./dev.sh <mode>     # 直接指定模式
#   ./dev.sh help       # 帮助
#
# 模式：
#   tauri     完整桌面客户端（Tauri 窗口 + 自动拉起 sidecar + Vite；首次 Rust 编译较慢）
#   browser   浏览器模式（sidecar[8765] + Vite[5173]，前端经 proxy 同源访问；日常开发推荐）
#   sidecar   只起 sidecar（8765，前台日志；调试 agent / SSE 后端逻辑用）
#   frontend  只起 Vite（5173，经 proxy 连 8765；需 sidecar 已在跑）
#   preview   纯 UI 预览（只起 Vite 并打开 /preview.html，不依赖 sidecar）
#   stop      停掉 8765 / 5173 上的开发进程
#
# 端口策略：启动前若 8765/5173 被占用，自动 kill 占用进程后继续——这两个是脚本专属的
# 开发端口，理论上只会残留 sidecar/Vite 占着；stop 模式用于手动清理。
#
# 提示：
#   - 浏览器模式务必打开 http://localhost:5173（Vite 只绑 IPv6 localhost，127.0.0.1 连不上）
#   - 别同时跑 Tauri 模式与浏览器模式：两个 sidecar 共用 agent.db 会导致 checkpoint 崩溃
#
set -u
cd "$(dirname "$0")"

PORT_SIDECAR=8765
PORT_VITE=5173

# ---- 小工具 ----
port_pid() { lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null; }
port_in_use() { [ -n "$(port_pid "$1")" ]; }

# 停掉某端口上的进程；该端口本来就空闲时返回 1（供调用方区分）。
# 先 SIGTERM，1 秒后还在就 SIGKILL。
kill_port() {
  local p="$1" pids
  pids=$(port_pid "$p")
  [ -z "$pids" ] && return 1
  echo "  停 $p : $pids"
  kill $pids 2>/dev/null
  sleep 1
  pids=$(port_pid "$p")
  if [ -n "$pids" ]; then
    echo "  强杀 $p : $pids"
    kill -9 $pids 2>/dev/null
  fi
  return 0
}

# 启动前腾端口：被占用就自动 kill 后继续。
free_port() {
  local p="$1" label="$2"
  if port_in_use "$p"; then
    echo "  🔧 端口 $p ($label) 被占用，自动 kill 后继续"
    kill_port "$p"
  fi
}

# ---- 各模式 ----
run_tauri() {
  echo "▶ tauri 完整桌面客户端"
  echo "  窗口内 Cmd+Option+I 打开 DevTools；sidecar 由 Tauri 在随机端口拉起（Python 日志被吞，后端问题请用浏览器模式复现）"
  # tauri dev 也要占 5173（Vite），且不应与浏览器模式共存（共用 agent.db）：
  # 先把两个开发端口腾干净，避免残留 sidecar。
  free_port "$PORT_SIDECAR" "sidecar"
  free_port "$PORT_VITE" "vite"
  npm run dev
}

run_browser() {
  free_port "$PORT_SIDECAR" "sidecar"
  free_port "$PORT_VITE" "vite"
  echo "▶ browser 浏览器模式：sidecar[${PORT_SIDECAR}] + Vite[${PORT_VITE}]"
  echo "  打开 http://localhost:5173（务必用 localhost，勿用 127.0.0.1）"
  echo "  Ctrl+C 同时退出两者"
  npm run dev:browser
}

run_sidecar() {
  free_port "$PORT_SIDECAR" "sidecar"
  echo "▶ sidecar 模式：uv run sidecar @ ${PORT_SIDECAR}（前台日志）"
  ( cd sidecar && uv run --env-file .env python -m app.main --port "$PORT_SIDECAR" )
}

run_frontend() {
  free_port "$PORT_VITE" "vite"
  if ! port_in_use "$PORT_SIDECAR"; then
    echo "  ⚠️  8765 没有 sidecar 在跑，前端会连不上后端。"
    echo "     另开终端跑 ./dev.sh sidecar，或直接用 ./dev.sh browser 一条命令。"
  fi
  echo "▶ frontend 模式：Vite @ ${PORT_VITE}（经 proxy 连 8765）"
  echo "  主页面 http://localhost:5173 ；纯 UI 预览 /preview.html"
  ( cd frontend && npm run dev )
}

run_preview() {
  free_port "$PORT_VITE" "vite"
  echo "▶ preview 纯 UI 预览：Vite @ ${PORT_VITE}，自动打开 /preview.html（不依赖 sidecar）"
  ( cd frontend && npm run dev ) &
  local vpid=$!
  trap 'kill "$vpid" 2>/dev/null' EXIT
  for _ in $(seq 1 40); do
    curl -sf -o /dev/null "http://localhost:${PORT_VITE}/preview.html" && break
    sleep 0.5
  done
  open "http://localhost:${PORT_VITE}/preview.html" 2>/dev/null \
    || echo "  请在浏览器打开 http://localhost:${PORT_VITE}/preview.html"
  wait "$vpid"
  trap - EXIT
}

stop_dev() {
  echo "▶ 停掉开发进程（端口 ${PORT_SIDECAR} / ${PORT_VITE}）"
  for p in "$PORT_SIDECAR" "$PORT_VITE"; do
    kill_port "$p" || echo "  $p 空闲"
  done
  return 0
}

# ---- 入口 ----
usage() {
  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '3,23p'
}

main() {
  local mode="${1:-}"
  if [ -z "$mode" ]; then
    while true; do
      echo ""
      echo "灵燕智能 开发启动器"
      echo "==================="
      echo "  1) tauri     完整桌面客户端"
      echo "  2) browser   浏览器模式（sidecar + Vite，推荐）"
      echo "  3) sidecar   只起 sidecar（8765）"
      echo "  4) frontend  只起 Vite（5173）"
      echo "  5) preview   纯 UI 预览（/preview.html）"
      echo "  6) stop      停掉开发进程（8765/5173）"
      echo "  q) 退出"
      echo ""
      read -rp "请选择 [1-6/q]: " mode
      [ -n "$mode" ] && break
    done
  fi
  case "$mode" in
    1|tauri)     run_tauri ;;
    2|browser)   run_browser ;;
    3|sidecar)   run_sidecar ;;
    4|frontend)  run_frontend ;;
    5|preview)   run_preview ;;
    6|stop)      stop_dev ;;
    q|Q|quit)    echo "退出。"; exit 0 ;;
    -h|--help|help) usage; exit 0 ;;
    *) echo "未知模式：$mode"; usage; exit 1 ;;
  esac
}

main "$@"
