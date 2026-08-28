"""确定性文档解析工具（LLM 工具层薄壳）：.docx/.pdf/.txt/.md → Markdown + 带行号区间的标题大纲。

转换核心在 app/parse/（注册表，知识库入库管线共用）；本文件只保留工具层职责：
任务上下文校验、workspace 路径 containment、hash 幂等、产物落盘（任务 out/parse/）、
概况文案、以及云端文档解析路由（见下）。

云端文档解析（百度云 PaddleOCR-VL，已配置才触发）：扫描 PDF（文本层过薄）与 .doc /
图片这类本地注册表不收的格式路由到 parse_via_baidu 整本解析（文档级 API 无逐页接口）；
未配置时维持明确拒绝并提示配置入口。同 hash 幂等检查在路由之前，重复调用不重复
产生云端花费。数字版 PDF 永远走本地 PyMuPDF（书签/目录链接结构识别只在本地有）。

结构识别按可信度分档（meta.conversion 记录，下游引用出处时按档位决定是否署章节名）：
- docx-native / pdf-toc：作者声明的结构（Word 标题样式 / PDF 书签树）——可信；
- pdf-link-toc：目录条目自带的内部超链接（Word 目录域生成）——硬标记+精确目标页；
- pdf-printed-toc：印刷目录页解析（文件自己印的目录）——作者自报，可靠性接近声明档；
- docx-numbered / pdf-numbered：中文编号识别（标题文字印在原文行上，可回原文验证）
  ——层级可能不完整，产物带警示；
- pdf-plain：未识别出结构（无书签/无印刷目录/无编号）——大纲不可用，警示 grep 兜底；
- paddleocr-vl：云端 OCR 识别（标题非作者声明，署名纪律同 pdf-plain）。
不使用字号判级（实测政采 PDF 章标题字号常与正文相同、封面全是巨字，信号不成立）。
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

from .. import baidu_ocr, runctx
from ..artifact_store import task_files_dir, task_out_dir
from ..config import workspace_dir
from ..parse import convert as parse_convert
from ..parse import count_nodes, outline_with_lines, sha256_file
from ..parse.image import IMAGE_EXTS

_MIN_TEXT_CHARS = 100  # 低于此值视为转换失败（扫描件/损坏文件）
_CLOUD_ONLY_EXTS = {".doc"}  # 本地注册表不收、云端文档解析专属的格式


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
    """把文档（.docx/.pdf/.txt/.md，图片/.doc 需配置文档解析）转换为 Markdown，
    并生成带行号区间的标题大纲与元信息。

    产物写入当前任务工作台的 out/parse/<文件名>/ 下三个文件（文件名=含扩展名的完整
    文件名——任务内同名即同文件，docx/pdf 同名不同扩展的产物互不覆盖）：
    - <文件名>.md：全文 Markdown（标题层级/表格 pipe 化；PDF 每页带 <!-- p:N --> 页码锚点）
    - <文件名>.outline.json：标题树，每个节点带 start_line/end_line 行号区间
    - <文件名>.meta.json：来源文件/sha256/解析路径(conversion)/顶层章节/质量警示

    结构识别分档（meta.conversion）：docx-native/pdf-toc=作者声明的结构（Word 样式/
    PDF 书签），可信；pdf-link-toc=目录页内部超链接（Word 目录域生成的硬标记）；
    pdf-printed-toc=印刷目录页解析（文件自己印的目录，可靠性接近作者声明）；
    docx-numbered/pdf-numbered=中文编号识别（标题文字印在原文行上，可回原文验证，
    但层级可能不完整）；pdf-plain=未识别出结构（大纲不可用，下游改用 grep 定位）；
    paddleocr-vl=云端 OCR 识别（扫描件/.doc/图片，标题非作者声明，引用出处按
    pdf-plain 纪律处理）。不使用字号判级（实测政采 PDF 章标题字号常与正文相同、
    封面全是巨字，字号信号在这类文档上不成立）。
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

        # 解析路由：图片/.doc 走云端文档解析（未配置则明确拒绝）；其余走本地注册表，
        # PDF 文本层过薄（扫描件）时若有云端配置则整本替换解析（幂等检查已在前面，
        # 重复调用不会重复产生云端花费）。经模块属性调用 baidu_ocr.parse_via_baidu，
        # 便于测试 monkeypatch 且不触碰网络
        ext = src.suffix.lower()
        cloud_ready = baidu_ocr.baidu_ocr_available()
        if ext in IMAGE_EXTS or ext in _CLOUD_ONLY_EXTS:
            if not cloud_ready:
                raise ValueError(
                    f"暂不支持解析 {ext or '(无扩展名)'}：可在设置中配置文档解析"
                    "（百度云 PaddleOCR-VL）后重试"
                    + ("；图片也可上传到知识库（知识库支持视觉模型识别）" if ext in IMAGE_EXTS else "")
                    + ("；.doc 也可用 Word 另存为 .docx 后上传" if ext in _CLOUD_ONLY_EXTS else "")
                )
            result = baidu_ocr.parse_via_baidu(src)
        else:
            result = parse_convert(src)
            if ext == ".pdf" and len(result.md.strip()) < _MIN_TEXT_CHARS:
                if not cloud_ready:
                    raise ValueError(
                        f"转换结果为空或极短（{len(result.md.strip())} 字符）。"
                        "若输入为 PDF，疑似扫描件（图片型 PDF）：可在设置中配置文档解析"
                        "（百度云）后重试，或提供 .docx / 文本型 PDF"
                    )
                result = baidu_ocr.parse_via_baidu(src)
        md_text, info = result.md, result.info
        if len(md_text.strip()) < _MIN_TEXT_CHARS:
            raise ValueError(f"解析结果为空或极短（{len(md_text.strip())} 字符），无法继续")
        outline = outline_with_lines(md_text)
        n_headings = count_nodes(outline)
        top_titles = [n["标题"] for n in outline]

        warnings: list[str] = []
        if info["conversion"] == "pdf-plain":
            # pdf-plain ⟹ md 无标题行（不足门槛的零星编号已丢弃），必伴随
            # n_headings==0——用档位专属警示，不与通用无标题警示叠加
            warnings.append("未识别出章节结构（无书签/无印刷目录/无编号），大纲不可用，请以 grep 全文检索定位")
        elif n_headings == 0:
            warnings.append("未识别到任何标题层级，大纲导航不可用（改用 grep 关键词定位）")
        elif info["conversion"] in ("docx-numbered", "pdf-numbered"):
            warnings.append("结构来自中文编号识别（标题文字印在原文，可回原文验证），层级可能不完整")
        # 完整招标文件几乎必有多部分（公告/须知/评标/格式等）；顶层仅 1-2 个 =
        # 疑似节选卷册或结构未完整标记（实测语料：两份顶层 1-2 的均为节选，
        # 完整标书顶层全部 ≥4）。如实警示，确认门据此提醒用户补传其他卷册。
        elif len(top_titles) < 3:
            warnings.append(
                f"顶层章节仅 {len(top_titles)} 个，疑似节选卷册或结构未完整标记，"
                "结构可能不完整（精读时建议结合 grep 关键词定位）"
            )
        # 云端解析等转换器自带的质量警示（OCR 识别建议核对等）
        warnings.extend(info.get("warnings") or [])

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
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        rel = out_dir.relative_to(workspace_dir())
        return "\n".join(
            _summary_lines(f"[解析成功] {src.name} → {rel}/", src.name, rel, meta, usage_hint=True)
        )
    except ValueError as e:
        return f"[解析失败] {e}"
    except Exception as e:  # 损坏文件等意外
        return f"[解析失败] {type(e).__name__}: {e}"
