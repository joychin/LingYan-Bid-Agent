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
