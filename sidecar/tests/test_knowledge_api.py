"""知识库 API：上传（hash 去重 409）/ badge / 确认表单 / 类型注册表 / 删除。"""

import io


def _upload(client, name: str, content: bytes):
    return client.post(
        "/api/kb/files",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )


def test_upload_and_types(client):
    r = client.get("/api/kb/types")
    assert r.status_code == 200
    types = r.json()["types"]
    assert any(t["code"] == "business_license" for t in types)
    assert r.json()["field_labels"]["uscc"] == "统一社会信用代码"


def test_upload_rejects_doc_and_oversize_name(client):
    assert _upload(client, "a.doc", b"x").status_code == 400
    assert _upload(client, ".hidden", b"x").status_code == 400


def test_upload_dedup_by_hash(client):
    body = b"# x\n\nsome unique content"
    r1 = _upload(client, "a.txt", body)
    assert r1.status_code == 201
    # 同内容不同名 → 409 提示已存在
    r2 = _upload(client, "b.txt", body)
    assert r2.status_code == 409
    assert "已在知识库" in r2.json()["detail"]
    # 不同内容同名 → 加序号后缀入库
    r3 = _upload(client, "a.txt", b"# different content entirely")
    assert r3.status_code == 201
    assert r3.json()["file_name"] != "a.txt"


def test_badge_counts_pending(client):
    assert client.get("/api/kb/badge").json() == {"pending": 0}
    _upload(client, "a.txt", b"# t\n\ncontent")
    assert client.get("/api/kb/badge").json() == {"pending": 1}


def test_confirm_metadata_flow(client):
    import json

    r = _upload(client, "cert.txt", b"# cert\n\nISO9001 content")
    kid = r.json()["id"]

    # 非法类型拒绝
    bad = client.put(f"/api/kb/items/{kid}/metadata", json={"doc_type": "nope", "fields": {}})
    assert bad.status_code == 422

    ok = client.put(
        f"/api/kb/items/{kid}/metadata",
        json={"doc_type": "qualification_certificate", "fields": {"cert_no": "CN-001", "issuer": ""}},
    )
    assert ok.status_code == 200
    data = ok.json()
    assert data["review_status"] == "confirmed"
    assert data["doc_type_name"] == "资质 / 体系证书"
    biz = data["business_metadata"]
    assert biz["fields"]["cert_no"]["value"] == "CN-001"
    assert "issuer" not in biz["fields"]  # 空串字段丢弃

    # badge 归零
    assert client.get("/api/kb/badge").json() == {"pending": 0}

    # 人工字段可检索（元数据段）。段重建与后台入库管线并发（上传 fire-and-forget），
    # 契约是最终一致：确认后若与管线收尾的补重建撞车，人工字段段可能迟几百毫秒
    # 才落上（管线末尾有收敛探测），轮询至收敛。
    import time

    from app import db
    from app.knowledge import fts

    expr = fts.build_match_expr("CN-001")
    deadline = time.time() + 5
    while not db.kb_search_segments(expr, limit=3):
        assert time.time() < deadline, "人工字段段 5s 内未收敛可检索"
        time.sleep(0.05)


def test_items_list_filters(client):
    import json

    r1 = _upload(client, "a.txt", b"# a\n\nx")
    r2 = _upload(client, "b.txt", b"# b\n\ny")
    for kid in (r1.json()["id"], r2.json()["id"]):
        client.put(f"/api/kb/items/{kid}/metadata", json={"doc_type": "other", "fields": {}})
    _upload(client, "c.txt", b"# c\n\nz")
    pend = client.get("/api/kb/items", params={"review_status": "pending_review"}).json()["items"]
    assert [it["file_name"] for it in pend] == ["c.txt"]
    all_items = client.get("/api/kb/items").json()["items"]
    assert all_items[0]["file_name"] == "c.txt"  # 待确认置顶
    q = client.get("/api/kb/items", params={"q": "c.txt"}).json()["items"]
    assert len(q) == 1


def test_delete_item(client):
    r = _upload(client, "gone.txt", b"# g\n\ndel")
    kid = r.json()["id"]
    assert client.delete(f"/api/kb/items/{kid}").status_code == 200
    assert client.get(f"/api/kb/items/{kid}").status_code == 404
    assert client.get("/api/kb/badge").json() == {"pending": 0}


def test_retrigger_accepted(client):
    r = _upload(client, "again.txt", b"# a\n\nx")
    kid = r.json()["id"]
    resp = client.post(f"/api/kb/items/{kid}/retrigger")
    assert resp.status_code == 202
    # 内容端点（未解析完成时为空串，不 500）
    assert client.get(f"/api/kb/items/{kid}/content").status_code == 200


def test_content_returns_parse_meta(client):
    from app.knowledge.ingest import run_ingest

    body = "# 概况\n\n" + "正文内容补充。" * 30
    r = _upload(client, "meta.txt", body.encode())
    kid = r.json()["id"]
    run_ingest(kid)  # TestClient 里 fire-and-forget 任务不执行，同步跑完解析

    data = client.get(f"/api/kb/items/{kid}/content").json()
    meta = data["meta"]
    assert meta is not None
    assert meta["conversion"] == "txt-passthrough"
    assert meta["conversion_label"] == "纯文本"
    assert meta["chars"] > 0
    assert meta["headings"] == 1
    assert meta["warnings"] == []
    assert meta["top_sections"] == ["概况"]
