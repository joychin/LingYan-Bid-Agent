"""bg：fire-and-forget 强引用登记（Python 官方模式）+ 解析专用线程池。"""

import asyncio
import contextvars
import logging
import threading

from app import bg


def test_spawn_background_holds_and_releases_reference():
    """官方模式：集合持强引用、完成自动移出；异常在回调里取走并记日志
    （fire-and-forget 无人 await，不能只靠 GC 时才浮出）。"""

    async def main():
        done = []

        async def work():
            done.append(1)

        bg.spawn_background(work())
        assert len(bg._tasks) == 1  # 运行期强引用在集合里（防中途被 GC 收走）
        await asyncio.sleep(0.05)
        assert done == [1]
        assert len(bg._tasks) == 0  # 完成自动移出，集合不增长

        async def boom():
            raise RuntimeError("测试异常")

        records: list[logging.LogRecord] = []

        class _Handler(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = logging.getLogger("app.bg")
        logger.addHandler(_Handler())
        try:
            bg.spawn_background(boom())
            await asyncio.sleep(0.05)
            assert len(bg._tasks) == 0
            assert any("测试异常" in r.getMessage() for r in records)
        finally:
            logger.removeHandler(_Handler)

    asyncio.run(main())


def test_run_in_ingest_runs_in_dedicated_pool_with_context():
    """解析线程池：函数在带 ingest 前缀的专属线程执行（与 agent run 的默认池
    分家），contextvars 随行不因换池丢失（对齐 to_thread 语义）。"""
    marker = contextvars.ContextVar("marker", default="")

    async def main():
        marker.set("ctx-value")
        seen: dict = {}

        def probe():
            seen["thread"] = threading.current_thread().name
            seen["ctx"] = marker.get()

        await bg.run_in_ingest(probe)
        assert seen["thread"].startswith("ingest")
        assert seen["ctx"] == "ctx-value"

    asyncio.run(main())
