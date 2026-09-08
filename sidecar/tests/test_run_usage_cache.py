"""run 级 token 用量累计 + 任务上下文块 run 冻结（2026-09-06 修复批）。"""

import json
from types import SimpleNamespace

import pytest

from app import agent, db, runctx, token_usage
from tests.util import init_env


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    agent._FROZEN_CTX.clear()
    token_usage._by_run.clear()
    yield task, conv
    runctx.clear_run()
    agent._FROZEN_CTX.clear()
    token_usage._by_run.clear()


# ---------- token_usage ----------


def _usage(**kw):
    return SimpleNamespace(**kw)


def test_extract_standard_openai_fields():
    u = _usage(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_tokens_details=SimpleNamespace(cached_tokens=800),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=120),
    )
    assert token_usage._extract(u) == {"input": 1000, "output": 200, "cached": 800, "reasoning": 120}


def test_extract_deepseek_nonstandard_cache_field():
    u = _usage(prompt_tokens=500, completion_tokens=50, prompt_cache_hit_tokens=400)
    assert token_usage._extract(u) == {"input": 500, "output": 50, "cached": 400}


def test_extract_none_and_partial():
    assert token_usage._extract(None) == {}
    assert token_usage._extract(_usage(prompt_tokens=10)) == {"input": 10}


def test_record_without_run_discarded(env):
    runctx.clear_run()
    token_usage.record_from_response(SimpleNamespace(usage=_usage(prompt_tokens=99, completion_tokens=9)))
    assert token_usage._by_run == {}


def test_record_accumulates_and_take_clears(env):
    task, conv = env
    runctx.set_run(conv["id"], "r_u1", task["id"])
    token_usage.record_from_response(SimpleNamespace(usage=_usage(prompt_tokens=100, completion_tokens=10)))
    token_usage.record_from_response(SimpleNamespace(usage=_usage(prompt_tokens=50, completion_tokens=5, prompt_cache_hit_tokens=30)))
    got = token_usage.take("r_u1")
    assert got == {"input": 150, "output": 15, "cached": 30}
    assert token_usage.take("r_u1") == {}  # 取走即清零


def test_record_usage_turn_detail_main_scope(env):
    """per-turn 明细：默认 main scope 落 run_turn_usage 一行，run 级聚合行为不变。"""
    task, conv = env
    runctx.set_run(conv["id"], "r_turn1", task["id"])
    token_usage.record_usage(_usage(prompt_tokens=100, completion_tokens=10))
    rows = db.list_run_turn_usage("r_turn1")
    assert len(rows) == 1
    assert rows[0]["scope"] == "main"
    assert rows[0]["input"] == 100 and rows[0]["output"] == 10
    assert token_usage.peek("r_turn1") == {"input": 100, "output": 10}


def test_record_usage_turn_detail_sub_scope(env):
    """子代理 scope 中间件打标路径：set sub → 明细行 scope=sub，finally 复位回 main。"""
    task, conv = env
    runctx.set_run(conv["id"], "r_turn2", task["id"])
    token = runctx.set_agent_scope("sub")
    token_usage.record_usage(
        _usage(
            prompt_tokens=50,
            completion_tokens=5,
            prompt_cache_hit_tokens=30,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
        )
    )
    runctx.reset_agent_scope(token)
    rows = db.list_run_turn_usage("r_turn2")
    assert len(rows) == 1
    assert rows[0]["scope"] == "sub"
    assert rows[0]["cached"] == 30 and rows[0]["reasoning"] == 3
    assert runctx.current_scope() == "main"


def test_finish_run_persists_usage(env):
    task, conv = env
    rid = db.create_run(conv["id"])["id"]
    db.finish_run(
        rid, "completed", last_seq=3,
        token_usage_json=json.dumps({"input": 10, "output": 2, "cached": 8}),
    )
    run = db.get_run(rid)
    assert json.loads(run["token_usage"]) == {"input": 10, "output": 2, "cached": 8}
    # 不传 token_usage_json 不覆盖已有值（HITL 续段无新增）
    db.finish_run(rid, "completed", last_seq=5)
    assert json.loads(db.get_run(rid)["token_usage"])["input"] == 10


