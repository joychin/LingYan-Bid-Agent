"""任务端点（P4 任务层，§16 任务分组目录）。

任务 = 一次投标 = workspace 下一个真实的项目文件夹（<task_id>/{formal,threads,files,out}）：
- POST 创建后自动建第一个会话一并返回（用户建完任务即刻可聊）
- PATCH 可改任务名与进度便签（进度便签是任务白板，LLM 也经
  update_task_progress 工具更新，同一份真值）
- DELETE 级联：全部会话（含对话记忆）+ 任务目录整体软归档
  （threads/ 过程稿先硬删，其余 mv 到 workspace/archive/<task_id>/，可手工找回）
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import artifact_store, db
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
    return {"tasks": db.list_tasks()}


@router.post("/tasks", status_code=201)
async def create_task(body: NewTaskBody):
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="任务名不能为空")
    task = db.create_task(title)
    # 预建 files/out/drafts 骨架：agent 开工第一步的 ls 不再 path_not_found
    artifact_store.ensure_task_skeleton(task["id"])
    conversation = db.create_conversation(task["id"]) if body.with_conversation else None
    return {"task": task, "conversation": conversation}


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
    return db.get_task(tid)


@router.delete("/tasks/{tid}")
async def delete_task(tid: str):
    if not db.get_task(tid):
        raise HTTPException(status_code=404, detail="任务不存在")
    cids = db.list_task_conversation_ids(tid)
    for cid in cids:
        if db.active_run_exists(cid):
            raise HTTPException(status_code=409, detail=f"会话 {cid} 有进行中的任务，无法删除任务")
    # 磁盘先行：任务目录整体归档（先 mv 到 archive/，成功后归档内 threads/ 硬删）。
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
