#!/usr/bin/env bash
# 冻结 sidecar 为可分发单文件（PyInstaller one-file），产物供 Tauri externalBin 捆绑。
#
# 关键约定：
# - 独立 .build-venv（uv 管的 python-build-standalone CPython 3.12，按 uv.lock 精确装）。
#   日常 .venv 软链 miniforge base，conda Python 打 PyInstaller 会把 dylib 路径指向
#   conda 前缀，用户机器没有 miniforge 即加载失败——绝不能从它冻结。
# - 产物名 = tender-agent-sidecar-<triple>（tauri externalBin 命名规则）。
# - UPX 禁用（spec 内 upx=False）：UPX 压缩产物过不了 codesign。
#
# 用法（多平台指引见 docs/packaging.md）：
#   build_sidecar.sh                      # 本机平台（rustc host triple）+ 构建尾部自动冒烟
#   build_sidecar.sh --target <triple>    # 指定目标 triple，如 x86_64-apple-darwin
#   build_sidecar.sh --no-smoke           # 跳过尾部冒烟门（CI 无 Rosetta 等场景）
#
# 多平台边界（PyInstaller 无法跨 OS 交叉编译——各平台产物须在各自 OS 上构建）：
# - 跨 OS 目标（如 mac 上打 windows/linux）直接拒绝并指路。
# - 同 OS 跨架构（mac arm 机打 x86_64-apple-darwin 半边，供 universal 用）经 uv 安装
#   对应架构托管 CPython，PyInstaller 在 Rosetta 下运行；venv 落 .build-venv-<arch>
#   与本机 .build-venv 隔离。
# - 冒烟门默认在「目标 OS = 本机 OS」时自动跑（跨架构经 Rosetta 也可跑）；跨 OS 产物
#   本机不可运行，跳过并提示去目标平台复跑 --smoke。
set -euo pipefail

TARGET=""
RUN_SMOKE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:?--target 需要 <triple> 参数，如 x86_64-apple-darwin}"; shift 2 ;;
    --no-smoke) RUN_SMOKE=0; shift ;;
    -h|--help) grep '^#' "$0" | grep -v '^#!' | sed 's/^#\s\{0,1\}//'; exit 0 ;;
    *) echo "未知参数: $1（支持 --target <triple> | --no-smoke）" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/sidecar"

command -v rustc >/dev/null 2>&1 || { echo "✗ 未找到 rustc（Tauri 构建同样需要，先装 Rust 工具链）" >&2; exit 1; }
HOST_TRIPLE="$(rustc --print host-tuple 2>/dev/null || rustc -vV | sed -n 's/^host: //p')"
TRIPLE="${TARGET:-$HOST_TRIPLE}"

triple_os() {
  case "$1" in
    *-apple-darwin) echo darwin ;;
    *-windows-*)    echo windows ;;
    *-linux-*)      echo linux ;;
    *)              echo unknown ;;
  esac
}
HOST_OS="$(triple_os "$HOST_TRIPLE")"
HOST_ARCH="${HOST_TRIPLE%%-*}"
OS="$(triple_os "$TRIPLE")"
ARCH="${TRIPLE%%-*}"

if [ "$OS" = "unknown" ]; then
  echo "✗ 无法识别目标 triple: ${TRIPLE}（示例：aarch64-apple-darwin / x86_64-pc-windows-msvc / x86_64-unknown-linux-gnu）" >&2
  exit 1
fi
if [ "$OS" != "$HOST_OS" ]; then
  echo "✗ PyInstaller 无法跨 OS 冻结：本机=${HOST_TRIPLE}，目标=${TRIPLE}。" >&2
  echo "  在目标 OS 环境跑同一脚本（原生机器 / 虚拟机 / CI），完整指引见 docs/packaging.md。" >&2
  exit 1
fi

