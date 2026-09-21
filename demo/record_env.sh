#!/bin/bash
# 演示录制环境切换：真实数据换出/还原（录制产品演示视频用，配套 demo/README.md）。
#
#   ./demo/record_env.sh on      备份真实数据 → 拷入演示数据 → 临时提升版本号（去更新红点）
#   ./demo/record_env.sh off     停用演示态：还原真实数据与版本号，并按清单校验还原完整
#   ./demo/record_env.sh status  查看当前状态
#
# 铁则：真实数据整目录 mv 备份（sidecar/data → sidecar/data.real），绝不删除；
#       已处于演示态时拒绝再次 on；未处于演示态时拒绝 off。幂等、可随时 status 自查。

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIDECAR_DATA="${ROOT}/sidecar/data"
BACKUP="${ROOT}/sidecar/data.real"
DEMO_SRC="${ROOT}/demo/demo-data"
MANIFEST="${ROOT}/demo/.real-data.manifest"
CONF="${ROOT}/src-tauri/tauri.conf.json"
CONF_ORIG="${ROOT}/demo/.tauri.conf.json.orig"
UPDATE_URL="https://ddmdj.com/release/version.json"

say() { echo "[record_env] $*"; }
die() { echo "[record_env] 错误：$*" >&2; exit 1; }

# dev 运行检测：vite(5173) 抓 tauri dev / 浏览器模式；8765 抓独立 sidecar
check_dev_running() {
  if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
    return 0
  fi
  if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

require_dev_stopped() {
  check_dev_running && die "开发进程还在运行（5173/8765 被占用）——先执行 ./dev.sh stop 再切换"
  return 0
}

bump_version() {
  # 取远端最新发布号（失败回退 0.2.2），临时写进 tauri.conf.json：
  # 消除录制画面的更新红点、设置页版本号与正式发布一致；原文件存档，off 时还原
  local ver="0.2.2"
  local fetched
  if command -v curl >/dev/null 2>&1; then
    fetched="$(curl -fsS --max-time 5 "${UPDATE_URL}" 2>/dev/null | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    if [ -n "${fetched}" ]; then
      ver="${fetched}"
    fi
  fi
  cp "${CONF}" "${CONF_ORIG}"
  python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["version"]=sys.argv[2]; json.dump(d, open(p,"w"), ensure_ascii=False, indent=2); open(p,"a").write("\n")' "${CONF}" "${ver}"
  say "版本号临时提升为 ${ver}（原文件存档在 demo/.tauri.conf.json.orig）"
}

restore_version() {
  if [ -f "${CONF_ORIG}" ]; then
    cp "${CONF_ORIG}" "${CONF}"
    rm -f "${CONF_ORIG}"
    say "tauri.conf.json 已还原"
  fi
}

do_on() {
  [ -d "${BACKUP}" ] && die "已处于演示态（${BACKUP} 存在）——如需重新开始请先 ./demo/record_env.sh off"
  [ -d "${DEMO_SRC}" ] || die "演示数据不存在：先跑 cd sidecar && uv run python ../demo/seed_demo.py"
  require_dev_stopped

  if [ -d "${SIDECAR_DATA}" ]; then
    mv "${SIDECAR_DATA}" "${BACKUP}"
    (cd "${BACKUP}" && find . -type f | sort) > "${MANIFEST}"
    say "真实数据已备份 → ${BACKUP}（$(wc -l < "${MANIFEST}" | tr -d ' ') 个文件）"
  else
    : > "${MANIFEST}"
    say "本无真实数据目录，直接创建演示数据"
  fi
  cp -R "${DEMO_SRC}" "${SIDECAR_DATA}"
  say "演示数据已就位 → ${SIDECAR_DATA}"
  bump_version
  say "现在可以录制：npm run dev（Tauri 开发窗口）"
  say "录完务必执行：./demo/record_env.sh off"
}

do_off() {
  [ -d "${BACKUP}" ] || die "当前不是演示态（${BACKUP} 不存在），无需还原"
  require_dev_stopped

  rm -rf "${SIDECAR_DATA}"
  mv "${BACKUP}" "${SIDECAR_DATA}"
  say "真实数据已还原 → ${SIDECAR_DATA}"
  restore_version

  local current
  current="$(cd "${SIDECAR_DATA}" && find . -type f | sort)"
  if [ ! -s "${MANIFEST}" ]; then
    say "还原完成（换出时无真实数据，无清单可校验）"
  elif [ "${current}" = "$(cat "${MANIFEST}")" ]; then
    say "还原校验通过：文件清单与备份时一致"
  else
    echo "[record_env] 警告：还原后文件清单与备份时有差异（可能是备份期间的真实增量，也可能异常）" >&2
    diff <(echo "${current}") "${MANIFEST}" | head -20 || true
    echo "[record_env] 请人工确认 sidecar/data 内容无误后，删除清单 ${MANIFEST}" >&2
    exit 1
  fi
  rm -f "${MANIFEST}"
  say "演示数据保留在 ${DEMO_SRC}，可随时再次 on 复录；不需要时手动删除即可"
}

do_status() {
  if [ -d "${BACKUP}" ]; then
    say "状态：演示态（真实数据备份在 ${BACKUP}）"
  else
    say "状态：真实态"
  fi
  [ -d "${DEMO_SRC}" ] && say "演示数据：${DEMO_SRC}（可用）" || say "演示数据：未生成（跑 seed_demo.py）"
  [ -f "${CONF_ORIG}" ] && say "tauri.conf.json：已被临时改写（off 时还原）" || say "tauri.conf.json：原样"
  if check_dev_running; then
    say "开发进程：运行中（切换前需 ./dev.sh stop）"
  else
    say "开发进程：未运行"
  fi
}

case "${1:-}" in
  on)     do_on ;;
  off)    do_off ;;
  status) do_status ;;
  *) echo "用法：$0 on|off|status" >&2; exit 2 ;;
esac
