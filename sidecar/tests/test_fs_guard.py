"""GuardedBackend 写路径黑名单（P0.3 → 2026-08-31 两态重构）+ 二进制读拦截（2026-09-13）
+ 文件变更串行/原子落盘（2026-09-13 并发编辑事故批）。

边界：拦写（write/edit/delete）与拦二进制/图片读（read 按扩展名），文本读与
ls/grep/glob 放开；work/ 下过程文件（parse/analysis/outline/body）正常可写；产物包
（work/artifacts/）、来源（sources/）、谱系（_meta/，**staging/ 草稿区豁免**——两步
发布流的模型写入点）、归档、技能目录、旧布局遗留段（formal/threads）拦写。
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
    r2 = be.read(f"{task['id']}/sources/说明.md")
    assert r2.error and "写入被拒绝" not in r.error


def test_read_refuses_images(backend):
    """图片 read 拒绝（2026-09-13 事故批）：整图 base64 内联≈百万 token 会撑爆上下文。

    事故形态复刻：并行 docx 写坏节文件后，写手 read_file 读知识库抽取图「看一眼」
    → 1,565,843 字符 base64 内联 → 下一次模型调用 1,113,773 token 撞 1M 上限。
    """
    be, task, _ = backend
    from app import config as cfg

    p = cfg.workspace_dir() / "knowledge" / "parse" / "证书(存档)" / "images" / "img_001.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    r = be.read("knowledge/parse/证书(存档)/images/img_001.png")
    assert r.error and "读取被拒绝" in r.error
    assert "docx_image_insert" in r.error  # 拒绝文案必须带正确出口
    # 任务侧/工作区任意位置同口径
    assert be.read(f"{task['id']}/work/body/扫描件.jpg").error


def test_read_refuses_pdf_and_office_with_hints(backend):
    """PDF/Office 二进制读拒绝：文案分别指向 parse_document 与 docx_section_read。"""
    be, task, _ = backend
    r = be.read(f"{task['id']}/sources/招标文件.pdf")
    assert r.error and "读取被拒绝" in r.error and "parse_document" in r.error
    r2 = be.read(f"{task['id']}/work/body/某节.docx")
    assert r2.error and "读取被拒绝" in r2.error and "docx_section_read" in r2.error
    assert be.read(f"{task['id']}/work/body/演示.pptx").error
    # Excel（2026-09-14 补面）：整文件 base64 撞上下文的路同开；当前无解析通道，
    # 文案不得引导模型走不存在的 parse_document/预览出口
    r3 = be.read(f"{task['id']}/sources/分项报价表.xlsx")
    assert r3.error and "读取被拒绝" in r3.error
    assert "parse_document" not in r3.error and "docx_section_read" not in r3.error
    assert be.read(f"{task['id']}/work/analysis/历史报价.xls").error


def test_read_allows_text_unchanged(backend):
    """文本读语义零变化：md/json 照常可读（导航硬纪律依赖）。"""
    be, task, _ = backend
    be.write(f"{task['id']}/work/analysis/a.md", "# 标题\n正文行")
    r = be.read(f"{task['id']}/work/analysis/a.md")
    assert not r.error and "标题" in (r.file_data or {}).get("content", "")


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


# ---------- 文件变更串行 + 原子落盘（2026-09-13 并发编辑事故批） ----------


def test_parallel_edits_same_file_all_survive(backend):
    """并发编辑丢更新的回归哨兵（机制断言）。

    事故形态（真实 run r_f7c2c322ec21 复盘）：模型一 turn 并发 4 条 edit_file 打
    同一 structure.md，上游 read→replace→O_TRUNC 无锁不原子——后写整存覆盖先写
    （丢更新且报成功，old_string 与原文逐字节相等仍假报「String not found」）。
    修法=变更全局串行 + 原子替换；本测试 Barrier 对齐 8 线程同时开火各改一行，
    断言三条：全部成功、8 处修改一条不丢（锁防丢更新）、无 .tmp 残件（原子替换）。
    """
    import contextvars
    import threading

    from app import config as cfg

    be, task, _ = backend
    rel = f"{task['id']}/work/analysis/并发编辑.md"
    lines = [f"| 字段{i} | 旧值 | unknown | 出处 |" for i in range(8)]
    assert not be.write(rel, "\n".join(lines)).error

    n = 8
    barrier = threading.Barrier(n)
    results: list[bool] = []
    rlock = threading.Lock()

    def worker(i: int):
        try:
            barrier.wait(timeout=10)
            r = be.edit(rel, f"| 字段{i} | 旧值 |", f"| 字段{i} | 新值 |")
            ok = not r.error
        except Exception:  # noqa: BLE001
            ok = False
        with rlock:
            results.append(ok)

    # 生产形态：ToolNode 的 ContextThreadPoolExecutor 逐任务拷贝 context——
    # 裸 Thread 不带上下文，须显式 ctx.run（与 test_docx_ops 哨兵同款）
    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(lambda i=i: worker(i),))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(results) == n and all(results), results
    content = be.read(rel).file_data["content"]
    assert content.count("新值") == n  # 8 处修改一条不丢——并行不丢更新
    assert "旧值" not in content
    target = cfg.workspace_dir() / task["id"] / "work" / "analysis" / "并发编辑.md"
    assert not list(target.parent.glob("*.tmp"))  # 原子替换无残件


def test_concurrent_read_never_torn(backend):
    """原子替换防撕裂读：写者高频整存覆盖、读者并发自旋读，任意时刻读到的
    必须是完整的旧版或新版（逐字节等于其一），绝无半截/混杂。

    事故形态=上游 O_TRUNC 截断窗口：读者撞进去读到空/半截文件 → 假
    「String not found」与幽灵残行。读者刻意不上锁（并行热路径），安全性
    全部由 tmp+os.replace 承担。
    """
    import threading

    be, task, _ = backend
    rel = f"{task['id']}/work/analysis/撕裂读.md"
    old_full = "\n".join(f"第{i}行：{'旧' * 40}" for i in range(200))
    new_full = "\n".join(f"第{i}行：{'新' * 40}" for i in range(200))
    assert not be.write(rel, old_full).error

    torn: list[str] = []
    tlock = threading.Lock()
    stop = threading.Event()

    def writer():
        for _ in range(40):
            be.write(rel, new_full)
            be.write(rel, old_full)
        stop.set()

    def reader():
        while not stop.is_set():
            r = be.read(rel)
            content = (r.file_data or {}).get("content")
            if content is not None and content != old_full and content != new_full:
                with tlock:
                    torn.append(content[:80])

    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start()
    tr.start()
    tw.join(timeout=30)
    tr.join(timeout=10)

    assert not torn, f"读到撕裂内容 {len(torn)} 次，首例：{torn[0] if torn else ''}"