def test_usage_json_final_merges_prev_and_current(env):
    task, conv = env
    rid = db.create_run(conv["id"])["id"]
    db.interrupt_run(
        rid, [], 1, token_usage_json=json.dumps({"input": 100, "output": 10})
    )
    runctx.set_run(conv["id"], rid, task["id"])
    token_usage.record_from_response(SimpleNamespace(usage=_usage(prompt_tokens=50, completion_tokens=5, prompt_cache_hit_tokens=40)))
    out = json.loads(agent._usage_json_final(rid))
    assert out == {"input": 150, "output": 15, "cached": 40}


# ---------- 流式路径用量观测（2026-09-06 修：观测点从 create 返回挪到流消费完）----------


class _FakeStream:
    """模拟 openai 流式响应：可迭代 + with 上下文，chunk 可能是 dict 或模型对象。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __iter__(self):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_usage_capturing_stream_records_from_final_chunk(env):
    task, conv = env
    runctx.set_run(conv["id"], "r_s1", task["id"])
    usage = _usage(prompt_tokens=700, completion_tokens=70, prompt_cache_hit_tokens=600)
    stream = agent._UsageCapturingStream(
        _FakeStream(
            [
                {"usage": None},  # dict 块无 usage
                SimpleNamespace(usage=None),  # 模型块无 usage
                SimpleNamespace(usage=usage),  # 最后一块带 usage（include_usage 开启时）
            ]
        )
    )
    with stream as s:
        chunks = list(s)
    assert len(chunks) == 3  # 迭代契约不变：原样吐全部块
    assert token_usage._by_run["r_s1"] == {"input": 700, "output": 70, "cached": 600}


def test_usage_capturing_stream_no_usage_records_nothing(env):
    task, conv = env
    runctx.set_run(conv["id"], "r_s2", task["id"])
    stream = agent._UsageCapturingStream(_FakeStream([SimpleNamespace(usage=None), {"usage": None}]))
    list(stream)
    assert token_usage._by_run == {}


def test_create_stream_wraps_and_records_after_consumption(env):
    """真实链路是 create(stream=True) → 包装器 → langchain 消费完才记账。"""
    task, conv = env
    runctx.set_run(conv["id"], "r_s3", task["id"])
    usage = _usage(prompt_tokens=300, completion_tokens=30)
    inner = SimpleNamespace(
        create=lambda **kw: _FakeStream([SimpleNamespace(usage=None), SimpleNamespace(usage=usage)])
    )
    shell = agent._NoThinkingRetryCompletions(inner)
    resp = shell.create(stream=True, model="m")
    assert token_usage._by_run == {}  # 消费前不记账（流未吐完 usage 取不到）
    list(resp)
    assert token_usage._by_run["r_s3"] == {"input": 300, "output": 30}


def test_create_nonstream_records_directly(env):
    """非流式（_generate 等）响应自带 .usage，create 返回处直接记账。"""
    task, conv = env
    runctx.set_run(conv["id"], "r_s4", task["id"])
    inner = SimpleNamespace(
        create=lambda **kw: SimpleNamespace(usage=_usage(prompt_tokens=100, completion_tokens=10))
    )
    shell = agent._NoThinkingRetryCompletions(inner)
    shell.create(model="m")
    assert token_usage._by_run["r_s4"] == {"input": 100, "output": 10}


# ---------- 任务上下文块 run 冻结 ----------


def test_frozen_block_byte_stable_within_run(env):
    task, conv = env
    b1 = agent._task_context_block_frozen(task["id"], conv["id"], "r_f1")
    # 中途改便签（旧实现此处会变化 → 打断前缀缓存）
    db.update_task_progress(task["id"], "中途更新：第三章已完成")
    b2 = agent._task_context_block_frozen(task["id"], conv["id"], "r_f1")
    assert b1 == b2
    assert "今天日期" in b1  # 天级日期（秒级时间戳已删，Claude Code 同款精度）


def test_frozen_block_recomputed_across_runs(env):
    task, conv = env
    agent._task_context_block_frozen(task["id"], conv["id"], "r_f1")
    db.update_task_progress(task["id"], "新便签")
    b2 = agent._task_context_block_frozen(task["id"], conv["id"], "r_f2")
    assert "新便签" in b2


def test_unfrozen_without_run_id(env):
    task, conv = env
    b = agent._task_context_block_frozen(task["id"], conv["id"], None)
    assert "今天日期" in b
