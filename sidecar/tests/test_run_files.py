"""run_files：run 起止 work/ 快照 diff 的收录范围与 HITL 分段合并语义。"""

import os

import pytest

from app import artifact_store, run_files


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _write(tid: str, rel: str, content: str = "x"):
    p = artifact_store.work_dir(tid) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_snapshot_scope(ws):
    """收录范围与工作台面板同口径：只收 .md/.docx；json/隐藏文件/artifacts 产物包子树不收。"""
    tid = "t_snap"
    artifact_store.ensure_task_skeleton(tid)
    _write(tid, "analysis/structure.md")
    _write(tid, "analysis/structure.outline.json")  # 机器格式（面板不是调试器）
    _write(tid, "parse/招标文件/招标文件.md")
    _write(tid, ".hidden.md")  # 隐藏文件（工作台 .bak 兜底同族）
    _write(tid, "artifacts/art_abc123def456/meta.md")  # 产物包子树：产物卡通道
    _write(tid, "body/3.1 需求分析.docx", content="binary")  # docx 正文节（面板有只读视图）
    # 恢复点目录（docx_ops replace / 工作台编辑同款命名）——.bak 不匹配 rglob
    _write(tid, "body/3.1 需求分析.docx.restorepoints/20260906000000000000.bak", content="old")
    snap = run_files.snapshot_work_files(tid)
    assert set(snap) == {
        "analysis/structure.md",
        "parse/招标文件/招标文件.md",
        "body/3.1 需求分析.docx",
    }
    # 无任务（会话缺 task_id 兜底）/ 任务目录不存在
    assert run_files.snapshot_work_files(None) is None
    assert run_files.snapshot_work_files("t_nope") == {}


def test_diff_created_modified_deleted(ws):
    """created=结束有开始无；modified=(mtime_ns,size) 变化；删除不产出条目。"""
    tid = "t_diff"
    artifact_store.ensure_task_skeleton(tid)
    keep = _write(tid, "analysis/keep.md")
    gone = _write(tid, "analysis/gone.md")
    start = run_files.snapshot_work_files(tid)

    _write(tid, "outline/new.md")
    keep.write_text("changed", encoding="utf-8")
    # mtime 显式错开 1ms（防文件系统时间戳精度抖动把 modified 判成没变）
    os.utime(keep, ns=(start["analysis/keep.md"][0], start["analysis/keep.md"][0] + 1_000_000))
    gone.unlink()

    files = run_files.diff_work_files(tid, start)
    assert {f["path"]: f["op"] for f in files} == {
        "outline/new.md": "created",
        "analysis/keep.md": "modified",
    }


def test_diff_no_start_is_no_data(ws):
    """start=None（无任务/探测失败）-> None：调用方按「保留旧值」合并，不覆盖。"""
    assert run_files.diff_work_files("t_x", None) is None
    assert run_files.diff_work_files(None, {}) is None


def test_merge_files():
    """HITL 分段合并：created 优先（先建后改仍是新建）；旧序在前新条目按出现序追加。"""
    old = [
        {"path": "a.md", "op": "created"},
        {"path": "b.md", "op": "modified"},
    ]
    new = [
        {"path": "b.md", "op": "created"},  # 暂停前新建、续段又改 → created
        {"path": "c.md", "op": "modified"},  # 续段新条目追加在后
    ]
    assert run_files.merge_files(old, new) == [
        {"path": "a.md", "op": "created"},
        {"path": "b.md", "op": "created"},
        {"path": "c.md", "op": "modified"},
    ]
    # 两段都只是改（没有分段新建过）→ modified 保持
    assert run_files.merge_files(
        [{"path": "a.md", "op": "modified"}], [{"path": "a.md", "op": "modified"}]
    ) == [{"path": "a.md", "op": "modified"}]
    # new=None（异常兜底/无任务）原样返回 old；空侧直通
    assert run_files.merge_files(old, None) is old
    assert run_files.merge_files(None, new) == new
    assert run_files.merge_files(None, None) is None
