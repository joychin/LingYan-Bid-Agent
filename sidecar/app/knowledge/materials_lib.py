"""写作素材库域（v2 手工构建，2026-09-04）：素材块 = 用户勾选的章节区间集合 + 备注。

与知识库彻底分离：自己的文件（materials/files/）、自己的解析产物
（materials/parse/<stem>/md+outline）、自己的块真值（blocks.json）。流程 =
上传 → 后台解析（纯机械，不做抽取/图片）→ 用户在目录树勾选 → 建块（多区间）
→ 备注。零 LLM——块的价值判断归用户，程序只做机械（行号夹紧/嵌套区间去
重叠/内容切片/检索段落盘）。

块检索段复用 kb_segments（item_id=素材文件 id mt_ 前缀；事实检索按 kb_items
映射过滤天然隔离）。块 id 只在一个 blocks.json 生命周期内稳定，删块=引用失效。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from .. import config as cfg
from .. import db
from ..parse import convert as parse_convert
from ..parse import outline_with_lines, write_atomic

logger = logging.getLogger(__name__)

# 在跑解析（单飞）：连点/重复触发跳过
_inflight: set[str] = set()


def mt_files_dir() -> Path:
    return cfg.materials_dir() / "files"


def mt_parse_dir(file_name: str) -> Path:
    return cfg.materials_dir() / "parse" / Path(file_name).stem


def mt_parse_paths(file_name: str) -> tuple[Path, Path, Path]:
    """(md, outline.json, blocks.json) 三产物路径。"""
    d = mt_parse_dir(file_name)
    return (
        d / f"{file_name}.md",
        d / f"{file_name}.outline.json",
        d / "blocks.json",
    )


def ensure_dirs() -> None:
    mt_files_dir().mkdir(parents=True, exist_ok=True)


def unique_file_path(file_name: str) -> Path:
    """同名加序号（同 hash 在 API 层已拦截，这里防同异 hash 同名）。"""
    cand = mt_files_dir() / file_name
    if not cand.exists():
        return cand
    stem, ext = Path(file_name).stem, Path(file_name).suffix
    i = 2
    while (mt_files_dir() / f"{stem} ({i}){ext}").exists():
        i += 1
    return mt_files_dir() / f"{stem} ({i}){ext}"


def delete_file_disk(file_name: str) -> None:
    """删文件连带解析产物（目录级，容错）。"""
    src = mt_files_dir() / file_name
    if src.is_file():
        src.unlink(missing_ok=True)
    import shutil

    shutil.rmtree(mt_parse_dir(file_name), ignore_errors=True)


# ---------- 解析（后台，纯机械） ----------

def schedule_parse(fid: str) -> bool:
    """上传后后台解析（单飞）。"""
    if fid in _inflight:
        return False
    _inflight.add(fid)
    asyncio.get_running_loop().create_task(_run_safe(fid))
    return True


async def _run_safe(fid: str) -> None:
    try:
        await asyncio.to_thread(run_parse, fid)
    except Exception:
        logger.exception("素材文件解析异常：%s", fid)
        try:
            db.mt_update_file(fid, parse_status="failed", error="解析异常，请重试")
        except Exception:
            pass
    finally:
        _inflight.discard(fid)


def run_parse(fid: str) -> dict:
    """解析主体：本地 parse_convert → md + outline 落盘 → ready。无 LLM、无图片。"""
    f = db.mt_get_file(fid)
    if not f:
        return {}
    src = mt_files_dir() / f["file_name"]
    if not src.is_file():
        db.mt_update_file(fid, parse_status="failed", error="原件缺失")
        return db.mt_get_file(fid) or {}
    db.mt_update_file(fid, parse_status="parsing", error=None)
    try:
        result = parse_convert(src)
    except Exception as e:
        db.mt_update_file(fid, parse_status="failed", error=f"解析失败：{e}")
        return db.mt_get_file(fid) or {}
    md_text = result.md
    outline = outline_with_lines(md_text) if md_text else []
    md_path, outline_path, _ = mt_parse_paths(f["file_name"])
    md_path.parent.mkdir(parents=True, exist_ok=True)
    if md_text:
        write_atomic(md_path, md_text)
    else:
        md_path.unlink(missing_ok=True)
    write_atomic(outline_path, json.dumps(outline, ensure_ascii=False, indent=2))
    db.mt_update_file(
        fid,
        parse_status="ready",
        error=None if outline else "未识别到目录结构——无法挑章节（该文件没有可用标题）",
    )
    return db.mt_get_file(fid) or {}


def read_outline(fid: str) -> list[dict]:
    """目录树（勾选界面数据源：全层级带行号）。"""
    f = db.mt_get_file(fid)
    if not f:
        return []
    _, outline_path, _ = mt_parse_paths(f["file_name"])
    if not outline_path.is_file():
        return []
    try:
        data = json.loads(outline_path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return data if isinstance(data, list) else []


# ---------- 块（真值 blocks.json + 索引 + 检索段） ----------

def read_blocks(fid: str) -> list[dict]:
    f = db.mt_get_file(fid)
    if not f:
        return []
    _, _, blocks_path = mt_parse_paths(f["file_name"])
    if not blocks_path.is_file():
        return []
    try:
        data = json.loads(blocks_path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list):
        return []
    return [b for b in blocks if isinstance(b, dict) and b.get("id")]


def write_blocks(fid: str, blocks: list[dict]) -> None:
    f = db.mt_get_file(fid)
    if not f:
        return
    _, _, blocks_path = mt_parse_paths(f["file_name"])
    write_atomic(blocks_path, json.dumps(
        {"version": 1, "blocks": blocks}, ensure_ascii=False, indent=2,
    ))


def _squash_ranges(raw: list, total_lines: int) -> list[list[int]]:
    """区间机械校验：夹紧到 [1, total]、丢弃无效区间、嵌套/重叠去重（被包含的丢弃）、排序。"""
    cleaned: list[list[int]] = []
    for r in raw:
        if not isinstance(r, (list, tuple)) or len(r) != 2:
            continue
        try:
            s, e = int(r[0]), int(r[1])
        except (TypeError, ValueError):
            continue
        s, e = max(1, s), min(total_lines, e)
        if e < s:
            continue
        if any(s >= cs and e <= ce for cs, ce in cleaned):
            continue  # 被已有区间包含（勾了父子节点）
        cleaned = [(cs, ce) for cs, ce in cleaned if not (cs >= s and ce <= e)]
        cleaned.append((s, e))
    return [list(r) for r in sorted(cleaned)]


def _slice(md_path: Path, ranges: list[list[int]]) -> str:
    """按区间拼接块内容（页锚点等注释行剥掉）。"""
    if not md_path.is_file():
        return ""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    parts: list[str] = []
    for s, e in ranges:
        chunk = [
            ln.replace("<!--", "").replace("-->", "").strip()
            for ln in lines[s - 1 : e]
        ]
        text = "\n".join(ln for ln in chunk if ln)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def reindex_blocks(fid: str) -> None:
    """重建该文件全部块的检索段（标题+备注+内容；复用 kb_segments，item_id=mt id）。"""
    from . import fts

    f = db.mt_get_file(fid)
    if not f:
        return
    md_path, _, _ = mt_parse_paths(f["file_name"])
    segs: list[dict] = []
    for b in read_blocks(fid):
        text = _slice(md_path, b.get("ranges") or [])
        raw = "\n".join(x for x in (b.get("title"), b.get("note"), text) if x)
        if not raw.strip():
            continue
        first_start = (b.get("ranges") or [[None]])[0][0]
        segs.append({
            "section_path": b.get("title"),
            "material_id": b["id"],
            "line_start": first_start,
            "line_end": None,
            "page_start": None,
            "raw": raw,
        })
    db.kb_replace_segments(
        fid,
        [{**s, "body": fts.segment_for_fts(s.pop("raw"))} for s in segs],
    )


def _sync_blocks(fid: str) -> None:
    """blocks.json 真值 → mt_blocks 索引行。"""
    rows = []
    md_path, _, _ = mt_parse_paths((db.mt_get_file(fid) or {}).get("file_name", ""))
    for b in read_blocks(fid):
        chars = len(_slice(md_path, b.get("ranges") or []))
        rows.append({
            "id": b["id"], "title": b.get("title") or "",
            "note": b.get("note") or "",
            "ranges": json.dumps(b.get("ranges") or [], ensure_ascii=False),
            "chars": chars,
        })
    db.mt_replace_blocks(fid, rows)


def create_block(fid: str, title: str, note: str, ranges: list) -> dict | None:
    """建块：区间校验（夹紧/嵌套去重）→ 真值追加 → 索引+检索段同步。"""
    f = db.mt_get_file(fid)
    if not f or f.get("parse_status") != "ready":
        return None
    md_path, _, _ = mt_parse_paths(f["file_name"])
    total = len(md_path.read_text(encoding="utf-8").splitlines()) if md_path.is_file() else 0
    cleaned = _squash_ranges(ranges, total)
    if not cleaned:
        return None
    blocks = read_blocks(fid)
    block = {
        "id": f"blk_{uuid.uuid4().hex[:12]}",
        "title": (title or "").strip()[:120] or "未命名素材块",
        "note": (note or "").strip()[:2000],
        "ranges": cleaned,
    }
    blocks.append(block)
    write_blocks(fid, blocks)
    _sync_blocks(fid)
    reindex_blocks(fid)
    return db.mt_get_block(block["id"])


def update_block(bid: str, title: str | None = None, note: str | None = None) -> dict | None:
    """改标题/备注（真值+索引+检索段同步）。"""
    b = db.mt_get_block(bid)
    if not b:
        return None
    fid = b["file_id"]
    blocks = read_blocks(fid)
    for x in blocks:
        if x.get("id") == bid:
            if title is not None:
                x["title"] = title.strip()[:120] or x["title"]
            if note is not None:
                x["note"] = note.strip()[:2000]
    write_blocks(fid, blocks)
    _sync_blocks(fid)
    reindex_blocks(fid)
    return db.mt_get_block(bid)


def delete_block(bid: str) -> bool:
    b = db.mt_get_block(bid)
    if not b:
        return False
    fid = b["file_id"]
    write_blocks(fid, [x for x in read_blocks(fid) if x.get("id") != bid])
    _sync_blocks(fid)
    reindex_blocks(fid)
    return True


def delete_file(fid: str) -> bool:
    """删文件：库行+块+段+磁盘。"""
    f = db.mt_get_file(fid)
    if not f:
        return False
    db.mt_delete_file(fid)
    delete_file_disk(f["file_name"])
    return True
