# -*- mode: python ; coding: utf-8 -*-
"""Tender Agent sidecar 冻结配置（PyInstaller one-file）。

构建走 sidecar/build_sidecar.sh（独立 .build-venv，勿用日常 .venv——它软链 miniforge）。
产物：src-tauri/binaries/<SIDECAR_NAME>（one-file 单文件，Tauri externalBin 只收单文件）。

收集依据（2026-09-07 依赖扫描：app 源码零动态导入，风险全在生态）：
- datas app/skills/**：main._sync_skills 启动时按 __file__ 相对路径读技能文件，
  非 .py 不进 PYZ，漏了启动即 warning 且 agent 无技能。
- collect_data trafilatura：settings.cfg / data/tei_corpus.dtd 走 __file__ 读，无 hook。
- collect_submodules 保底（冷门无 hook + 懒加载）：deepagents / langchain 全家 /
  openai（3.x _resources_proxy 纯字符串 import_module("openai.resources")；
  langgraph jsonplus 反序列化动态 import = agent.db 会话恢复路径；
  langgraph 一条物理覆盖 langgraph/checkpoint/sqlite 子包）。
- 有现成 hook 无需处理：uvicorn / jieba / certifi / python-docx / pydantic / lxml。
- upx 必须 False：UPX 压缩产物过不了 codesign 校验（macOS 签名公证硬前提）。
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 构建脚本经 env 传 triple 后缀（tauri externalBin 命名规则）与 Windows 无控制台开关
exe_name = os.environ.get("SIDECAR_NAME", "tender-agent-sidecar")
windowed = os.environ.get("SIDECAR_WINDOWED", "") == "1"

datas = [
    ("app/skills", "app/skills"),
    # 标书基准 docx 模板（docx_ops._new_document 按 __file__ 相对路径读，
    # 漏了建节回落英文默认模板=版式退化，非崩溃）
    ("app/resources", "app/resources"),
]
datas += collect_data_files("trafilatura")
# trafilatura 2.x 走 justext 剔除样板文本，stoplists 是包内数据文件（冻结冒烟实测抓漏）
datas += collect_data_files("justext")

hiddenimports = []
for _pkg in (
    "deepagents",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_deepseek",
    "langgraph",
    "openai",
):
    hiddenimports += collect_submodules(_pkg)


a = Analysis(
    ["run_frozen.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=not windowed,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
