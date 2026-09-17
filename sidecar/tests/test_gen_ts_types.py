"""gen_ts_types 的可执行 shim 跨平台解析（2026-09-17 v0.2.1 五跑实证：Windows 上
写死无扩展名找不到——venv console-script 落 .exe、npm .bin 落 .cmd shim）。"""

import importlib.util
from pathlib import Path


def _load():
    src = Path(__file__).resolve().parent.parent / "scripts" / "gen_ts_types.py"
    spec = importlib.util.spec_from_file_location("gen_ts_types", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_resolve_bin_prefers_windows_suffixes(tmp_path):
    resolve = _load()._resolve_bin
    # Windows venv：只有 .exe → 选 .exe（修前写死无扩展名在 win 上必找不到）
    (tmp_path / "pydantic2ts.exe").write_bytes(b"")
    assert resolve(tmp_path, "pydantic2ts").name == "pydantic2ts.exe"
    # Windows npm .bin：.cmd shim 与无扩展名 sh shim 并存 → 优先 .cmd
    d2 = tmp_path / "bin2"
    d2.mkdir()
    (d2 / "json2ts.cmd").write_bytes(b"")
    (d2 / "json2ts").write_bytes(b"")
    assert resolve(d2, "json2ts").name == "json2ts.cmd"
    # unix：只有无扩展名 sh shim → 原样选中
    d3 = tmp_path / "bin3"
    d3.mkdir()
    (d3 / "json2ts").write_bytes(b"")
    assert resolve(d3, "json2ts").name == "json2ts"
    # 全无 → 兜底无扩展名路径（让 main 的守卫给人话报错，不在此抛）
    d4 = tmp_path / "bin4"
    d4.mkdir()
    assert resolve(d4, "json2ts").name == "json2ts"
