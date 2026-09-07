#!/usr/bin/env bash
# 冻结 sidecar 为可分发单文件（PyInstaller one-file），产物供 Tauri externalBin 捆绑。
#
# 关键约定：
# - 独立 .build-venv（uv 管的 python-build-standalone CPython 3.12，按 uv.lock 精确装）。
#   日常 .venv 软链 miniforge base，conda Python 打 PyInstaller 会把 dylib 路径指向
#   conda 前缀，用户机器没有 miniforge 即加载失败——绝不能从它冻结。
# - 产物名 = tender-agent-sidecar-<target_triple>（tauri externalBin 命名规则）。
# - UPX 禁用（spec 内 upx=False）：UPX 压缩产物过不了 codesign。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/sidecar"

TRIPLE="$(rustc --print host-tuple 2>/dev/null || rustc -vV | sed -n 's/^host: //p')"
export SIDECAR_NAME="tender-agent-sidecar-${TRIPLE}"
# Windows 构建加 -w 无控制台窗（stderr 由 Rust 侧重定向，日志仍进 boot 留档）
case "$TRIPLE" in *windows*) export SIDECAR_WINDOWED=1 ;; *) export SIDECAR_WINDOWED=0 ;; esac
# venv 布局按平台分派：unix=bin/，Windows=Scripts/（Windows 构建未实测验证，
# 产物冒烟 --smoke 与真机拉起属后续 Windows 门）
case "$TRIPLE" in
  *windows*) VENV_BIN="$PWD/.build-venv/Scripts" ;;
  *) VENV_BIN="$PWD/.build-venv/bin" ;;
esac

echo "==> build venv（.build-venv, CPython 3.12, --frozen）"
UV_PROJECT_ENVIRONMENT="$PWD/.build-venv" uv sync --python 3.12 --frozen --no-dev
"${VENV_BIN}/python" -m pip --version >/dev/null 2>&1 || true
if [ ! -x "${VENV_BIN}/pyinstaller" ] && [ ! -x "${VENV_BIN}/pyinstaller.exe" ]; then
  echo "==> 安装锁版 PyInstaller 到 build venv"
  uv pip install --python "${VENV_BIN}/python" "pyinstaller==6.14.1"
fi

echo "==> PyInstaller one-file → src-tauri/binaries/${SIDECAR_NAME}"
"${VENV_BIN}/pyinstaller" \
  --clean --noconfirm \
  --distpath "$ROOT/src-tauri/binaries" \
  --workpath "$PWD/build/pyinstaller" \
  tender-agent-sidecar.spec

ls -lh "$ROOT/src-tauri/binaries/"
echo "==> 完成：$ROOT/src-tauri/binaries/${SIDECAR_NAME}"
