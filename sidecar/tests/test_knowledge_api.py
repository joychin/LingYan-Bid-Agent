"""知识库 API（v3 章节块模型）：上传归一/role 过滤/能力档位/说明/章节块端点/
排除开关/重建章节/确认/图片清单/全局视图。"""

import io
import json


def _upload(client, name: str, content: bytes):
    return client.post(
        "/api/kb/files",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )


def _types(client):
    return {t["code"]: t for t in client.get("/api/kb/types").json()["types"]}


def _wait_ready(client, kid: str, timeout_s: float = 5.0):
    """等后台入库管线收敛（TestClient 里 fire-and-forget 会跨请求执行）。"""
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        item = client.get(f"/api/kb/items/{kid}").json()
        if item.get("parse_status") in ("ready", "failed"):
            return item
        time.sleep(0.05)
    raise AssertionError("入库管线 5s 内未收敛")


def test_upload_no_bucket_param(client):
    """上传归一：不带任何分类参数；响应无 bucket。"""
    r = _upload(client, "a.txt", b"# t\n\ncontent")
    assert r.status_code == 201
    assert set(r.json()) == {"id", "file_name", "size"}


def test_types_payload_roles(client):
    types = _types(client)
    assert types["past_proposal"]["role"] == "writing"
    assert types["financial_report"]["role"] == "fact"
    assert "decompose" not in types["past_proposal"]  # 策略字段已删（role 驱动）
    assert "field_labels" in client.get("/api/kb/types").json()


def test_items_role_filter_and_capability(client):
    from app import db

    _upload(client, "证书.txt", b"# c\n\ncontent")
    _upload(client, "标书范文.txt", b"# s\n\ncontent")
    db.kb_update_item(
        next(it["id"] for it in db.kb_list_items() if it["file_name"] == "标书范文.txt"),
        doc_type="past_proposal",
    )
    # role 过滤（分组视图）
    writing = client.get("/api/kb/items", params={"role": "writing"}).json()["items"]
    assert [it["file_name"] for it in writing] == ["标书范文.txt"]
    assert writing[0]["role"] == "writing"
    fact = client.get("/api/kb/items", params={"role": "fact"}).json()["items"]
    assert all(it["role"] == "fact" for it in fact)
    # 能力档位（素材分离后无 enriched 档）；无素材字段
    assert all(it["capability"] in ("stored", "searchable", "typed") for it in fact + writing)
    assert all("material_count" not in it for it in fact + writing)
    # 素材端点已随素材分离删除
    assert client.get("/api/kb/materials").status_code in (404, 405)


def test_item_statement_and_freshness(client):
    from app import db

    r = _upload(client, "老证书.txt", b"# c\n\ncontent")
    kid = r.json()["id"]
    _wait_ready(client, kid)
    db.kb_update_item(kid, doc_type="qualification_certificate", parse_status="ready",
                      extract_status="done", suggested_metadata=json.dumps({
                          "doc_type": "qualification_certificate",
                          "statement": "ISO 认证，有效期至 2020-01-01（第1页）。",
                          "fields": {"valid_until": {"value": "2020-01-01", "source": "第1页"}},
                      }, ensure_ascii=False))
    item = next(it for it in client.get("/api/kb/items").json()["items"] if it["id"] == kid)
    assert item["capability"] == "typed"
    assert "ISO 认证" in item["suggested"]["statement"]
    assert {f["kind"] for f in item["freshness"]} == {"expired"}


def test_content_meta_image_count(client):
    from app.knowledge.ingest import run_ingest

    body = "# 概况\n\n" + "正文内容补充。" * 30
    r = _upload(client, "meta.txt", body.encode())
    run_ingest(r.json()["id"])
    meta = client.get(f"/api/kb/items/{r.json()['id']}/content").json()["meta"]
    assert meta["conversion"] == "txt-passthrough" and meta["chars"] > 0


