"""bus：必达事件（终态/artifact.created）在队列积压时挤位送达，可丢事件照常丢弃。"""

import asyncio

from app import bus, events


def test_must_deliver_events_survive_full_queue():
    async def scenario():
        cid = "c_full"
        q = bus.subscribe(cid)
        try:
            # 塞满队列：先塞可丢的 token，再补一条必达的终态事件
            for i in range(q.maxsize):
                await bus.publish(cid, {"event": events.EVENT_TOKEN, "data": {"i": i}})
            assert q.full()
            await bus.publish(cid, {"event": events.EVENT_COMPLETED, "data": {"seq": 999}})

            drained = []
            while not q.empty():
                drained.append(q.get_nowait())
            events_out = [e["event"] for e in drained]
            # 必达事件挤掉最旧一条（token i=0）送达；其余 token 保留
            assert q.maxsize == 500 and len(drained) == 500
            assert events_out[-1] == "agent.completed"
            assert events_out.count("agent.token") == 499
            assert drained[0]["data"] == {"i": 1}
            assert drained[-1]["data"] == {"seq": 999}
        finally:
            bus.unsubscribe(cid, q)

    asyncio.run(scenario())


def test_must_deliver_head_not_evicted_by_must_deliver():
    """队头恰为必达事件时再入必达事件：丢弃的是最旧的**非必达**事件，队头的
    必达事件不得被盲挤（丢掉终态/interrupt 会让连接存活期间失去收敛信号）。"""
    async def scenario():
        cid = "c_must_head"
        q = bus.subscribe(cid)
        try:
            # 队头是必达的 completed，其后 499 条可丢 token（队列满）
            await bus.publish(cid, {"event": events.EVENT_COMPLETED, "data": {"seq": 1}})
            for _ in range(q.maxsize - 1):
                await bus.publish(cid, {"event": events.EVENT_TOKEN, "data": {}})
            assert q.full()

            await bus.publish(cid, {"event": events.EVENT_RUN_INTERRUPT, "data": {"seq": 2}})

            drained = []
            while not q.empty():
                drained.append(q.get_nowait())
            events_out = [e["event"] for e in drained]
            # 两条必达事件都在：队头 completed 未被挤掉，新 interrupt 也送达
            assert events_out.count("agent.completed") == 1
            assert events_out.count("run.interrupt") == 1
            assert events_out.count("agent.token") == q.maxsize - 2
        finally:
            bus.unsubscribe(cid, q)

    asyncio.run(scenario())


def test_full_must_deliver_queue_evicts_oldest_ordered():
    """极端态：积压全是必达事件时再入必达事件——保序丢弃最旧一条，
    新事件必须送达（不得因队列满而把新终态丢掉）。"""
    async def scenario():
        cid = "c_all_must"
        q = bus.subscribe(cid)
        try:
            for i in range(q.maxsize):
                await bus.publish(cid, {"event": events.EVENT_ARTIFACT_CREATED, "data": {"i": i}})
            assert q.full()
            await bus.publish(cid, {"event": events.EVENT_ERROR, "data": {"seq": 999}})

            drained = []
            while not q.empty():
                drained.append(q.get_nowait())
            events_out = [e["event"] for e in drained]
            assert len(drained) == q.maxsize == 500
            assert events_out[-1] == "agent.error"
            assert events_out.count("agent.error") == 1
            # 最旧一条（i=0）被保序丢弃，其余 499 条 artifact.created 完整保留
            assert drained[0]["data"] == {"i": 1}
            assert events_out.count("artifact.created") == 499
        finally:
            bus.unsubscribe(cid, q)

    asyncio.run(scenario())


def test_droppable_events_discarded_when_full():
    async def scenario():
        cid = "c_drop"
        q = bus.subscribe(cid)
        try:
            for _ in range(q.maxsize):
                await bus.publish(cid, {"event": events.EVENT_TOKEN, "data": {}})
            assert q.full()
            await bus.publish(cid, {"event": events.EVENT_TODO_UPDATED, "data": {}})
            # 可丢事件不挤位：队列仍是满的 500 条 token，todo 事件被丢弃
            assert q.qsize() == q.maxsize
            kinds = set()
            while not q.empty():
                kinds.add(q.get_nowait()["event"])
            assert kinds == {"agent.token"}
        finally:
            bus.unsubscribe(cid, q)

    asyncio.run(scenario())
