"""解析目录键 = 文件名全名（2026-09-17 审计批次②）+ 旧布局（parse/<stem>/）一次性迁移。

背景：目录键原用 stem，`证书.pdf` 与 `证书.docx` 共享 parse/证书/——KB 的 images/
互清、delete rmtree 毁同名兄弟全部产物；素材库 blocks.json/element_map.json 连前缀
都没有、双向污染。迁移规则：单文件组整目录 rename；碰撞组逐文件拆分，共享件拷贝
给各方（历史污染无法归属、谁都不丢），element_map 按文件内记录的 file_name 归属
校验（错主删除，注入侧自动落补跑解析路径）。
"""

import json
from pathlib import Path

import pytest

from app import db
from app.knowledge import ingest, materials_lib, store


@pytest.fixture
def env(tmp_path, monkeypatch):
    from tests.util import init_env

    init_env(tmp_path, monkeypatch)
    yield


def _kb_seed(file_name: str, hash_suffix: str) -> str:
    return db.kb_insert_item(
        file_name=file_name,
        file_hash=f"hash-{hash_suffix}",
        title=file_name,
        ext=file_name.rsplit(".", 1)[-1],
    )["id"]


def _mt_seed(file_name: str, hash_suffix: str) -> str:
    return db.mt_insert_file(file_name=file_name, file_hash=f"hash-{hash_suffix}")["id"]


# ---------- 新布局隔离（同名不同扩展互不干扰） ----------


def test_kb_same_stem_isolated(env):
    a, b = "证书.pdf", "证书.docx"
    _kb_seed(a, "a")
    _kb_seed(b, "b")
    for name, text in ((a, "# PDF 版"), (b, "# DOCX 版")):
        md, _, _, _ = store.kb_parse_paths(name)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(text, encoding="utf-8")
        store.kb_images_dir(name).mkdir(parents=True, exist_ok=True)
        (store.kb_images_dir(name) / "img_001.png").write_bytes(b"png")
    # 目录级隔离：删一条不毁另一条（旧布局 rmtree 会连带毁掉兄弟的 md+图）
    store.delete_item_files(a)
    md_b, _, _, _ = store.kb_parse_paths(b)
    assert md_b.read_text(encoding="utf-8") == "# DOCX 版"
    assert (store.kb_images_dir(b) / "img_001.png").is_file()
    assert not store.kb_parse_dir(a).exists()


def test_mt_same_stem_blocks_isolated(env):
    a, b = "历史标书.docx", "历史标书.pdf"
    fid_a, fid_b = _mt_seed(a, "a"), _mt_seed(b, "b")
    for fid, name, title in ((fid_a, a, "docx 的块"), (fid_b, b, "pdf 的块")):
        md, outline, _ = materials_lib.mt_parse_paths(name)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(f"# {name}", encoding="utf-8")
        outline.write_text("[]", encoding="utf-8")
        materials_lib.write_blocks(fid, [{"id": f"blk_{name}", "title": title, "ranges": [[1, 2]]}])
    assert materials_lib.read_blocks(fid_a) != materials_lib.read_blocks(fid_b)
    assert materials_lib.read_blocks(fid_a)[0]["title"] == "docx 的块"
    assert materials_lib.read_blocks(fid_b)[0]["title"] == "pdf 的块"


# ---------- 旧布局一次性迁移 ----------


def _old_kb_layout(stem: str, names_with_md: list[str], images: bool = True):
    old = store.kb_parse_root() / stem
    old.mkdir(parents=True, exist_ok=True)
    for name in names_with_md:
        (old / f"{name}.md").write_text(f"# {name}", encoding="utf-8")
        (old / f"{name}.outline.json").write_text("[]", encoding="utf-8")
    if images:
        img = old / "images"
        img.mkdir(exist_ok=True)
        (img / "img_001.png").write_bytes(b"png")


