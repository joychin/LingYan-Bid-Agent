"""GuardedBackend 写路径黑名单（P0.3，fs_guard.py）。

边界：只拦写（write/edit/delete），read/ls/grep/glob 完全放开；
out/（任务工作台）与 drafts/（发布草稿区）正常可写。
"""

import pytest

from app import fs_guard
from app.fs_guard import GuardedBackend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    from tests.util import init_env

    task, conv = init_env(tmp_path, monkeypatch)
    from app import config as cfg

    root = cfg.workspace_dir()
    return GuardedBackend(root_dir=str(root)), task, conv


def test_write_rejects_formal_package(backend):
    be, task, _ = backend
    r = be.write(f"{task['id']}/formal/art_x/current/content.json", "{}")
    assert r.error and "写入被拒绝" in r.error
    # manifest / 恢复点同样拒写
    assert be.write(f"{task['id']}/formal/art_x/manifest.json", "{}").error
    assert be.write(f"{task['id']}/formal/art_x/restorepoints/rp1.json", "{}").error


def test_write_rejects_thread_art_package(backend):
    be, task, conv = backend
    r = be.write(f"{task['id']}/threads/{conv['id']}/art_y/current/content.json", "{}")
    assert r.error and "写入被拒绝" in r.error
    assert be.edit(
        f"{task['id']}/threads/{conv['id']}/art_y/manifest.json", "a", "b"
    ).error
    assert be.delete(f"{task['id']}/threads/{conv['id']}/art_y/current/content.json").error


def test_write_rejects_archive_and_skills(backend):
    be, task, _ = backend
    assert be.write(f"archive/{task['id']}/formal/art_x/manifest.json", "{}").error
    assert be.write("skills/tender-analysis/SKILL.md", "hacked").error
    # 深层 skills 路径段命中同样拒
    assert be.write("skills/tender-outline/references/r1.md", "x").error


def test_write_allows_out_and_drafts(backend):
    be, task, _ = backend
    ok1 = be.write(f"{task['id']}/out/analysis/structure.md", "# 结构事实")
    assert not ok1.error and ok1.path
    ok2 = be.write(f"{task['id']}/drafts/run-1/toc.json", "{}")
    assert not ok2.error
    # 任务 files/ 上传区可写（模型读得见即可，不额外禁止）
    ok3 = be.write(f"{task['id']}/files/招标文件.docx", "bin")
    assert not ok3.error


def test_edit_delete_scoped_to_protected_only(backend):
    be, task, _ = backend
    # 工作台文件：编辑/删除不受限
    be.write(f"{task['id']}/out/analysis/evaluation.md", "line1\nline2")
    assert not be.edit(f"{task['id']}/out/analysis/evaluation.md", "line1", "line1!").error
    assert not be.delete(f"{task['id']}/out/analysis/evaluation.md").error
    # 保护区 delete 拒绝
    assert be.delete(f"{task['id']}/formal/art_x/manifest.json").error


def test_read_paths_not_blocked(backend):
    """读不拦：包内部文件 read 走正常读语义（不存在报 not found，而非写入拒绝）。"""
    be, task, conv = backend
    target = f"{task['id']}/formal/art_x/current/content.json"
    r = be.read(target)
    assert r.error and "写入被拒绝" not in r.error
    r2 = be.read(f"{task['id']}/threads/{conv['id']}/art_y/manifest.json")
    assert r2.error and "写入被拒绝" not in r2.error


def test_protect_predicate_direct():
    """_is_protected 段匹配规则直测（含 threads 下的非包路径不拦）。"""
    assert fs_guard._is_protected(("t1", "formal", "art_x", "current", "content.json"))
    assert fs_guard._is_protected(("skills", "tender-analysis", "SKILL.md"))
    assert fs_guard._is_protected(("t1", "threads", "c1", "art_y", "manifest.json"))
    # threads 下非包路径（未来 scratch 扩展位）不拦
    assert not fs_guard._is_protected(("t1", "threads", "c1", "scratch", "note.md"))
    # 工作台/草稿/上传区不拦
    assert not fs_guard._is_protected(("t1", "out", "analysis", "x.md"))
    assert not fs_guard._is_protected(("t1", "drafts", "r1", "x.json"))
    assert not fs_guard._is_protected(("t1", "files", "招标文件.docx"))
