"""run 级工作文件变更探测（「本轮文件」的数据来源，起止快照 diff）。

run 开始时对 <task>/work/ 做文件清单快照，终态时重新枚举做 diff--文件系统是
唯一真值，不依赖任何工具配合登记（未来加新工具自动覆盖），「新建/修改」的判定
是精确的（开始前是否已存在 + mtime/size 是否变化）。

收录范围与工作台面板同一先例（api/workbench.py 的 rglob("*.md") + 跳隐藏文件，
「面板不是调试器」）：只收 work/ 下的 .md 过程文件；json/机器文件不可点开不收；
work/artifacts/（登记产物包）显式跳过--产物有自己的展示通道（产物卡），且包内
本就无 .md。path 存 posix 相对路径（相对 work/），与 WorkbenchFile.path 同约定，
前端 chip 可直接透传给工作台查看器。

有意接受的限制：
- 同任务并发 run 互不感知，diff 可能把对方 run 的写入归到本 run（无锁铁则）。
- mtime/size 判「修改」：同内容重写也会显示为修改（parse_document 同 hash 幂等
  跳过已避免最常见情形）。
"""

from . import artifact_store


def _walk_work_md(task_id: str) -> dict[str, tuple[int, int]]:
    """枚举 work/ 下 .md 文件 -> {posix 相对路径: (mtime_ns, size)}；目录缺失返回 {}。"""
    root = artifact_store.work_dir(task_id)
    if not root.is_dir():
        return {}
    out: dict[str, tuple[int, int]] = {}
    for p in root.rglob("*.md"):
        if not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(root)
        if rel.parts[0] == "artifacts":  # 产物包子树：产物卡通道，不进「本轮文件」
            continue
        st = p.stat()
        out[rel.as_posix()] = (st.st_mtime_ns, st.st_size)
    return out


def snapshot_work_files(task_id: str | None) -> dict[str, tuple[int, int]] | None:
    """run 起点快照；task_id 为空（会话无任务，理论不发生）返回 None=无探测语义。"""
    if not task_id:
        return None
    return _walk_work_md(task_id)


def diff_work_files(
    task_id: str | None, start: dict[str, tuple[int, int]] | None
) -> list[dict] | None:
    """run 终态 diff：start 为 None -> None（调用方按「无新数据」合并，不覆盖旧值）。

    created = 结束有开始无；modified = 两侧都有但 (mtime_ns, size) 变化；
    删除不产出条目（「本轮文件」只回答写了什么，不回答删了什么）。
    """
    if start is None or not task_id:
        return None
    end = _walk_work_md(task_id)
    files: list[dict] = []
    for path, stat in end.items():
        if path not in start:
            files.append({"path": path, "op": "created"})
        elif start[path] != stat:
            files.append({"path": path, "op": "modified"})
    return files


def merge_files(old: list[dict] | None, new: list[dict] | None) -> list[dict] | None:
    """HITL 分段合并（同 run 暂停->续跑，run_traces 一行多段累积）。

    按 path 去重：任一分段新建过即 created（先建后改仍是新建）；旧序在前、
    新条目按出现顺序追加。new 为 None（异常兜底/无任务）-> 原样返回 old。
    """
    if new is None:
        return old
    if not old:
        return new
    merged: dict[str, dict] = {}
    for entry in old:
        merged[entry["path"]] = dict(entry)
    for entry in new:
        path = entry["path"]
        if path in merged:
            if entry["op"] == "created":
                merged[path]["op"] = "created"
        else:
            merged[path] = dict(entry)
    return list(merged.values())
