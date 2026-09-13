"""任务阶段推导（首页列表用；纯机械、零 LLM、零新增持久化）。

阶段回答「这个标走到哪一步了」，判据全部来自既有磁盘与索引真值，不引入任何
新表新列：

| stage | 判据 |
|---|---|
| delivered | 产物含 tender-volume-docx（整本已合册交付） |
| drafting  | work/body/ 有文件（正文节已开写） |
| outlined  | 产物含 tender-response-docs（投标目录已发布） |
| analyzed  | work/analysis/ 有文件（要点提取已跑） |
| parsed    | work/parse/ 有文件（招标文件已解析） |
| new       | 以上皆无 |

**必须要看文件、不能看目录**：ensure_task_skeleton 在建任务时与每次 run 起点
都会预建 parse/analysis/outline/body（目录空窗期是刻意设计的，「模型 ls 撞
path_not_found」的先例修复）——所以目录存在只说明骨架就位，判「已解析」必须
目录里有文件。同理判据只 stat 不读内容（workbench 首行读法只用于单任务，
列表端点逐任务读文件是性能陷阱）。

last_activity_at = max(任务创建时间, 最近一次 run 起始, 最近一次产物更新时间)，
用于首页「按最近活动排序」（后端 GET /tasks 的 SQL 排序不动——侧栏保持创建序、
不随 run 跳动；「最近视图」只在首页排）。
"""

from datetime import datetime
from pathlib import Path

from . import artifact_store, db

# 顺序即流水线推进序（将来若加阶段进度条，直接按此顺序取下标，推导无需改动）
STAGES = ("new", "parsed", "analyzed", "outlined", "drafting", "delivered")

_SCHEMA_DIRECTORY = "tender-response-docs"  # 投标目录已发布
_SCHEMA_VOLUME = "tender-volume-docx"  # 整本已合册交付

# 阶段探测的 work/ 子目录（_PROCESS_DIRS 的子集：outline/fragments 是中间态不判阶段）
_STAGE_DIRS = {
    "parsed": "parse",
    "analyzed": "analysis",
    "drafting": "body",
}


def _dir_has_files(path: Path) -> bool:
    """目录里存在任一非隐藏常规文件即 True（找到第一个就返回，不做全量枚举）。

    与其他 work/ 遍历同一口径（run_files._walk_work_files / workbench 列表）：
    跳隐藏文件、跳 artifacts/ 子树（产物包不参与阶段判定）。
    """
    if not path.is_dir():
        return False
    for p in path.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        try:
            if p.relative_to(path).parts[0] == "artifacts":
                continue
        except ValueError:  # 理论不发生（rglob 结果必在 path 下）
            continue
        return True
    return False


def derive_stage(task_id: str, schemas: set[str]) -> str:
    """单任务阶段：schemas=该任务产物 schema_id 集合（由调用方批量取好）。"""
    if _SCHEMA_VOLUME in schemas:
        return "delivered"
    work = artifact_store.work_dir(task_id)
    if _dir_has_files(work / _STAGE_DIRS["drafting"]):
        return "drafting"
    if _SCHEMA_DIRECTORY in schemas:
        return "outlined"
    if _dir_has_files(work / _STAGE_DIRS["analyzed"]):
        return "analyzed"
    if _dir_has_files(work / _STAGE_DIRS["parsed"]):
        return "parsed"
    return "new"


def _max_iso(*values: str | None) -> str:
    """取最大 ISO 时间串（同格式可直接字典序比较，见 db._now 的 isoformat）。"""
    present = [v for v in values if v]
    return max(present) if present else datetime.now().astimezone().isoformat(timespec="seconds")


def compute_task_meta(tasks: list[dict]) -> dict[str, dict]:
    """批量算 {task_id: {"stage", "last_activity_at"}}。

    两次 GROUP BY 批量取索引真值 + 每任务常数次小目录探测（空目录瞬间返回），
    不 caching：几十个任务量级下开销可忽略，且阶段天然随磁盘/索引实时变化。
    """
    if not tasks:
        return {}
    signals = db.list_task_artifact_signals()  # {tid: {schema_id: max_updated_at}}
    last_run = db.list_task_last_run()  # {tid: iso}

    out: dict[str, dict] = {}
    for t in tasks:
        tid = t["id"]
        by_schema = signals.get(tid, {})
        schemas = set(by_schema)
        last_artifact = max(by_schema.values()) if by_schema else None
        out[tid] = {
            "stage": derive_stage(tid, schemas),
            "last_activity_at": _max_iso(t.get("created_at"), last_run.get(tid), last_artifact),
        }
    return out


def enrich(tasks: list[dict]) -> list[dict]:
    """给任务行附加 stage / last_activity_at（GET 列表、POST、PATCH 三处复用）。"""
    meta = compute_task_meta(tasks)
    return [{**t, **meta.get(t["id"], {})} for t in tasks]