def test_kb_materials_endpoints_removed(client):
    """素材分离：知识库侧素材端点全部删除（素材域在 /api/materials）。"""
    r = _upload(client, "x.txt", b"# x\n\ncontent")
    kid = r.json()["id"]
    assert client.get(f"/api/kb/items/{kid}/materials").status_code in (404, 405)
    assert client.post(f"/api/kb/items/{kid}/decompose").status_code in (404, 405)
    assert client.put(f"/api/kb/items/{kid}/materials/m/excluded", json={"excluded": True}).status_code in (404, 405)


def test_materials_files_api_flow(client):
    """素材域 API 全流程：上传→解析→目录树→建块（多区间）→列表→改备注→删块→删文件。"""
    import hashlib
    import time

    body = "# 一、方案\n\n" + "\n".join(f"运维服务方案内容文本第{i}行补充说明。" for i in range(20))
    r = client.post(
        "/api/materials/files",
        files={"file": ("库标书.md", body.encode(), "application/octet-stream")},
    )
    assert r.status_code == 201
    fid = r.json()["id"]
    # 同 hash 重复上传 → 409
    dup = client.post(
        "/api/materials/files",
        files={"file": ("库标书.md", body.encode(), "application/octet-stream")},
    )
    assert dup.status_code == 409

    # 解析收敛（TestClient 后台任务跨请求执行）
    deadline = time.time() + 5
    while time.time() < deadline:
        outline = client.get(f"/api/materials/files/{fid}/outline").json()
        if outline["parse_status"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    assert outline["parse_status"] == "ready"
    assert outline["outline"] and outline["outline"][0]["标题"] == "一、方案"

    # 建块：多区间（勾两段不连续区间——用树区间与手造区间）
    block = client.post(
        f"/api/materials/files/{fid}/blocks",
        json={"title": "运维方案块", "note": "政务云运维", "ranges": [[1, 5], [10, 15]]},
    )
    assert block.status_code == 201
    bid = block.json()["id"]
    assert block.json()["ranges"] == [[1, 5], [10, 15]] and block.json()["chars"] > 0
    # 非法 ranges → 422
    assert client.post(
        f"/api/materials/files/{fid}/blocks",
        json={"title": "x", "note": "", "ranges": []},
    ).status_code == 422

    # 文件列表带块数；块列表带来源文件
    files = client.get("/api/materials/files").json()["files"]
    assert next(f for f in files if f["id"] == fid)["block_count"] == 1
    blocks = client.get("/api/materials/blocks").json()["blocks"]
    assert blocks[0]["file_name"] == "库标书.md" and blocks[0]["note"] == "政务云运维"

    # 改备注 → 删块 → 删文件（连带）
    assert client.put(f"/api/materials/blocks/{bid}", json={"note": "改后备注"}).json()["note"] == "改后备注"
    assert client.delete(f"/api/materials/blocks/{bid}").status_code == 200
    assert client.get("/api/materials/blocks").json()["blocks"] == []
    assert client.delete(f"/api/materials/files/{fid}").status_code == 200
    assert client.get("/api/materials/files").json()["files"] == []
    assert hashlib.sha256(b"gone")  # 保持 import 使用


def test_materials_reparse_file(client):
    """reparse 端点：失败文件重试恢复 + 404 不存在 + 409 正在解析（单飞）。"""
    import time

    from app import db
    from app.knowledge import materials_lib as mlib

    body = "# 一、方案\n\n" + "素材重试路径内容补充。" * 10
    r = client.post(
        "/api/materials/files",
        files={"file": ("重试标书.md", body.encode(), "application/octet-stream")},
    )
    fid = r.json()["id"]

    def _wait_terminal(left: str | None = None) -> dict:
        """等后台解析收敛；left=须先观察到离开的旧状态（防 reparse 任务未启动
        就读到重跑前的终态快照）。"""
        deadline = time.time() + 5
        while time.time() < deadline:
            f = db.mt_get_file(fid)
            if left is not None:
                if f["parse_status"] == left:
                    time.sleep(0.05)
                    continue
                left = None
            if f["parse_status"] in ("ready", "failed"):
                return f
            time.sleep(0.05)
        raise AssertionError("解析 5s 内未收敛")

    assert _wait_terminal()["parse_status"] == "ready"

    # 模拟历史失败（如解析程序 bug）→ reparse 恢复
    db.mt_update_file(fid, parse_status="failed", error="解析失败：name 'qn' is not defined")
    rr = client.post(f"/api/materials/files/{fid}/reparse")
    assert rr.status_code == 202 and rr.json() == {"ok": True}
    f = _wait_terminal(left="failed")
    assert f["parse_status"] == "ready" and f["error"] is None

    # 404 不存在；409 单飞——真实形态=parse_status=parsing + in-flight 标记双条件
    # （只剩标记而状态已终态=收尾调度窗口的陈旧标记，schedule_parse 自愈放行；
    #  2026-09-08 全量套件负载下实测该窗口曾致本测试偶发 409/202 竞态）
    assert client.post("/api/materials/files/mt_nope/reparse").status_code == 404
    db.mt_update_file(fid, parse_status="parsing", error=None)
    mlib._inflight.add(fid)
    try:
        assert client.post(f"/api/materials/files/{fid}/reparse").status_code == 409
    finally:
        mlib._inflight.discard(fid)
        db.mt_update_file(fid, parse_status="ready", error=None)


def test_item_images_listing(client):
    """图片清单端点：内容页折叠区数据源（图片仅供查看，与素材无关）。"""
    from app.knowledge import store

    r = _upload(client, "无图.txt", b"# t\n\ncontent")
    kid = r.json()["id"]
    data = client.get(f"/api/kb/items/{kid}/images").json()
    assert data["images"] == []
    # 造两张盘上图片（绕过抽取，聚焦端点）
    img_dir = store.kb_images_dir("无图.txt")
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "img_001.png").write_bytes(b"\x89PNG-fake")
    (img_dir / "img_002.png").write_bytes(b"\x89PNG-fake2")
    imgs = client.get(f"/api/kb/items/{kid}/images").json()["images"]
    assert [i["name"] for i in imgs] == ["img_001.png", "img_002.png"]
    assert imgs[0]["size"] == len(b"\x89PNG-fake")


