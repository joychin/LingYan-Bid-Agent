"""db：崩溃残留 running run 的恢复 + 每会话单 run 守卫。"""

import pytest

from app import db


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    return tmp_path


def test_recover_stale_runs(db_env):
    cid = db.create_conversation("t")["id"]
    db.create_run(cid)
    assert db.active_run_exists(cid) is True
    recovered = db.recover_stale_runs()
    assert recovered == 1
    assert db.active_run_exists(cid) is False


def test_recover_only_marks_running(db_env):
    cid = db.create_conversation("t")["id"]
    rid = db.create_run(cid)["id"]
    db.finish_run(rid, "completed")
    assert db.recover_stale_runs() == 0


def test_finished_run_no_longer_blocks(client):
    r = client.post("/api/conversations", json={})
    cid = r.json()["id"]
    rid = db.create_run(cid)["id"]
    assert client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).status_code == 409
    db.finish_run(rid, "completed")
    r2 = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
    assert r2.status_code == 202
    assert "run_id" in r2.json()


def test_rename_conversation_endpoint(client):
    r = client.post("/api/conversations", json={"title": "old"})
    cid = r.json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"title": "新标题"}).json()["title"] == "新标题"
    # 空标题 422
    assert client.patch(f"/api/conversations/{cid}", json={"title": "  "}).status_code == 422
    # 不存在 404
    assert client.patch("/api/conversations/c_nope", json={"title": "x"}).status_code == 404


def test_delete_conversation_cascades(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    db.create_user_message(cid, "hi")
    rid = db.create_run(cid)["id"]
    db.finish_run(rid, "completed")  # running 会话不可删（409），先完成再删
    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert client.get(f"/api/conversations/{cid}/messages").status_code == 404
    # 不存在的会话 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 404


def test_get_latest_run(db_env):
    cid = db.create_conversation("t")["id"]
    assert db.get_latest_run(cid) is None

    r1 = db.create_run(cid)
    db.finish_run(r1["id"], "completed")
    r2 = db.create_run(cid)  # 同秒内两条 run，靠 rowid 分先后
    latest = db.get_latest_run(cid)
    assert latest["id"] == r2["id"]
    assert latest["status"] == "running"

    db.finish_run(r2["id"], "error", "boom")
    latest = db.get_latest_run(cid)
    assert latest["status"] == "error"
    assert latest["error"] == "boom"


def test_latest_run_endpoint(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    assert client.get(f"/api/conversations/{cid}/runs/latest").json()["run"] is None

    rid = db.create_run(cid)["id"]
    r = client.get(f"/api/conversations/{cid}/runs/latest")
    assert r.status_code == 200
    assert r.json()["run"]["id"] == rid
    assert r.json()["run"]["status"] == "running"

    # 不存在的会话 404
    assert client.get("/api/conversations/c_nope/runs/latest").status_code == 404


def test_delete_conversation_running_returns_409(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    db.create_run(cid)  # status='running'
    assert client.delete(f"/api/conversations/{cid}").status_code == 409
    # 会话仍在
    assert client.get(f"/api/conversations/{cid}/messages").status_code == 200


def test_delete_conversation_unlinks_artifacts(client):
    from app import db as dbmod

    cid = client.post("/api/conversations", json={}).json()["id"]
    dbmod.create_artifact("a_1", cid, "r", "tender.md", "/tmp/tender.md", "md", 10)
    client.delete(f"/api/conversations/{cid}")
    arts = dbmod.list_artifacts()
    assert len(arts) == 1
    assert arts[0]["conversation_id"] is None
