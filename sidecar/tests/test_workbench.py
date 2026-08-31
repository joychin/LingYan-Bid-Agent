"""workbench API：out/ 工作台 列表/读取/编辑（409+force+修订标记+.bak 恢复）/存为笔记。

工作台不是 Artifact（无索引无事件）；parse/ 只读；写走探测+裁决+恢复点兜底。
"""



from app import artifact_store
from tests.util import create_task


def _seed_out(task_id: str, rel: str, text: str) -> None:
    p = artifact_store.work_dir(task_id) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_list_filters_and_flags(client):
    task = create_task(client)["task"]
    tid = task["id"]
    _seed_out(tid, "analysis/disqualification.md", "<!-- tender-analysis | 节=disqualification | 生成=2026-08-28T00:00:00+00:00 -->\n| 1 | 逾期 | 高 |")
    _seed_out(tid, "analysis/structure.md", "<!-- tender-analysis | 节=structure | 生成=2026-08-28T00:00:00+00:00 -->\n| 项目名称 | 测试 |")
    _seed_out(tid, "parse/招标文件.docx/招标文件.docx.md", "# 招标文件\n正文")
    _seed_out(tid, "parse/招标文件.docx/招标文件.docx.outline.json", "[]")
    _seed_out(tid, "outline/fragments/.hidden.md", "x")

    r = client.get("/api/workbench", params={"task_id": tid})
    assert r.status_code == 200
    files = {f["path"]: f for f in r.json()["files"]}
    # json/隐藏文件不进列表；md 全进
    assert set(files) == {
        "analysis/disqualification.md",
        "analysis/structure.md",
        "parse/招标文件.docx/招标文件.docx.md",
    }
    assert files["parse/招标文件.docx/招标文件.docx.md"]["editable"] is False
    assert files["analysis/disqualification.md"]["editable"] is True
    assert files["analysis/disqualification.md"]["revised"] is False
    assert "mtime" in files["analysis/structure.md"] and "size" in files["analysis/structure.md"]


def test_read_and_containment(client):
    task = create_task(client)["task"]
    tid = task["id"]
    _seed_out(tid, "analysis/evaluation.md", "<!-- x -->\n内容")
    r = client.get("/api/workbench/content", params={"task_id": tid, "path": "analysis/evaluation.md"})
    assert r.status_code == 200
    d = r.json()
    assert d["content"].startswith("<!-- x -->")
    assert len(d["hash"]) == 64 and d["editable"] is True and d["has_backup"] is False

    # 越界（../ 逃出 out/）与非 md 一律 404
    for bad in ("../files/a.md", "analysis/../../x.md", "analysis/x.json", "nope.md"):
        rr = client.get("/api/workbench/content", params={"task_id": tid, "path": bad})
        assert rr.status_code == 404, bad


def test_write_stamps_revised_and_conflict(client):
    task = create_task(client)["task"]
    tid = task["id"]
    _seed_out(tid, "analysis/structure.md", "<!-- tender-analysis | 节=structure | 生成=2026-08-28T00:00:00+00:00 -->\n旧内容\n")

    base = client.get("/api/workbench/content", params={"task_id": tid, "path": "analysis/structure.md"}).json()

    # base_hash 过期 → 409
    r = client.put(
        "/api/workbench/content",
        json={"task_id": tid, "path": "analysis/structure.md", "content": "用户改的\n", "base_hash": "0" * 64},
    )
    assert r.status_code == 409

    # 正确 base → 成功 + 修订标记盖进首行注释 + .bak 留底
    # （编辑器保存全量内容——含原头部行，故头部保留、标记追加其内）
    edited = "<!-- tender-analysis | 节=structure | 生成=2026-08-28T00:00:00+00:00 -->\n用户改的\n"
    r = client.put(
        "/api/workbench/content",
        json={"task_id": tid, "path": "analysis/structure.md", "content": edited, "base_hash": base["hash"]},
    )
    assert r.status_code == 200
    d = client.get("/api/workbench/content", params={"task_id": tid, "path": "analysis/structure.md"}).json()
    first = d["content"].splitlines()[0]
    assert first.startswith("<!--") and "修订=用户" in first and "节=structure" in first
    assert d["revised"] is True and d["has_backup"] is True
    # .bak 不在列表（列表只收 .md；.md.bak 后缀不匹配）
    listed = client.get("/api/workbench", params={"task_id": tid}).json()["files"]
    assert all(not f["path"].endswith(".bak") for f in listed)

    # force 覆盖过期 base 也成功
    r = client.put(
        "/api/workbench/content",
        json={"task_id": tid, "path": "analysis/structure.md", "content": "再改\n", "base_hash": "0" * 64, "force": True},
    )
    assert r.status_code == 200

    # 无注释头的文件：前插一行注释
    _seed_out(tid, "outline/fragments/技术标.md", "- 封面\n- 目录\n")
    r = client.put(
        "/api/workbench/content",
        json={"task_id": tid, "path": "outline/fragments/技术标.md", "content": "- 封面\n", "base_hash": "0" * 64, "force": True},
    )
    assert r.status_code == 200
    d = client.get("/api/workbench/content", params={"task_id": tid, "path": "outline/fragments/技术标.md"}).json()
    assert d["content"].splitlines()[0].startswith("<!-- 工作文件 | 修订=用户")
    assert d["content"].splitlines()[1] == "- 封面"


