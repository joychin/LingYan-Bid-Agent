"""GuardedBackend 写路径黑名单（P0.3 → 2026-08-31 两态重构）。

边界：只拦写（write/edit/delete），read/ls/grep/glob 完全放开；
work/ 下过程文件（parse/analysis/outline/body）正常可写；产物包（work/artifacts/）、
来源（sources/）、谱系（_meta/，**staging/ 草稿区豁免**——两步发布流的模型写入点）、
归档、技能目录、旧布局遗留段（formal/threads）拦写。
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


def test_write_rejects_artifact_package(backend):
    be, task, _ = backend
    r = be.write(f"{task['id']}/work/artifacts/art_x/content.json", "{}")
    assert r.error and "写入被拒绝" in r.error
    # meta / 恢复点同样拒写
    assert be.write(f"{task['id']}/work/artifacts/art_x/meta.json", "{}").error
    assert be.write(f"{task['id']}/work/artifacts/art_x/restorepoints/rp1.json", "{}").error


def test_write_rejects_sources_and_meta(backend):
    be, task, _ = backend
    assert be.write(f"{task['id']}/sources/招标文件.docx", "bin").error
    assert be.write(f"{task['id']}/_meta/lineage/art_x.json", "{}").error


def test_write_allows_staging_drafts(backend):
    """_meta/staging/ 豁免：两步发布流的模型草稿区（fs_guard ↔ publish 工具契约）。

    2026-08-31 review 修复：此前 staging 被 _meta 段级命中拦死，而 publish_artifact
    工具指示模型把草稿写到那里——通用发布链路（doc.note 收拢等）在真实 run 里
    完全不可用（测试用 pathlib 直写绕过了守卫，故全绿漏网）。
    """
    be, task, _ = backend
    r = be.write(f"{task['id']}/_meta/staging/toc.json", "{}")
    assert not r.error and r.path
    # 豁口只开 staging：_meta 其余路径照拒（`..` 穿越则由 backend virtual_mode
    # 在段匹配之前就 ValueError 拒绝，无需守卫兜底）
    assert be.write(f"{task['id']}/_meta/restorepoints/rp.json", "{}").error
    assert be.write(f"{task['id']}/_meta/lineage/art_x.json", "{}").error


def test_write_rejects_archive_and_skills(backend):
    be, task, _ = backend
    assert be.write(f"archive/{task['id']}/work/artifacts/art_x/meta.json", "{}").error
    assert be.write("skills/tender-analysis/SKILL.md", "hacked").error
    # 深层 skills 路径段命中同样拒
    assert be.write("skills/tender-outline/references/r1.md", "x").error


def test_write_allows_work_process_files(backend):
    be, task, _ = backend
    ok1 = be.write(f"{task['id']}/work/analysis/structure.md", "# 结构事实")
    assert not ok1.error and ok1.path
    ok2 = be.write(f"{task['id']}/work/parse/a.pdf/a.pdf.md", "# 原文")
    assert not ok2.error
    ok3 = be.write(f"{task['id']}/work/outline/tender-response-docs.md", "- 封面")
    assert not ok3.error
    ok4 = be.write(f"{task['id']}/work/body/商务标.md", "# 正文")
    assert not ok4.error


def test_edit_delete_scoped_to_protected_only(backend):
    be, task, _ = backend
    # 工作过程文件：编辑/删除不受限
    be.write(f"{task['id']}/work/analysis/evaluation.md", "line1\nline2")
    assert not be.edit(f"{task['id']}/work/analysis/evaluation.md", "line1", "line1!").error
    assert not be.delete(f"{task['id']}/work/analysis/evaluation.md").error
    # 保护区 delete 拒绝
    assert be.delete(f"{task['id']}/work/artifacts/art_x/meta.json").error


def test_read_paths_not_blocked(backend):
    """读不拦：包内部文件 read 走正常读语义（不存在报 not found，而非写入拒绝）。"""
    be, task, _ = backend
    target = f"{task['id']}/work/artifacts/art_x/content.json"
    r = be.read(target)
    assert r.error and "写入被拒绝" not in r.error
    r2 = be.read(f"{task['id']}/sources/招标文件.docx")
    assert r2.error and "写入被拒绝" not in r2.error


def test_protect_predicate_direct():
    """_is_protected 段匹配规则直测。"""
    assert fs_guard._is_protected(("t1", "work", "artifacts", "art_x", "content.json"))
    assert fs_guard._is_protected(("skills", "tender-analysis", "SKILL.md"))
    assert fs_guard._is_protected(("t1", "sources", "招标文件.docx"))
    assert fs_guard._is_protected(("t1", "_meta", "lineage", "x.json"))
    assert fs_guard._is_protected(("t1", "_meta", "restorepoints", "rp.json"))
    # staging 豁免：两步发布流的模型草稿区
    assert not fs_guard._is_protected(("t1", "_meta", "staging", "x.json"))
    assert not fs_guard._is_protected(("t1", "_meta", "staging"))
    # 旧布局遗留段防御性拒写
    assert fs_guard._is_protected(("t1", "formal", "art_x", "manifest.json"))
    assert fs_guard._is_protected(("t1", "threads", "c1", "art_x", "manifest.json"))
    # work 下过程文件不拦（artifacts 段前是 work 才拦）
    assert not fs_guard._is_protected(("t1", "work", "analysis", "x.md"))
    assert not fs_guard._is_protected(("t1", "work", "parse", "a.pdf", "a.pdf.md"))
    assert not fs_guard._is_protected(("t1", "work", "outline", "toc.md"))
    assert not fs_guard._is_protected(("t1", "work", "body", "正文.md"))