def test_metadata_confirm_with_statement(client):
    from app import db

    r = _upload(client, "范文2.txt", b"# s\n\ncontent")
    kid = r.json()["id"]
    _wait_ready(client, kid)
    db.kb_update_item(kid, parse_status="ready", doc_type="other")

    ok = client.put(
        f"/api/kb/items/{kid}/metadata",
        json={"doc_type": "past_proposal",
              "statement": "共 3 章技术标。",
              "fields": {"project_name": "某园区项目"},
              "extra": {"来源": "2024 中标项目"}},
    )
    assert ok.status_code == 200
    data = ok.json()
    assert data["review_status"] == "confirmed" and data["role"] == "writing"
    assert data["business"]["statement"] == "共 3 章技术标。"


def test_metadata_confirm_with_questions(client):
    """PUT 检索问题：落 business + §questions 段可检中；坏形状/超长/超条数 422。"""
    from app import db
    from app.knowledge import fts

    r = _upload(client, "医院合同.txt", "# 合同\n\nXX医院智慧后勤平台项目，金额 380 万元。".encode("utf-8"))
    kid = r.json()["id"]
    _wait_ready(client, kid)
    db.kb_update_item(kid, parse_status="ready", doc_type="contract_case")

    ok = client.put(
        f"/api/kb/items/{kid}/metadata",
        json={"doc_type": "contract_case",
              "statement": "XX 医院智慧后勤平台合同（第1页）。",
              "questions": ["做过哪些医疗行业项目？", " 合同金额多大？ ", ""]},
    )
    assert ok.status_code == 200
    data = ok.json()
    assert data["business"]["questions"] == ["做过哪些医疗行业项目？", "合同金额多大？"]
    hits = db.kb_search_segments(fts.build_match_expr("医疗行业"), limit=5)
    assert any(h["item_id"] == kid and h.get("section_path") == "§questions" for h in hits)

    assert client.put(
        f"/api/kb/items/{kid}/metadata",
        json={"doc_type": "contract_case", "questions": "不是数组"},
    ).status_code == 422
    assert client.put(
        f"/api/kb/items/{kid}/metadata",
        json={"doc_type": "contract_case", "questions": ["超" * 41]},
    ).status_code == 422
    assert client.put(
        f"/api/kb/items/{kid}/metadata",
        json={"doc_type": "contract_case", "questions": [f"问题{i}" for i in range(11)]},
    ).status_code == 422