def test_parse_readonly(client):
    task = create_task(client)["task"]
    tid = task["id"]
    _seed_out(tid, "parse/a.pdf/a.pdf.md", "# 原文")
    r = client.put(
        "/api/workbench/content",
        json={"task_id": tid, "path": "parse/a.pdf/a.pdf.md", "content": "篡改", "base_hash": "0" * 64, "force": True},
    )
    assert r.status_code == 403
    assert "只读" in r.json()["detail"]


def test_restore_roundtrip(client):
    task = create_task(client)["task"]
    tid = task["id"]
    _seed_out(tid, "analysis/evaluation.md", "<!-- x -->\n版本1\n")
    h1 = client.get("/api/workbench/content", params={"task_id": tid, "path": "analysis/evaluation.md"}).json()["hash"]
    client.put("/api/workbench/content", json={"task_id": tid, "path": "analysis/evaluation.md", "content": "<!-- x -->\n版本2\n", "base_hash": h1})

    r = client.post("/api/workbench/restore", json={"task_id": tid, "path": "analysis/evaluation.md"})
    assert r.status_code == 200
    d = client.get("/api/workbench/content", params={"task_id": tid, "path": "analysis/evaluation.md"}).json()
    assert "版本1" in d["content"]

    # 恢复可再撤销：再 restore 回版本2（互换语义）
    r = client.post("/api/workbench/restore", json={"task_id": tid, "path": "analysis/evaluation.md"})
    d = client.get("/api/workbench/content", params={"task_id": tid, "path": "analysis/evaluation.md"}).json()
    assert "版本2" in d["content"]

    # 无 .bak → 409
    _seed_out(tid, "analysis/structure.md", "无备份文件\n")
    assert client.post("/api/workbench/restore", json={"task_id": tid, "path": "analysis/structure.md"}).status_code == 409


def test_save_as_note(client):
    task, conv = None, None
    rr = client.post("/api/tasks", json={"title": "任务A"})
    task = rr.json()["task"]
    conv = rr.json()["conversation"]
    tid = task["id"]
    _seed_out(tid, "analysis/disqualification.md", "<!-- tender-analysis | 节=disqualification -->\n| 1 | 逾期 | 高 |")

    r = client.post(
        "/api/workbench/note",
        json={"conversation_id": conv["id"], "path": "analysis/disqualification.md"},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["artifact_id"]
    assert r.json()["display_name"].startswith("工作文件快照 · disqualification")

    # 落在会话作用域（过程稿）、kind=doc.note、可读
    rows = client.get("/api/artifacts", params={"conversation_id": conv["id"]}).json()["artifacts"]
    row = next(a for a in rows if a["artifact_id"] == aid)
    assert row["kind"] == "doc.note" and row["display_name"].startswith("工作文件快照")

    # 自定义 title
    r2 = client.post(
        "/api/workbench/note",
        json={"conversation_id": conv["id"], "path": "analysis/disqualification.md", "title": "废标清单定稿"},
    )
    assert r2.status_code == 201
    assert r2.json()["display_name"] == "废标清单定稿"
