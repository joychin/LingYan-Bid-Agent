"""幽灵 run 收尸（2026-09-10 review 批次 C）：

create_run 之后的落库失败（磁盘满等）若不收尸，会留下「无 worker 的 running
run」——后续发消息撞 409「已有进行中的任务」、cancel 端点也无此 rid 的取消
事件，唯一出路是重启。端点在 run 行提交后的失败路径必须 finish_run_if_running。
"""

import pytest

from tests.util import create_conversation, create_task


def test_message_db_failure_does_not_leave_ghost_run(client, monkeypatch):
    from app import db as appdb

    task = create_task(client)
    conv = create_conversation(client, task=task)
    cid = conv["id"]

    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(appdb, "create_user_message", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/conversations/{cid}/messages", json={"content": "你好"})

    # run 已被收尸为 error——不是 409 钉死会话的 running 幽灵
    latest = appdb.get_latest_run(cid)
    assert latest is not None
    assert latest["status"] == "error"
    assert "落库失败" in (latest.get("error") or "")


def test_message_normal_path_unaffected(client, monkeypatch):
    """守卫不伤正常路径：失败未发生时消息照常发出（worker 起不来会自行 error，
    但 run 创建+消息落库成功、接口 202）。"""
    from app import db as appdb

    task = create_task(client)
    conv = create_conversation(client, task=task)
    cid = conv["id"]

    def no_agent(*_a, **_k):
        raise RuntimeError("无 LLM 配置，测试环境不跑真 run")

    monkeypatch.setattr(appdb, "get_latest_run", lambda _cid: None)
    monkeypatch.setattr("app.agent.run_stream", no_agent)
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "你好"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["run_id"] and body["message_id"]