def test_delete_and_badge(client):
    r = _upload(client, "gone.txt", b"# g\n\ndel")
    kid = r.json()["id"]
    assert client.delete(f"/api/kb/items/{kid}").status_code == 200
    assert client.get(f"/api/kb/items/{kid}").status_code == 404
    assert client.get("/api/kb/badge").json() == {"pending": 0}


def test_materials_content_search_usage_flow(client):
    """完善批端点：块内容分节 / ?q= 正文检索 / outline 字数 / 引用打点透出。"""
    import time

    body = "# 一、方案\n\n" + "\n".join(f"等保合规建设内容第{i}行补充。" for i in range(20))
    fid = client.post(
        "/api/materials/files",
        files={"file": ("完善标书.md", body.encode(), "application/octet-stream")},
    ).json()["id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        outline = client.get(f"/api/materials/files/{fid}/outline").json()
        if outline["parse_status"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    assert outline["parse_status"] == "ready"
    assert outline["outline"][0]["chars"] > 0

    bid = client.post(
        f"/api/materials/files/{fid}/blocks",
        json={"title": "等保块", "note": "安全写法", "ranges": [[1, 6]]},
    ).json()["id"]

    # 块内容：分节区间 + 正文；不存在 404
    content = client.get(f"/api/materials/blocks/{bid}/content").json()
    assert content["sections"][0]["start"] == 1
    assert "等保合规建设内容" in content["sections"][0]["text"]
    assert client.get("/api/materials/blocks/blk_none/content").status_code == 404

    # ?q=：正文 FTS 命中（「建设内容」只在正文里）∪ 标题命中；无命中空表
    assert [b["id"] for b in client.get("/api/materials/blocks?q=建设内容").json()["blocks"]] == [bid]
    assert [b["id"] for b in client.get("/api/materials/blocks?q=等保块").json()["blocks"]] == [bid]
    assert client.get("/api/materials/blocks?q=绝不存在的词xyzzy").json()["blocks"] == []

    # 引用打点透出
    from app import db

    db.mt_touch_blocks([bid])
    row = next(b for b in client.get("/api/materials/blocks").json()["blocks"] if b["id"] == bid)
    assert row["use_count"] == 1 and row["last_used_at"]

    assert client.delete(f"/api/materials/files/{fid}").status_code == 200


def test_check_result_passthrough_and_human_confirm_marker(client):
    """核对结果随条目下发（解析后的 JSON）；PUT 人工确认后 business 无 auto 标记。"""
    from app import db

    r = _upload(client, "核对证书.txt", b"# c\n\ncontent")
    kid = r.json()["id"]
    _wait_ready(client, kid)
    db.kb_update_item(
        kid, parse_status="ready", extract_status="done",
        doc_type="qualification_certificate",
        suggested_metadata=json.dumps({
            "doc_type": "qualification_certificate",
            "fields": {"valid_until": {"value": "2099-01-01"}},
        }, ensure_ascii=False),
        check_result=json.dumps({
            "status": "fail",
            "results": [{"field": "valid_until", "label": "有效期至",
                         "ok": False, "detail": "未在原文找到该日期——疑似抽取有误，请核对"}],
        }, ensure_ascii=False),
    )
    item = next(it for it in client.get("/api/kb/items").json()["items"] if it["id"] == kid)
    assert item["review_status"] == "pending_review"
    assert item["check_result"]["status"] == "fail"
    assert "未在原文找到该日期" in item["check_result"]["results"][0]["detail"]

    ok = client.put(f"/api/kb/items/{kid}/metadata",
                    json={"doc_type": "qualification_certificate",
                          "fields": {"valid_until": "2028-06-30"}})
    assert ok.status_code == 200
    data = ok.json()
    assert data["review_status"] == "confirmed"
    assert data["business"].get("confirmed_by") is None  # 人工语义：无 auto 标记
