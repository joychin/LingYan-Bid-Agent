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
