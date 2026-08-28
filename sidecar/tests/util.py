"""测试工具：P4 起会话必须归属任务，统一「建任务 → 建会话」样板。"""


def create_task(client, title="测试任务"):
    r = client.post("/api/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def create_conversation(client, title="新对话", task=None):
    body = task or create_task(client)
    r = client.post("/api/conversations", json={"task_id": body["task"]["id"], "title": title})
    assert r.status_code == 201, r.text
    return r.json()


def init_env(tmp_path, monkeypatch, data_subdir="data"):
    """DATA_DIR 隔离 + init_db + 建任务与首个会话（§16：发布/解析都需要任务上下文），
    返回 (task, conv)。云端文档解析凭证默认清空（需要时各测试自行 setenv）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / data_subdir))
    monkeypatch.delenv("BAIDU_OCR_API_KEY", raising=False)
    monkeypatch.delenv("BAIDU_OCR_SECRET_KEY", raising=False)
    from app import db

    db.init_db()
    task = db.create_task("测试任务")
    conv = db.create_conversation(task["id"])
    return task, conv


def upload_file(client, task_id, name, content=b"hello", content_type="application/octet-stream"):
    """上传到指定任务的 files/（§16 任务级文件区），断言 201 返回响应体。"""
    r = client.post(
        "/api/files", params={"task_id": task_id}, files={"file": (name, content, content_type)}
    )
    assert r.status_code == 201, r.text
    return r.json()
