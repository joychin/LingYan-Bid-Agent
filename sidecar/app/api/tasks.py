"""任务端点（P4 任务层，§16 任务分组目录，2026-08-31 重构）。

任务 = 一次投标 = workspace 下一个真实的项目文件夹（<task_id>/{sources,work,_meta}）：
- POST 创建后自动建第一个会话一并返回（用户建完任务即刻可聊）
- PATCH 可改任务名与进度便签（进度便签是任务白板，LLM 也经
  update_task_progress 工具更新，同一份真值）
- DELETE 级联：全部会话（含对话记忆）+ 任务目录整体软归档
  （整目录 mv 到 workspace/archive/<task_id>/，可手工找回；文件归任务，归档不删子目录）
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import artifact_store, db, task_stage
from ..agent import delete_thread_memory

router = APIRouter()


class NewTaskBody(BaseModel):
    title: str
    # 侧栏「新建任务」默认连带第一个会话（建完即聊）；输入区选择器就地新建时
    # 传 False——会话由首发消息创建，不留下空会话
    with_conversation: bool = True


class UpdateTaskBody(BaseModel):
    title: str | None = None
    progress_note: str | None = None


@router.get("/tasks")
async def list_tasks():
    # 附加 stage/last_activity_at（task_stage 批量推导；db.list_tasks 的 SQL 排序
    # 不动——侧栏按创建序稳定不跳动，「按最近活动」由首页前端排）
    return {"tasks": task_stage.enrich(db.list_tasks())}


@router.post("/tasks", status_code=201)
async def create_task(body: NewTaskBody):
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="任务名不能为空")
    task = db.create_task(title)
    # 预建 sources/work 骨架：agent 开工第一步的 ls 不再 path_not_found
    artifact_store.ensure_task_skeleton(task["id"])
    conversation = db.create_conversation(task["id"]) if body.with_conversation else None
    return {"task": task_stage.enrich([task])[0], "conversation": conversation}


@router.patch("/tasks/{tid}")
async def update_task(tid: str, body: UpdateTaskBody):
    if not db.get_task(tid):
        raise HTTPException(status_code=404, detail="任务不存在")
    if body.title is not None:
        try:
            db.rename_task(tid, body.title)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    if body.progress_note is not None:
        db.update_task_progress(tid, body.progress_note[:20_000])
    return task_stage.enrich([db.get_task(tid)])[0]


@router.delete("/tasks/{tid}")
async def delete_task(tid: str):
    if not db.get_task(tid):
        raise HTTPException(status_code=404, detail="任务不存在")
    cids = db.list_task_conversation_ids(tid)
    for cid in cids:
        if db.active_run_exists(cid):
            raise HTTPException(status_code=409, detail=f"会话 {cid} 有进行中的任务，无法删除任务")
    # 磁盘先行：任务目录整体归档（mv 到 archive/，文件归任务、整目录保留）。
    # 归档失败（磁盘不可写/目标冲突）必须中止且不删库：否则任务与索引行消失、
    # 磁盘目录残留原位，用户在产品内再也找不回——保留现场让用户裁决。
    if not artifact_store.archive_task(tid):
        raise HTTPException(
            status_code=500,
            detail="任务目录归档失败（磁盘不可写或归档目标冲突），任务未删除，可重试或手工处理",
        )
    db.delete_task(tid)
    for cid in cids:
        delete_thread_memory(cid)  # 连带清 agent.db checkpoint，防幽灵记忆
    return {"ok": True}