def test_migrate_kb_single_group(env):
    _kb_seed("年度报告.pdf", "r")
    _old_kb_layout("年度报告", ["年度报告.pdf"])
    stats = ingest.migrate_parse_dir_layout()
    assert stats["renamed"] == 1
    md, outline, _, _ = store.kb_parse_paths("年度报告.pdf")
    assert md.read_text(encoding="utf-8") == "# 年度报告.pdf"
    assert outline.is_file()
    assert not (store.kb_parse_root() / "年度报告").exists()
    # 幂等：重跑无副作用
    again = ingest.migrate_parse_dir_layout()
    assert again["renamed"] == 0 and again["split"] == 0
    assert md.read_text(encoding="utf-8") == "# 年度报告.pdf"


def test_migrate_kb_collision_splits_and_copies_images(env):
    a, b = "证书.pdf", "证书.docx"
    _kb_seed(a, "a")
    _kb_seed(b, "b")
    _old_kb_layout("证书", [a, b])  # 共享旧目录：两份 md 共存 + 共享 images/
    stats = ingest.migrate_parse_dir_layout()
    assert stats["split"] == 2 and stats["conflicts"] == ["证书"]
    md_a, _, _, _ = store.kb_parse_paths(a)
    md_b, _, _, _ = store.kb_parse_paths(b)
    # 各自 md 完好（带前缀产物本就可共存，迁移按文件归位）
    assert md_a.read_text(encoding="utf-8") == f"# {a}"
    assert md_b.read_text(encoding="utf-8") == f"# {b}"
    # 共享 images 拷贝给各方（历史互清无法归属，谁都不丢）
    assert (store.kb_images_dir(a) / "img_001.png").is_file()
    assert (store.kb_images_dir(b) / "img_001.png").is_file()
    assert not (store.kb_parse_root() / "证书").exists()
    # 幂等
    ingest.migrate_parse_dir_layout()
    assert md_a.read_text(encoding="utf-8") == f"# {a}"


