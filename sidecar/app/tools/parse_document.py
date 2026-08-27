"""确定性文档解析工具（LLM 工具层薄壳）：.docx/.pdf/.txt/.md → Markdown + 带行号区间的标题大纲。

转换核心在 app/parse/（注册表，知识库入库管线共用）；本文件只保留工具层职责：
任务上下文校验、workspace 路径 containment、hash 幂等、产物落盘（任务 out/parse/）、
概况文案、以及任务场景限制（扫描件/图片明确拒绝——视觉识别是知识库管线能力）。

结构识别按可信度分档（meta.conversion 记录，下游引用出处时按档位决定是否署章节名）：
- docx-native / pdf-toc：作者声明的结构（Word 标题样式 / PDF 书签树）——可信；
- docx-numbered / pdf-fontsize：启发式（无样式文档的中文编号识别 / 无书签 PDF 的字号
  判级）——可能有误，产物带警示，出处不署章节名。
pdf 侧另有跨页重复的页眉页脚与纯页码剔除、每页页码锚点 <!-- p:N -->（出处可引页码）。
txt/md 透传（md 保留 ATX 标题进 outline；txt 无结构走 grep 兜底警示）。
outline 记录每个标题的行号区间（大文件按区段精读的定位索引）、meta 记录来源 hash/
顶层章节/质量警示，同 hash 幂等跳过、扫描件质量兜底（不静默产垃圾）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool

from .. import runctx
from ..artifact_store import task_files_dir, task_out_dir
from ..config import workspace_dir
from ..parse import convert as parse_convert
from ..parse import count_nodes, outline_with_lines, sha256_file
from ..parse.image import IMAGE_EXTS

_MIN_TEXT_CHARS = 100  # 低于此值视为转换失败（扫描件/损坏文件）


# ---------------------------------------------------------------------------
# 工具主体
# ---------------------------------------------------------------------------
def _resolve_ws_path(p: str) -> Path:
    """路径 containment：解析（含符号链接）后必须落在 workspace 内。

    相对路径按 workspace 根解析；根下找不到时回退当前任务的 files/ 按文件名找
    （模型常直接说裸文件名，上传文件住在 <task>/files/）。
    """
    root = workspace_dir().resolve()
    cand = Path(p).expanduser()
    if not cand.is_absolute():
        cand = root / cand
    resolved = cand.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"路径越界：只允许 workspace 内的文件（{root}），收到 {p}")
    if not resolved.exists() and not Path(p).is_absolute():
        ctx = runctx.current_run()
        if ctx and ctx.task_id:
            alt = (task_files_dir(ctx.task_id) / Path(p).name).resolve()
            if alt.is_relative_to(root):
                resolved = alt
    return resolved


def _summary_lines(head: str, name: str, rel: Path, meta: dict, *, usage_hint: bool) -> list[str]:
    """成功/跳过两路共用的返回文案组装；meta 形状即落盘 meta.json（旧文件缺键防御取值）。

    跳过路径也带全量概况，调用方（确认门汇总）无需再读 meta.json。
    """
    pages_part = f" / {meta['pages']} 页" if "pages" in meta else ""
    top = meta.get("top_level") or []
    n_top = meta.get("top_level_titles", len(top))
    top_show = "；".join(top) + ("…" if n_top > len(top) else "")
    parts = [
        head,
        f"Markdown {meta.get('chars', '?')} 字符 / 标题 {meta.get('headings', '?')} 个"
        f" / 顶层章节 {n_top} 个{pages_part} / 表格 {meta.get('tables', '?')} 个；"
        f"解析路径：{meta.get('conversion', '?')}",
        f"顶层章节：{top_show}" if top_show else "顶层章节：（无——启发式未识别出结构）",
    ]
    if usage_hint:
        parts.append(
            f"下游精读时才需要：先读 {rel}/{name}.outline.json 按行号定位章节，"
            "再用 read_file(file_path=…, offset=起始行, limit=行数) 读对应区段"
        )
    parts.extend(f"⚠️ {w}" for w in meta.get("warnings") or [])
    return parts


@tool
def parse_document(path: str) -> str:
    """把文档（.docx/.pdf/.txt/.md）转换为 Markdown，并生成带行号区间的标题大纲与元信息。

    产物写入当前任务工作台的 out/parse/<文件名>/ 下三个文件（文件名=含扩展名的完整
    文件名——任务内同名即同文件，docx/pdf 同名不同扩展的产物互不覆盖）：
    - <文件名>.md：全文 Markdown（标题层级/表格 pipe 化；PDF 每页带 <!-- p:N --> 页码锚点）
    - <文件名>.outline.json：标题树，每个节点带 start_line/end_line 行号区间
    - <文件名>.meta.json：来源文件/sha256/解析路径(conversion)/顶层章节/质量警示

    结构识别分档（meta.conversion）：docx-native/pdf-toc=作者声明的结构（Word 样式/
    PDF 书签），可信；docx-numbered/pdf-fontsize=启发式（编号识别/字号判级），可能有误。
    同一文件内容未变（hash 一致）时重复调用会跳过重转（跳过同样返回全量概况，
    调用方无需读 meta.json 补数字）。下游分析技能精读时才用 outline.json 按行号
    定位区段；document-parse 阶段不需要读它。
    """
    try:
        ctx = runctx.current_run()
        task_id = ctx.task_id if ctx else None
        if not task_id:
            return "[解析失败] 缺少任务上下文：解析产物归属当前任务的 out/ 目录，请在任务会话中执行"
        src = _resolve_ws_path(path)
        if not src.is_file():
            return f"[解析失败] 文件不存在：{path}"
        if src.suffix.lower() in IMAGE_EXTS:
            return (
                "[解析失败] 任务场景暂不支持图片解析；图片请上传到知识库"
                "（知识库支持视觉模型识别），或改传 .docx / 文本型 PDF"
            )
        digest = sha256_file(src)
        # 目录与产物文件名都用完整文件名（含扩展名）：同名不同扩展（docx/pdf 双格式）
        # 的解析产物各有各的目录，不互相覆盖
        out_dir = task_out_dir(task_id) / "parse" / src.name
        md_path = out_dir / f"{src.name}.md"
        outline_path = out_dir / f"{src.name}.outline.json"
        meta_path = out_dir / f"{src.name}.meta.json"

        # 幂等：同 hash 且产物齐备则跳过
        if meta_path.is_file() and md_path.is_file() and outline_path.is_file():
            try:
                old = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                old = {}
            if old.get("sha256") == digest:
                rel = out_dir.relative_to(workspace_dir())
                return "\n".join(
                    _summary_lines(
                        f"[解析跳过] {src.name} 内容未变化（sha256 一致），沿用已有产物：{rel}/",
                        src.name,
                        rel,
                        old,
                        usage_hint=False,
                    )
                )

        result = parse_convert(src)
        md_text, info = result.md, result.info
        if len(md_text.strip()) < _MIN_TEXT_CHARS:
            raise ValueError(
                f"转换结果为空或极短（{len(md_text.strip())} 字符）。"
                "若输入为 PDF，疑似扫描件（图片型 PDF），当前不支持 OCR；请提供 .docx 或文本型 PDF"
            )
        outline = outline_with_lines(md_text)
        n_headings = count_nodes(outline)
        top_titles = [n["标题"] for n in outline]

        warnings: list[str] = []
        if n_headings == 0:
            warnings.append("未识别到任何标题层级，大纲导航不可用（改用 grep 关键词定位）")
        if info["conversion"] in ("docx-numbered", "pdf-fontsize"):
            warnings.append("结构来自启发式识别（无样式/无书签），层级可能不完整或有误")
        elif info["conversion"] == "docx-native" and len(top_titles) < 3:
            # 完整招标文件几乎必有多部分（公告/须知/评标/格式等）；顶层仅 1-2 个 =
            # 疑似节选卷册或正文章节未标记样式（实测语料：两份顶层 1-2 的均为节选，
            # 完整标书顶层全部 ≥4）。如实警示，确认门据此提醒用户补传其他卷册。
            warnings.append(
                f"顶层章节仅 {len(top_titles)} 个，疑似节选卷册或结构未完整标记，"
                "结构可能不完整（精读时建议结合 grep 关键词定位）"
            )

        out_dir.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_text, encoding="utf-8")
        outline_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = {
            "source": src.name,
            "sha256": digest,
            "bytes": src.stat().st_size,
            "conversion": info["conversion"],
            "chars": len(md_text),
            "headings": n_headings,
            "top_level_titles": len(top_titles),
            "top_level": top_titles[:12],
            "tables": info.get("tables", 0),
            "warnings": warnings,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if "pages" in info:
            meta["pages"] = info["pages"]
        if "body_size" in info:
            meta["body_size"] = info["body_size"]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        rel = out_dir.relative_to(workspace_dir())
        return "\n".join(
            _summary_lines(f"[解析成功] {src.name} → {rel}/", src.name, rel, meta, usage_hint=True)
        )
    except ValueError as e:
        return f"[解析失败] {e}"
    except Exception as e:  # 损坏文件等意外
        return f"[解析失败] {type(e).__name__}: {e}"
