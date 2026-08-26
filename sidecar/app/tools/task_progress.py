"""任务进度便签工具：LLM 在阶段性节点更新任务的「进度白板」。

进度便签是任务层共享上下文的一部分（每次 run 启动注入各会话），本质是一张
整体覆盖的白板（last-write-wins），不是版本化内容——「废标项解析-已完成 /
投标目录-进行中」这类一句话清单。
"""

from langchain_core.tools import tool

from .. import db, runctx

_NOTE_MAX_CHARS = 20_000


@tool
def update_task_progress(progress_note: str) -> str:
    """更新当前任务的进度便签（markdown，整体覆盖）。

    在完成阶段性工作时调用（如「招标文件已解析完成」「投标目录已生成待用户转正」），
    保持简短：每行一个条目，标注状态（未开始/进行中/已完成）。该便签对任务下
    所有会话可见，是新会话了解任务进展的第一入口。
    """
    ctx = runctx.current_run()
    if ctx is None or not ctx.task_id:
        return "[更新失败] 当前不在任务会话中，无法更新进度便签"
    if not db.get_task(ctx.task_id):
        return "[更新失败] 任务不存在"
    note = progress_note.strip()[:_NOTE_MAX_CHARS]
    if not note:
        return "[更新失败] 进度便签不能为空"
    db.update_task_progress(ctx.task_id, note)
    return "[已更新] 任务进度便签已保存。"
