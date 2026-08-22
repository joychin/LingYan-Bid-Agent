#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tender-toc — 招标文件解析 → 投标文件目录（TOC）技能脚本（Agent 原生版）

本脚本只做「确定性」工作，不再调用任何第三方 LLM：
  convert   把 .docx/.doc/.pdf 转成完整 Markdown（tender-full.md），交给 Agent 阅读分析。
  file      直接从 docx 标题层级抽取招标文件自身的目录 / 大纲（免 LLM）。
  build     读取 Agent 按提示词写出的中间产物，解析目录树 + 来源标注(lineage) + 目录说明，
            组装并导出 tender-directory.json 与 tender-registry.json。

「思考」类步骤（F1 结构抽取 / F2 需求 / F3 评分 / Step2 规划 / STEP3 补缺 /
修订② 评分对齐 / 修订③ 走查定稿）由 WorkBuddy 智能体（skill 的属主）按
references/prompts.md 的提示词逐步完成，并把结果写成 Markdown 文件，最后由本脚本 build 组装。

依赖：pip install python-docx
可选：LibreOffice（soffice）— 用于 .doc / .pdf → .docx 转换
"""

import os
import sys
import argparse
import re
import json
import copy
import html
import time
import shutil
import subprocess
import tempfile
from docx import Document


# ----------------------------------------------------------------------------
# 1) docx -> markdown（尽量保留标题层级与表格顺序）
# ----------------------------------------------------------------------------
def _heading_level(p):
    style_name = (p.style.name if p.style else "") or ""
    for prefix in ("Heading ", "标题 ", "heading "):
        if style_name.startswith(prefix):
            try:
                return int(style_name[len(prefix):].strip())
            except ValueError:
                pass
    try:
        pPr = p._p.pPr
        if pPr is not None and pPr.outlineLvl is not None:
            return int(pPr.outlineLvl.val) + 1
    except Exception:
        pass
    return 0


def _is_numbered(p):
    try:
        pPr = p._p.pPr
        if pPr is not None and pPr.numPr is not None:
            return True
    except Exception:
        pass
    return False


def _para_text(p):
    return p.text.strip()


def _cell_text(cell):
    txt = cell.text.replace("\n", " ").strip()
    return txt if txt else " "


def _table_to_md(table):
    rows = table.rows
    if not rows:
        return ""
    out = []
    header = [_cell_text(c) for c in rows[0].cells]
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(["---"] * len(header)) + " |")
    for r in rows[1:]:
        out.append("| " + " | ".join(_cell_text(c) for c in r.cells) + " |")
    return "\n".join(out)


def docx_to_markdown(path):
    doc = Document(path)
    lines = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph
            p = Paragraph(child, doc)
            text = _para_text(p)
            lvl = _heading_level(p)
            if lvl > 0:
                lines.append("#" * lvl + " " + text)
            elif _is_numbered(p):
                lines.append("- " + text)
            else:
                lines.append(text if text else "")
        elif tag == "tbl":
            from docx.table import Table
            t = Table(child, doc)
            lines.append("")
            lines.append(_table_to_md(t))
            lines.append("")
    out, blank = [], 0
    for ln in lines:
        if ln == "":
            blank += 1
            if blank <= 2:
                out.append(ln)
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out)


# ----------------------------------------------------------------------------
# 2) 招标文件自带目录 / 大纲抽取（file 子命令，免 LLM）
# ----------------------------------------------------------------------------
def md_headings_to_tree(md):
    root = []
    stack = [(-1, root)]
    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line.rstrip())
        if not m:
            continue
        title = m.group(2).strip()
        if not title:  # 跳过空标题（目录页残留的裸 # 等）
            continue
        level = len(m.group(1))
        node = {"标题": title, "level": level, "children": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((level, node["children"]))
    return root


def _iter_nodes(tree):
    for n in tree:
        yield n
        yield from _iter_nodes(n["children"])


# ----------------------------------------------------------------------------
# 3) 来源标注 / 目录说明 / 目录树 解析（供 build 使用）
# ----------------------------------------------------------------------------
ID_RE = re.compile(r"^(MAND|REQ|SCORE|TPL)-\d+$")


def _norm_id(i):
    """把来源ID的数字部分补零到两位（MAND-1 -> MAND-01），与 registry 键保持一致。"""
    return re.sub(r"(\d+)$", lambda m: m.group(1).zfill(2), i)


def _split_step1_sections(md):
    sections = {"structure": "", "mandatory": "", "templates": ""}
    cur = None
    for line in md.splitlines():
        if line.startswith("## 一、"):
            cur = "structure"
        elif line.startswith("## 二、"):
            cur = "mandatory"
        elif line.startswith("## 三、"):
            cur = "templates"
        if cur is not None:
            sections[cur] += line + "\n"
    return sections


def build_req_registry(req_md):
    reg, n = {}, 0
    for line in req_md.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "|" not in s:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        text = cells[0] if cells else ""
        rest = cells[1] if len(cells) > 1 else ""
        if not text or "---" in text or text in ("需求", "要求", "项目背景") or "出处" in text or "原文" in text:
            continue
        n += 1
        reg[f"REQ-{n:02d}"] = {"type": "需求", "text": text, "出处": rest}
    return reg


def build_score_registry(scoring_md):
    reg, n = {}, 0
    for line in scoring_md.splitlines():
        s = line.strip()
        if not s or "|" not in s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if not parts or not parts[0] or parts[0] in ("评分项", "评分标准") or "---" in parts[0]:
            continue
        n += 1
        reg[f"SCORE-{n:02d}"] = {
            "type": "评分点",
            "text": parts[0],
            "出处": parts[-1] if len(parts) > 1 else "",
        }
    return reg


def build_mand_tpl_registry(step1_md):
    sec = _split_step1_sections(step1_md)
    mand, nm = {}, 0
    for line in sec["mandatory"].splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or "---" in cells[0] or cells[0] in ("序号", "章节名称"):
            continue
        nm += 1
        src = cells[3] if len(cells) > 3 else (cells[-1] if len(cells) > 2 else "")
        mand[f"MAND-{nm:02d}"] = {"type": "招标文件规定", "text": cells[1], "出处": src}
    tpl, nt = {}, 0
    for line in sec["templates"].splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or "---" in cells[0] or cells[0] in ("序号", "模板名称"):
            continue
        nt += 1
        tpl[f"TPL-{nt:02d}"] = {
            "type": "模板",
            "text": cells[1],
            "出处": cells[-1] if len(cells) > 2 else "",
        }
    return mand, tpl


DIR_NOTE_RE = re.compile(
    r"^(?P<title>.+?)\s*::\s*交付形态=(?P<mode>[^|]+?)\s*"
    r"\|\s*归位理由=(?P<reason>[^|]*?)\s*"
    r"\|\s*理由来源=(?P<rids>[^|]*?)\s*"
    r"\|\s*概述=(?P<summary>.*)$"
)


def parse_trailer(md):
    result, in_block = {}, False
    for line in md.splitlines():
        if re.match(r"^#+\s*来源标注", line.strip()):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#+\s", line.strip()):
                break
            s = line.strip()
            if s.startswith(("-", "*")):
                body = s.lstrip("-*").strip()
            if "::" in body:
                title, _, ids = body.partition("::")
                title = title.strip()
                idlist = [_norm_id(x.strip()) for x in ids.split(",") if ID_RE.match(x.strip())]
                if title and idlist:
                    result.setdefault(title, [])
                    for i in idlist:
                        if i not in result[title]:
                            result[title].append(i)
    return result


def parse_dir_notes(md):
    result, in_block = {}, False
    for line in md.splitlines():
        if re.match(r"^#+\s*目录说明", line.strip()):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#+\s", line.strip()):
                break
            s = line.strip()
            if s.startswith(("-", "*")):
                m = DIR_NOTE_RE.match(s.lstrip("-*").strip())
                if m:
                    title = m.group("title").strip()
                    mode = m.group("mode").strip()
                    reason = m.group("reason").strip()
                    rids = [_norm_id(x.strip()) for x in m.group("rids").split(",") if ID_RE.match(x.strip())]
                    summary = m.group("summary").strip()
                    if title:
                        result[title] = {
                            "delivery_mode": mode,
                            "placement_reason": reason,
                            "reason_source_ids": rids,
                            "brief_summary": summary,
                        }
    return result


def strip_section(md, section_name):
    out, in_block = [], False
    for line in md.splitlines():
        if re.match(rf"^#+\s*{re.escape(section_name)}", line.strip()):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#+\s", line.strip()):
                in_block = False
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def strip_trailer(md):
    return strip_section(md, "来源标注")


def md_to_tree(md):
    """将无编号缩进列表（Markdown）解析为嵌套树 [{目录名称,level,children}]。
    level 在解析后按树深度统一赋值，不依赖具体缩进宽度（兼容 2/4 空格或 Tab）。"""
    root = []
    stack = [(-1, root)]
    for line in md.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^(\s*)[-*]\s+(.*)$", line.rstrip())
        if not m:
            continue
        indent = len(m.group(1).replace("\t", "  "))
        level = indent // 2 + 1
        node = {"目录名称": m.group(2).strip(), "level": level, "children": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((level, node["children"]))
    _assign_levels(root, 1)
    return root


def _assign_levels(nodes, base):
    """按实际树深度重写 level（1 起），修复缩进宽度不统一造成的 level 与嵌套深度不一致。"""
    for n in nodes:
        n["level"] = base
        _assign_levels(n.get("children", []), base + 1)
    return nodes


def _source_type(rid):
    if rid.startswith("MAND"):
        return "招标文件规定"
    if rid.startswith("REQ"):
        return "需求"
    if rid.startswith("SCORE"):
        return "评分点"
    if rid.startswith("TPL"):
        return "模板"
    return "其他"


def _match_ids(title, lineage_map):
    if title in lineage_map:
        return lineage_map[title]
    for k, v in lineage_map.items():
        if k and (k in title or title in k):
            return v
    return []


def attach_lineage(tree, lineage_map, dir_notes=None):
    for node in tree:
        ids = _match_ids(node["目录名称"], lineage_map)
        node["来源"] = sorted({_source_type(i) for i in ids}) if ids else []
        node["来源位置"] = ids if ids else []
        if dir_notes:
            note = dir_notes.get(node["目录名称"]) or {}
            node["交付形态"] = note.get("delivery_mode", "")
            node["归位理由"] = note.get("placement_reason", "")
            node["理由来源"] = note.get("reason_source_ids", [])
            node["节点概述"] = note.get("brief_summary", "")
        attach_lineage(node["children"], lineage_map, dir_notes)


def _extract_section(body, name):
    """返回 body 中 `## <name>`（行尾精确匹配）与下一个 `##` 之间的文本。"""
    out, in_block = [], False
    for line in body.splitlines():
        if re.match(rf"^##\s*{re.escape(name)}\s*$", line.strip()):
            in_block = True
            continue
        if in_block:
            if re.match(r"^##\s", line.strip()):
                break
            out.append(line)
    return "\n".join(out)


def _before_section(body, name):
    """返回 body 中 `## <name>`（行尾精确匹配）之前的文本。"""
    out = []
    for line in body.splitlines():
        if re.match(rf"^##\s*{re.escape(name)}\s*$", line.strip()):
            break
        out.append(line)
    return "\n".join(out)


def parse_response_docs(md):
    """解析 `tender-response-docs.md`：每个顶层 `# 响应文件：XXX` 为一个响应文件，
    内含 `## 目录`（树）、`## 来源标注`、`## 目录说明`。"""
    segments, cur = [], None
    for line in md.splitlines():
        if re.match(r"^#\s(?![#])\s*(.+)$", line):
            if cur is not None:
                segments.append(cur)
            cur = {"header": line.strip(), "body": []}
        elif cur is not None:
            cur["body"].append(line)
    if cur is not None:
        segments.append(cur)
    docs = []
    for seg in segments:
        m = re.match(r"^#\s(?![#])\s*(?:响应文件[：:]\s*)?(.+?)\s*$", seg["header"])
        name = m.group(1).strip() if m else seg["header"].lstrip("#").strip()
        body = "\n".join(seg["body"])
        dir_sec = _extract_section(body, "目录")
        lineage = parse_trailer(body)
        notes = parse_dir_notes(body)
        tree = md_to_tree(dir_sec) if dir_sec.strip() else []
        attach_lineage(tree, lineage, notes)
        scope = _before_section(body, "目录").strip()
        for prefix in ("scope：", "scope:", "Scope："):
            if scope.startswith(prefix):
                scope = scope[len(prefix):].strip()
                break
        docs.append({"name": name, "scope": scope, "directory": tree})
    return docs


def parse_meta(md):
    """提取可选的 `## 项目信息` 段（位于文件顶部，二级标题，解析器忽略其作为响应文件段）。
    支持 `- 键：值` 或 `| 键 | 值 |` 表格两种写法。"""
    meta, in_block = {}, False
    for line in md.splitlines():
        s = line.strip()
        if re.match(r"^##\s*项目信息\s*$", s):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#+\s", s):
                break
            m = re.match(r"^[-*]\s*(.+?)[：:]\s*(.+)$", s)
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
                continue
            if s.startswith("|") and "|" in s[1:]:
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) == 2 and cells[0] and "---" not in cells[0] \
                        and cells[0] not in ("键", "项目"):
                    meta[cells[0]] = cells[1]
    return meta


def _relevel(tree, base):
    """把目录树各节点的 level 整体下移（从 base 起），用于聚合视图。"""
    for n in tree:
        n["level"] = base
        _relevel(n.get("children", []), base + 1)
    return tree


# ----------------------------------------------------------------------------
# 3.5) HTML 渲染（人类可读交付物 tender-directory.html）
# ----------------------------------------------------------------------------
_MODE_CLASS = {"MAND": "b-mand", "TPL": "b-tpl", "REQ": "b-req", "SCORE": "b-score"}


def _esc(s):
    return html.escape(str(s or ""))


def _node_html(n):
    ids = n.get("来源位置", []) or []
    badges = "".join(
        f'<span class="b {_MODE_CLASS.get(i.split("-")[0], "b-req")}" '
        f'data-id="{_esc(i)}">{_esc(i)}</span>'
        for i in ids
    )
    mode = n.get("交付形态", "") or ""
    mode_tag = f'<span class="mode">{_esc(mode)}</span>' if mode else ""
    detail_parts = []
    if n.get("节点概述"):
        detail_parts.append("概述：" + _esc(n["节点概述"]))
    if n.get("归位理由"):
        detail_parts.append("归位理由：" + _esc(n["归位理由"]))
    detail = f'<div class="detail">{" · ".join(detail_parts)}</div>' if detail_parts else ""
    kids = n.get("children", []) or []
    kids_html = ""
    if kids:
        kids_html = "<ul>" + "".join(_node_html(k) for k in kids) + "</ul>"
    caret = '<span class="caret">▾</span>' if kids else '<span class="caret"></span>'
    return (f'<li><div class="node">{caret}'
            f'<span class="name">{_esc(n["目录名称"])}</span>{mode_tag}{badges}{detail}</div>'
            f'{kids_html}</li>')


def _tree_html(tree):
    return '<ul class="tree">' + "".join(_node_html(n) for n in tree) + "</ul>"


def _registry_html(registry):
    groups = {"MAND": [], "TPL": [], "REQ": [], "SCORE": []}
    for k, v in registry.items():
        p = k.split("-")[0]
        if p in groups:
            groups[p].append((k, v))
    labels = [("MAND", "招标文件规定"), ("TPL", "模板"),
              ("REQ", "需求"), ("SCORE", "评分点")]
    out = []
    for p, label in labels:
        rows = sorted(groups.get(p, []))
        trs = "".join(
            f'<tr><td class="rid">{_esc(k)}</td><td>{_esc(v.get("text", ""))}</td>'
            f'<td class="src">{_esc(v.get("出处", ""))}</td></tr>'
            for k, v in rows
        )
        out.append(
            f'<h3>{_esc(label)} <span class="cnt">{len(rows)}</span></h3>'
            f'<table><thead><tr><th>ID</th><th>内容</th><th>出处</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>'
        )
    return "".join(out)


def render_html(docs, registry, meta, out_path, unused_ids=None, dangling_ids=None):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    total_nodes = sum(1 for d in docs for _ in _iter_nodes(d["directory"]))
    cnt = {"MAND": 0, "TPL": 0, "REQ": 0, "SCORE": 0}
    for k in registry:
        p = k.split("-")[0]
        if p in cnt:
            cnt[p] += 1
    meta_html = ""
    if meta:
        meta_html = '<div class="meta">' + " · ".join(
            f"{_esc(k)}：{_esc(v)}" for k, v in meta.items()
        ) + "</div>"
    docs_html = []
    for i, d in enumerate(docs, 1):
        scope = d.get("scope", "") or ""
        docs_html.append(
            f'<section class="doc" id="doc-{i}">'
            f'<h2><span class="doc-no">{i}</span>{_esc(d["name"])}</h2>'
            + (f'<p class="scope">{scope}</p>' if scope else "")
            + _tree_html(d["directory"])
            + "</section>"
        )
    note_parts = []
    if unused_ids:
        note_parts.append(
            "以下来源ID未被任何目录节点引用：" + "、".join(f"<b>{_esc(u)}</b>" for u in unused_ids)
            + "，建议核查是否为漏标。")
    if dangling_ids:
        note_parts.append(
            "以下来源ID被引用但 registry 中不存在（悬空）：" + "、".join(f"<b>{_esc(d)}</b>" for d in dangling_ids)
            + "，请检查 F2/F3 行序是否漂移或编号拼写。")
    check_html = (f'<div class="note">⚠️ lineage 完整性检查：{" ".join(note_parts)}</div>'
                  if note_parts else "")
    reg_json = json.dumps(registry, ensure_ascii=False) \
        .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    nodes_by_id = {}
    for d in docs:
        for n in _iter_nodes(d["directory"]):
            for i in n.get("来源位置", []) or []:
                nodes_by_id.setdefault(i, []).append(n["目录名称"])
    nodes_json = json.dumps(nodes_by_id, ensure_ascii=False) \
        .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>投标文件目录规划（tender-toc）</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e5e7eb;--ink:#1f2937;--muted:#6b7280;
--b-mand:#2563eb;--b-tpl:#7c3aed;--b-req:#059669;--b-score:#d97706}}
*{{box-sizing:border-box}}
body{{font-family:"PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;
margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.7}}
header{{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;padding:24px 32px}}
header h1{{margin:0 0 6px;font-size:22px}}
header .meta{{opacity:.92;font-size:13px}}
.stats{{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}}
.chip{{background:rgba(255,255,255,.16);border-radius:999px;padding:3px 12px;font-size:12px}}
main{{max-width:1080px;margin:0 auto;padding:24px 20px 8px}}
.toolbar{{text-align:right;margin-bottom:10px}}
.toolbar button{{border:1px solid var(--line);background:#fff;border-radius:8px;
padding:4px 12px;cursor:pointer;font-size:12px;margin-left:6px}}
.doc{{background:var(--card);border:1px solid var(--line);border-radius:12px;
margin-bottom:18px;padding:18px 22px}}
.doc h2{{font-size:17px;margin:0 0 8px;display:flex;align-items:center;gap:10px}}
.doc-no{{background:#2563eb;color:#fff;border-radius:6px;padding:2px 9px;font-size:13px}}
.scope{{color:var(--muted);font-size:13px;border-left:3px solid #bfdbfe;
padding-left:10px;margin:0 0 12px}}
ul.tree,ul.tree ul{{list-style:none;margin:0;padding-left:0}}
ul.tree ul{{padding-left:22px;border-left:1px dashed var(--line)}}
.node{{padding:6px 8px;border-radius:8px;display:flex;align-items:flex-start;
gap:8px;flex-wrap:wrap}}
.node:hover{{background:#f3f4f6}}
.caret{{display:inline-block;width:14px;color:var(--muted);user-select:none;
cursor:pointer;text-align:center}}
.name{{font-weight:600}}
.mode{{font-size:11px;color:var(--muted);border:1px solid var(--line);
border-radius:999px;padding:0 8px;align-self:center;white-space:nowrap}}
.b{{font-size:11px;color:#fff;border-radius:4px;padding:0 6px;align-self:center;
letter-spacing:.3px;white-space:nowrap;cursor:pointer}}
.b-mand{{background:var(--b-mand)}}.b-tpl{{background:var(--b-tpl)}}
.b-req{{background:var(--b-req)}}.b-score{{background:var(--b-score)}}
.b:hover{{filter:brightness(1.12)}}
.modal-backdrop{{position:fixed;inset:0;z-index:100;background:rgba(15,23,42,.45);
display:none;align-items:center;justify-content:center;padding:24px}}
.modal-card{{background:#fff;color:var(--ink);border-radius:14px;width:100%;max-width:640px;
max-height:84vh;display:flex;flex-direction:column;box-shadow:0 24px 60px rgba(0,0,0,.35)}}
.m-head{{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;
border-bottom:1px solid var(--line)}}
.m-title{{font-weight:700;font-size:15px}}
.m-close{{border:none;background:#f3f4f6;border-radius:8px;width:30px;height:30px;cursor:pointer;
font-size:14px;color:var(--muted)}}
.m-close:hover{{background:#e5e7eb}}
.m-body{{padding:16px 18px;overflow-y:auto}}
.m-field{{margin-bottom:14px}}
.m-label{{font-size:12px;color:var(--muted);margin-bottom:4px;font-weight:600}}
.m-text{{font-size:14px;line-height:1.8;background:#f8fafc;border:1px solid var(--line);
border-radius:8px;padding:10px 12px}}
.m-src{{font-size:13px;color:#334155}}
.m-nodes{{display:flex;flex-direction:column;gap:4px}}
.m-node{{font-size:13px;background:#eef2ff;color:#3730a3;border-radius:6px;padding:4px 10px}}
.m-none{{font-size:13px;color:var(--muted)}}
.detail{{width:100%;font-size:12px;color:var(--muted);padding-left:22px}}
.collapsed>ul{{display:none}}
.collapsed>.node>.caret{{transform:rotate(-90deg)}}
h3{{font-size:15px;margin:26px 0 8px;display:flex;align-items:center;gap:8px}}
.cnt{{background:#eef2ff;color:#3730a3;border-radius:999px;padding:0 8px;font-size:12px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:8px}}
th,td{{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}}
th{{background:#f9fafb;white-space:nowrap}}
.rid{{font-family:ui-monospace,Menlo,Consolas,monospace;font-weight:600;white-space:nowrap}}
td.src{{color:var(--muted);font-size:12px}}
.note{{background:#fffbeb;border:1px solid #fde68a;color:#92400e;border-radius:8px;
padding:10px 14px;font-size:13px;margin-bottom:18px}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding:16px 20px 28px}}
@media print{{header{{background:#1e3a8a;-webkit-print-color-adjust:exact}}
body{{background:#fff}}.doc{{break-inside:avoid}}}}
</style>
</head>
<body>
<header>
<h1>📑 投标文件目录规划</h1>
{meta_html}
<div class="stats">
<span class="chip">响应文件 {len(docs)} 个</span>
<span class="chip">目录节点 {total_nodes} 个</span>
<span class="chip">MAND {cnt['MAND']}</span>
<span class="chip">TPL {cnt['TPL']}</span>
<span class="chip">REQ {cnt['REQ']}</span>
<span class="chip">SCORE {cnt['SCORE']}</span>
</div>
</header>
<main>
<div class="toolbar">
<button onclick="setAll(true)">全部折叠</button>
<button onclick="setAll(false)">全部展开</button>
</div>
{check_html}
{"".join(docs_html)}
<section class="doc" id="registry">
<h2>📋 来源登记表（registry）</h2>
{_registry_html(registry)}
</section>
</main>
<div class="modal-backdrop" id="modal">
<div class="modal-card" role="dialog" aria-modal="true">
<div class="m-head">
<span class="m-title" id="m-title"></span>
<button class="m-close" id="m-close" aria-label="关闭">✕</button>
</div>
<div class="m-body">
<div class="m-field"><div class="m-label">原文片段</div><div class="m-text" id="m-text"></div></div>
<div class="m-field"><div class="m-label">原文位置</div><div class="m-src" id="m-src"></div></div>
<div class="m-field"><div class="m-label">关联目录节点</div><div class="m-nodes" id="m-nodes"></div></div>
</div>
</div>
</div>
<footer>由 tender-toc 技能生成 · {now}</footer>
<script>
const REGISTRY = {reg_json};
const NODES_BY_ID = {nodes_json};
function esc_html(s){{var d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML;}}
document.querySelectorAll('.caret').forEach(function(c){{
  c.addEventListener('click', function(e){{
    e.stopPropagation();
    var li=c.closest('li'); li.classList.toggle('collapsed');
    c.textContent = li.classList.contains('collapsed') ? '▸' : '▾';
  }});
}});
function setAll(collapse){{
  document.querySelectorAll('ul.tree li').forEach(function(li){{
    var c=li.querySelector(':scope > .node > .caret');
    var ul=li.querySelector(':scope > ul');
    if(!c || !ul) return;
    li.classList.toggle('collapsed', collapse);
    c.textContent = collapse ? '▸' : '▾';
  }});
}}
var modal=document.getElementById('modal');
var mTitle=document.getElementById('m-title'), mText=document.getElementById('m-text'),
    mSrc=document.getElementById('m-src'), mNodes=document.getElementById('m-nodes'),
    mClose=document.getElementById('m-close');
function showModal(id){{
  var r=REGISTRY[id]; if(!r) return;
  mTitle.textContent = id + ' · ' + (r.type||'');
  mText.textContent = r.text||'';
  mSrc.textContent = r['出处']||'';
  var ns=(NODES_BY_ID[id]||[]).map(esc_html);
  mNodes.innerHTML = ns.length
    ? ns.map(function(t){{return '<div class="m-node">'+t+'</div>';}}).join('')
    : '<span class="m-none">（无）</span>';
  modal.style.display='flex';
}}
function closeModal(){{ modal.style.display='none'; }}
document.querySelectorAll('.b').forEach(function(b){{
  var id=b.getAttribute('data-id');
  var r=REGISTRY[id];
  if(r) b.title = r.type + '：' + r.text + '（' + (r['出处']||'') + '）';
  b.addEventListener('click', function(e){{
    e.stopPropagation();
    showModal(b.getAttribute('data-id'));
  }});
}});
mClose.addEventListener('click', closeModal);
modal.addEventListener('click', function(e){{ if(e.target===modal) closeModal(); }});
document.addEventListener('keydown', function(e){{ if(e.key==='Escape') closeModal(); }});
</script>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return total_nodes


# ----------------------------------------------------------------------------
# 4) 输入处理：.docx 原生；.doc/.pdf 经 soffice 转 docx
# ----------------------------------------------------------------------------
def ensure_docx(path, workdir):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return path
    if ext in (".doc", ".pdf"):
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            sys.exit(
                f"❌ 输入为 {ext}，需 LibreOffice(soffice) 转成 docx，但未找到 soffice。\n"
                f"   请安装 LibreOffice 后重试，或先手动把文件另存为 .docx。"
            )
        tmp = tempfile.mkdtemp(prefix="tender-toc-")
        out = os.path.join(tmp, "converted.docx")
        print(f"[0] 用 soffice 把 {os.path.basename(path)} 转为 docx ...")
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, path],
            check=True, capture_output=True,
        )
        if not os.path.exists(out):
            sys.exit(f"❌ soffice 转换失败，未生成 {out}")
        return out
    sys.exit(f"❌ 不支持的输入格式：{ext}（仅支持 .docx / .doc / .pdf）")


# ----------------------------------------------------------------------------
# 5) 子命令
# ----------------------------------------------------------------------------
def cmd_convert(args):
    docx_path = ensure_docx(args.docx, args.outdir)
    print("[1] 读取 docx 并转为 Markdown ...")
    markdown = docx_to_markdown(docx_path)
    full_md_path = os.path.join(args.outdir, "tender-full.md")
    with open(full_md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"      完成，字符数={len(markdown)} -> {full_md_path}")
    print("      接下来：由 Agent 按 references/prompts.md 的提示词逐步分析，写出")
    print("      tender-extraction.md / tender-index-tight.md / tender-scoring.md / tender-response-docs.md，")
    print("      最后运行 `python parse_toc.py build --outdir <outdir>` 组装目录 JSON + HTML。")


def cmd_file(args):
    docx_path = ensure_docx(args.docx, args.outdir)
    print("[1] 读取 docx 并转为 Markdown ...")
    markdown = docx_to_markdown(docx_path)
    print(f"      字符数={len(markdown)}")
    print("[2] 从标题层级抽取招标文件自带目录 / 大纲 ...")
    tree = md_headings_to_tree(markdown)
    if not tree:
        with open(os.path.join(args.outdir, "tender-file-toc.json"), "w", encoding="utf-8") as f:
            json.dump({"toc": [], "warning": "未在文档中发现任何标题层级，可能该文件无结构化目录。"},
                      f, ensure_ascii=False, indent=2)
        print("⚠️ 未发现标题，已写 warning。")
        return
    with open(os.path.join(args.outdir, "tender-file-toc.json"), "w", encoding="utf-8") as f:
        json.dump({"toc": tree}, f, ensure_ascii=False, indent=2)
    lines = ["# 招标文件自带目录 / 大纲（file 模式，无 LLM）", ""]
    def _emit(t, depth=0):
        for n in t:
            lines.append("#" * (depth + 1) + " " + n["标题"])
            _emit(n["children"], depth + 1)
    _emit(tree)
    with open(os.path.join(args.outdir, "tender-file-toc.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"      大纲节点数={sum(1 for _ in _iter_nodes(tree))} -> tender-file-toc.json / .md")


def cmd_build(args):
    outdir = args.outdir
    extraction = os.path.join(outdir, "tender-extraction.md")
    req_path = os.path.join(outdir, "tender-index-tight.md")
    resp_docs = os.path.join(outdir, "tender-response-docs.md")
    plan_final = os.path.join(outdir, "tender-plan-final.md")

    missing = [p for p in (extraction, req_path) if not os.path.exists(p)]
    if missing:
        sys.exit(
            "❌ build 缺少 Agent 产出的中间文件：\n  " + "\n  ".join(missing) +
            "\n   请先由 Agent 按 references/prompts.md 完成分析并写出这些文件，再运行 build。"
        )
    # 响应文件目录：新版 tender-response-docs.md，或兼容旧版单文档 tender-plan-final.md
    if not os.path.exists(resp_docs) and not os.path.exists(plan_final):
        sys.exit(
            "❌ build 缺少目录产出文件：tender-response-docs.md（多响应文件）或 "
            "tender-plan-final.md（旧版单文档）。\n   请先由 Agent 写出响应文件目录，再运行 build。"
        )

    with open(extraction, "r", encoding="utf-8") as f:
        md_report = f.read()
    with open(req_path, "r", encoding="utf-8") as f:
        req_raw = f.read()

    scoring_md = ""
    scoring_file = os.path.join(outdir, "tender-scoring.md")
    if os.path.exists(scoring_file):
        with open(scoring_file, "r", encoding="utf-8") as f:
            scoring_md = f.read()

    print("[build] 构建来源登记表 ...")
    mand_reg, tpl_reg = build_mand_tpl_registry(md_report)
    req_reg = build_req_registry(req_raw)
    score_reg = build_score_registry(scoring_md) if scoring_md.strip() else {}
    registry = {}
    for d in (mand_reg, tpl_reg, req_reg, score_reg):
        registry.update(d)
    reg_path = os.path.join(outdir, "tender-registry.json")
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    print(f"      MAND={len(mand_reg)} TPL={len(tpl_reg)} REQ={len(req_reg)} "
          f"SCORE={len(score_reg)} -> {reg_path}")

    print("[build] 解析响应文件目录树 ...")
    raw_md = ""
    if os.path.exists(resp_docs):
        with open(resp_docs, "r", encoding="utf-8") as f:
            raw_md = f.read()
        docs = parse_response_docs(raw_md)
    else:
        # 兼容旧版：整个 tender-plan-final.md 作为单一合并响应文件
        with open(plan_final, "r", encoding="utf-8") as f:
            raw_md = f.read()
        lineage = parse_trailer(raw_md)
        notes = parse_dir_notes(raw_md)
        tree = md_to_tree(strip_section(strip_trailer(raw_md), "目录说明"))
        attach_lineage(tree, lineage, notes)
        docs = [{"name": "投标文件（合并）", "scope": "", "directory": tree}]

    meta = parse_meta(raw_md)
    referenced = set()
    for d in docs:
        for n in _iter_nodes(d["directory"]):
            referenced.update(n.get("来源位置", []) or [])
    unused_ids = sorted(k for k in registry if k not in referenced)
    dangling_ids = sorted(i for i in referenced if i not in registry)
    lineage_check = {"unused_ids": unused_ids, "dangling_ids": dangling_ids}

    if not docs or all(not d["directory"] for d in docs):
        out = {"response_documents": docs, "registry": registry, "meta": meta,
               "lineage_check": lineage_check,
               "warning": "未解析出任何响应文件目录，请检查 tender-response-docs.md 格式。"}
        dir_path = os.path.join(outdir, "tender-response-docs.json")
        with open(dir_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("⚠️ 响应文件目录为空，已写 warning。")
        return

    out = {"response_documents": docs, "registry": registry, "meta": meta,
           "lineage_check": lineage_check}
    dir_path = os.path.join(outdir, "tender-response-docs.json")
    with open(dir_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 兼容聚合视图：每个响应文件作为顶层节点（子目录整体下移一层），便于只需单棵树的下游消费
    agg_docs = copy.deepcopy(docs)
    agg = {"directory": [
        {"目录名称": d["name"], "level": 1,
         "children": _relevel(d["directory"], 2),
         "scope": d.get("scope", ""),
         "来源": [], "来源位置": [], "交付形态": "", "归位理由": "",
         "理由来源": [], "节点概述": ""} for d in agg_docs
    ], "registry": registry, "meta": meta, "lineage_check": lineage_check}
    agg_path = os.path.join(outdir, "tender-directory.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)
    total = sum(1 for d in docs for _ in _iter_nodes(d["directory"]))
    print(f"      响应文件数={len(docs)}，目录节点总数={total} -> {dir_path} (+ {agg_path})")
    if unused_ids:
        print(f"⚠️ lineage 完整性检查：未引用的来源ID={unused_ids}")
    if dangling_ids:
        print(f"⚠️ lineage 完整性检查：悬空来源ID（被引用但 registry 中不存在）={dangling_ids}")
    print("[build] 渲染 HTML 交付物 ...")
    html_path = os.path.join(outdir, "tender-directory.html")
    render_html(docs, registry, meta, html_path,
                unused_ids=unused_ids, dangling_ids=dangling_ids)
    print(f"      -> {html_path}")
    print("Done.")


def main():
    ap = argparse.ArgumentParser(description="招标文件解析 → 投标文件目录(TOC) 技能脚本（Agent 原生版）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_c = sub.add_parser("convert", help="docx/doc/pdf → tender-full.md（交给 Agent 分析）")
    p_c.add_argument("docx", help="输入文件 .docx / .doc / .pdf")
    p_c.add_argument("--outdir", default=".", help="输出目录")
    p_c.set_defaults(func=cmd_convert)

    p_f = sub.add_parser("file", help="仅抽招标文件自身标题大纲（免 LLM）")
    p_f.add_argument("docx", help="输入文件 .docx / .doc / .pdf")
    p_f.add_argument("--outdir", default=".", help="输出目录")
    p_f.set_defaults(func=cmd_file)

    p_b = sub.add_parser("build", help="读取 Agent 产出 → 组装 tender-directory.json/.html")
    p_b.add_argument("--outdir", default=".", help="含 Agent 中间产物的目录")
    p_b.set_defaults(func=cmd_build)

    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
