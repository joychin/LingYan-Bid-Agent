"""后台任务强引用登记（Python 官方推荐模式，docs asyncio 「Creating tasks」）。

asyncio.create_task 返回的 task 事件循环只持弱引用——GC 时机不巧会把未完成的
task 连同其 finally 清理（_inflight discard、run 收尾落库）一起收走，造成条目
永久 409「正在识别中」或 run 悬挂到重启。这里集中持有强引用、完成自动移出；
异常在回调里取走并记日志（调用方全是 fire-and-forget，没人 await）。
"""

import asyncio
import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def spawn_background(coro) -> asyncio.Task:
    """fire-and-forget 唯一入口：持强引用防中途被 GC，完成自动出集合。"""

    def _release(task: asyncio.Task) -> None:
        _tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.error("后台任务异常：%s", exc, exc_info=exc)

    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_release)
    return task


# KB/素材解析专用线程池：与 agent run 的默认 to_thread 池分家——一边卡死不再
# 饿死另一边（纯资源隔离，不加锁不排队）。max_workers=4 同时是解析并发的
# 上限，防 bulk 上传把 CPU 打满。
_INGEST_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ingest")


def run_in_ingest(func, /, *args):
    """解析线程池跑阻塞函数（KB/素材解析唯一通道）。

    手动复制 contextvars 再进 lambda：对齐 asyncio.to_thread 的传播语义，
    调用方若依赖请求域 contextvar 不因换池而丢。
    """
    ctx = contextvars.copy_context()
    return asyncio.get_running_loop().run_in_executor(
        _INGEST_EXECUTOR, lambda: ctx.run(func, *args)
    )