def test_migrate_mt_collision_element_map_attribution(env):
    a, b = "运维方案.docx", "运维方案.pdf"
    fid_a, fid_b = _mt_seed(a, "a"), _mt_seed(b, "b")
    from app import config as cfg

    old = cfg.materials_dir() / "parse" / "运维方案"
    old.mkdir(parents=True, exist_ok=True)
    for name in (a, b):
        (old / f"{name}.md").write_text(f"# {name}", encoding="utf-8")
        (old / f"{name}.outline.json").write_text("[]", encoding="utf-8")
    (old / "blocks.json").write_text(
        json.dumps({"version": 1, "blocks": [{"id": "blk_x", "title": "共享块", "ranges": [[1, 2]]}]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    # element_map 记录的归属是 a（docx 才有元素映射；b 是 pdf）
    (old / "element_map.json").write_text(
        json.dumps({"version": 2, "file_name": a, "element_lines": [[0, 1, 2]]}, ensure_ascii=False),
        encoding="utf-8",
    )
    stats = materials_lib.migrate_parse_dir_layout()
    assert stats["split"] == 2 and stats["conflicts"] == ["运维方案"]
    # blocks.json 拷贝给各方（内容保留，污染留给用户清理）
    assert materials_lib.read_blocks(fid_a) and materials_lib.read_blocks(fid_b)
    # element_map 只留在归属方；错主拷贝被移除（read_element_map → None → 补跑解析路径）
    assert materials_lib.read_element_map(a) is not None
    assert materials_lib.read_element_map(b) is None
    md_b, _, _ = materials_lib.mt_parse_paths(b)
    assert md_b.read_text(encoding="utf-8") == f"# {b}"
    assert not (cfg.materials_dir() / "parse" / "运维方案").exists()
    # 幂等
    materials_lib.migrate_parse_dir_layout()
    assert materials_lib.read_element_map(a) is not None


def test_migrate_new_layout_untouched(env):
    """新布局（parse/<文件名>/）与无扩展名文件名：迁移天然跳过，不误动。"""
    _kb_seed("说明.pdf", "s")
    _kb_seed("无扩展名", "n")
    md, _, _, _ = store.kb_parse_paths("说明.pdf")
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("# 已是新布局", encoding="utf-8")
    stats = ingest.migrate_parse_dir_layout()
    assert stats["renamed"] == 0 and stats["split"] == 0
    assert md.read_text(encoding="utf-8") == "# 已是新布局"


# ---------- 收尾 rmtree 双守卫（2026-09-17 复审收尾） ----------


def test_migrate_collision_with_extensionless_keeps_own_dir(env):
    """无扩展名文件名恰与兄弟 stem 相同（上传边界已拒此形态，仅远古遗留可达）：
    其新目录=旧目录本身，守卫后原地保留，不被收尾 rmtree 误删自己的产物。"""
    a, b = "证书.pdf", "证书"
    _kb_seed(a, "a")
    _kb_seed(b, "b")
    old = store.kb_parse_root() / "证书"
    old.mkdir(parents=True)
    (old / f"{a}.md").write_text(f"# {a}", encoding="utf-8")
    (old / f"{b}.md").write_text(f"# {b}", encoding="utf-8")  # 无扩展名成员自己的产物
    img = old / "images"
    img.mkdir()
    (img / "img_001.png").write_bytes(b"png")
    stats = ingest.migrate_parse_dir_layout()
    assert stats["conflicts"] == ["证书"]
    # pdf 成员照常拆分出去（md + 共享 images 拷贝）
    md_a, _, _, _ = store.kb_parse_paths(a)
    assert md_a.read_text(encoding="utf-8") == f"# {a}"
    assert (store.kb_images_dir(a) / "img_001.png").is_file()
    # 无扩展名成员：自己的产物原地保留（rmtree 守卫点）
    md_b, _, _, _ = store.kb_parse_paths(b)
    assert md_b.read_text(encoding="utf-8") == f"# {b}"
    # 幂等：重跑不误动（旧目录=无扩展名成员的最终目录，每次重跑都走碰撞组
    # no-op 拆分后保留——split 计数非零是预期，数据无损才是断言点）
    ingest.migrate_parse_dir_layout()
    assert md_a.read_text(encoding="utf-8") == f"# {a}"
    assert md_b.read_text(encoding="utf-8") == f"# {b}"


def test_migrate_move_failure_keeps_old_dir(env, monkeypatch):
    """搬移失败不删旧目录（原实现 _move_into 吞异常 + 随后 rmtree 会删掉没搬走的
    产物）：rename 注入失败 → 整组保留；恢复后重跑幂等收敛。"""
    a, b = "证书.pdf", "证书.docx"
    _kb_seed(a, "a")
    _kb_seed(b, "b")
    _old_kb_layout("证书", [a, b])
    real_rename = Path.rename

    def flaky_rename(self, target):
        if self.name == f"{a}.md":
            raise OSError("injected rename failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)
    stats = ingest.migrate_parse_dir_layout()
    assert stats["conflicts"] == ["证书"]
    # 失败方产物留在旧目录（未被 rmtree 连带删掉），成功方照常归位
    old = store.kb_parse_root() / "证书"
    assert (old / f"{a}.md").read_text(encoding="utf-8") == f"# {a}"
    md_b, _, _, _ = store.kb_parse_paths(b)
    assert md_b.read_text(encoding="utf-8") == f"# {b}"
    # 恢复 rename 后重跑：残留产物归位、旧目录收走（幂等收敛）
    monkeypatch.setattr(Path, "rename", real_rename)
    ingest.migrate_parse_dir_layout()
    md_a, _, _, _ = store.kb_parse_paths(a)
    assert md_a.read_text(encoding="utf-8") == f"# {a}"
    assert not old.exists()