# venv 布局按平台分派：unix=bin/，Windows=Scripts/（Windows 构建未实测验证，
# 产物冒烟 --smoke 与真机拉起属后续 Windows 门）
VENV_DIR="$PWD/.build-venv"
PY_REQ="3.12"
if [ "$ARCH" != "$HOST_ARCH" ]; then
  # 同 OS 跨架构：uv 托管 Python 用 python-build-standalone 命名
  # （macos-aarch64-none / windows-x86_64-none / linux-x86_64-gnu）。
  # 注意不可写成 $(case ...)：macOS 自带 bash 3.2 解析不了 $() 内嵌 case（模式里的
  # ) 会被当替换结束符，执行期才爆），本脚本须兼容 /bin/bash 3.2。
  PBS_OS="$OS"
  [ "$OS" = "darwin" ] && PBS_OS="macos"
  PBS_LIB="none"
  [ "$OS" = "linux" ] && PBS_LIB="gnu"
  PY_REQ="cpython-3.12-${PBS_OS}-${ARCH}-${PBS_LIB}"
  VENV_DIR="$PWD/.build-venv-${ARCH}"
  echo "==> 跨架构构建（本机 ${HOST_ARCH} → 目标 ${ARCH}）：安装 ${PY_REQ}，PyInstaller 将经 Rosetta 运行"
  uv python install "$PY_REQ"
  # 生态现实：cryptography 50.x 的 macOS 轮子只发 arm64（上游放弃 Intel mac），
  # x86_64 侧只能源码编译（maturin/cargo）——需要 rustup 装目标 triple 的 std，
  # 否则 E0463 can't find crate for `core`。rustup 不存在时降级为提示（继续跑，
  # 若本次无 sdist 依赖则照样能过）。
  if command -v rustup >/dev/null 2>&1; then
    rustup target add "$TRIPLE"
  else
    echo "!! 未找到 rustup：若依赖解析走到源码编译（cryptography 等）会失败，建议经 rustup 管理 Rust" >&2
  fi
fi
case "$OS" in
  windows) VENV_BIN="$VENV_DIR/Scripts" ;;
  *)       VENV_BIN="$VENV_DIR/bin" ;;
esac

export SIDECAR_NAME="tender-agent-sidecar-${TRIPLE}"
# Windows 构建加 -w 无控制台窗（stderr 由 Rust 侧重定向，日志仍进 boot 留档）
case "$OS" in windows) export SIDECAR_WINDOWED=1 ;; *) export SIDECAR_WINDOWED=0 ;; esac

# --inexact：不剔除 lock 外的包，pyinstaller 装一次即可跨多次构建复用
# （uv sync 默认精确同步会先删掉它；想彻底重建删 .build-venv* 重跑）
echo "==> build venv（$VENV_DIR, CPython ${PY_REQ}, --frozen）"
UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv sync --python "$PY_REQ" --frozen --no-dev --inexact
if [ ! -x "${VENV_BIN}/pyinstaller" ] && [ ! -x "${VENV_BIN}/pyinstaller.exe" ]; then
  echo "==> 安装锁版 PyInstaller 到 build venv"
  PY_BIN="${VENV_BIN}/python"; [ "$OS" = "windows" ] && PY_BIN="${PY_BIN}.exe"
  uv pip install --python "$PY_BIN" "pyinstaller==6.14.1"
fi

echo "==> PyInstaller one-file → src-tauri/binaries/${SIDECAR_NAME}"
"${VENV_BIN}/pyinstaller" \
  --clean --noconfirm \
  --distpath "$ROOT/src-tauri/binaries" \
  --workpath "$PWD/build/pyinstaller" \
  tender-agent-sidecar.spec

ARTIFACT="$ROOT/src-tauri/binaries/${SIDECAR_NAME}"
ls -lh "$ARTIFACT"

# 冒烟门：产物自检（one-file 解压 + 高风险依赖逐项验证，实测 ~12s）。收集漏项里
# 恰恰多的是「不崩溃只退化」型（如版式模板缺失静默回落英文默认模板），必须逐次构建后跑。
if [ "$RUN_SMOKE" -eq 1 ] && [ "$OS" = "$HOST_OS" ]; then
  echo "==> 冒烟门：${SIDECAR_NAME} --smoke"
  if ! "$ARTIFACT" --smoke; then
    echo "✗ 冒烟失败。跨架构产物若报「Bad CPU type」：装 Rosetta（softwareupdate --install-rosetta --agree-to-license）或 --no-smoke 跳过" >&2
    exit 1
  fi
  echo "==> 冒烟通过"
else
  echo "==> 跳过冒烟（跨 OS 产物本机不可运行）——请在目标平台跑 '${ARTIFACT##*/} --smoke' 复验"
fi
echo "==> 完成：$ARTIFACT"
