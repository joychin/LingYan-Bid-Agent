"""check_pipeline_state 工具：任务流水线事实状态报告（纯事实、零结论）。"""

import json
import os
from datetime import datetime

import pytest

from app import artifact_store, runctx
from app.tools.check_pipeline import check_pipeline_state
from tests.util import init_env


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_test", task["id"])
    yield task, conv
    runctx.clear_run()


def _wroot(task):
    return artifact_store.work_dir(task["id"])


def _seed_sources_file(task, files, main, supplements=(), excluded=()):
    sroot = artifact_store.sources_dir(task["id"])
    sroot.mkdir(parents=True, exist_ok=True)
    for name in files:
        (sroot / name).write_bytes(b"x")
    proot = _wroot(task) / "parse"
    proot.mkdir(parents=True, exist_ok=True)
    (proot / "sources.json").write_text(
        json.dumps(
            {
                "main": main,
                "supplements": [{"file": f, "role": r} for f, r in supplements],
                "excluded": list(excluded),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seed_parse(task, fname, ts="2026-08-31T05:00:00+00:00", missing=(), lines=100):
    pdir = _wroot(task) / "parse" / fname
    pdir.mkdir(parents=True, exist_ok=True)
    contents = {"md": "行\n" * lines, "outline.json": "{}", "meta.json": json.dumps({"generated_at": ts, "conversion": "docx-native"}, ensure_ascii=False)}
    for ext in ("md", "outline.json", "meta.json"):
        if ext not in missing:
            (pdir / f"{fname}.{ext}").write_text(contents[ext], encoding="utf-8")


def _seed_analysis(task, stem, mtime="2026-08-31T06:00:00+00:00", revised=False):
    """无头部（2026-09-04 起产物不再带模型写的元信息头）；mtime 用 utime 钉死
    （新鲜度锚）；revised=True 写服务端前插形态的首行注释。"""
    adir = _wroot(task) / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    text = "<!-- 工作文件 | 修订=用户 2026-08-31T07:00:00+00:00 -->\n正文\n" if revised else "正文\n"
    p = adir / f"{stem}.md"
    p.write_text(text, encoding="utf-8")
    ts = datetime.fromisoformat(mtime).timestamp()
    os.utime(p, (ts, ts))


def test_no_task_context(tmp_path, monkeypatch):
    init_env(tmp_path, monkeypatch)
    runctx.clear_run()
    assert check_pipeline_state.invoke({}).startswith("[检查失败] 缺少任务上下文")


def test_empty_task(env):
    r = check_pipeline_state.invoke({})
    assert "[sources] 未确认" in r
    assert "[analysis] 无产物" in r
    assert "[untracked]" not in r  # 未确认时不报 untracked


def test_confirmed_and_complete(env):
    task, _ = env
    _seed_sources_file(task, ["招标文件.docx", "补遗1.docx"], "招标文件.docx", [("补遗1.docx", "补遗")])
    _seed_parse(task, "招标文件.docx")
    _seed_parse(task, "补遗1.docx", ts="2026-08-31T05:30:00+00:00")
    _seed_analysis(task, "structure")
    r = check_pipeline_state.invoke({})
    assert "[sources] 已确认：主文件=招标文件.docx；补充=补遗1.docx（补遗）" in r
    assert "[parse] 招标文件.docx：三件齐备，生成=2026-08-31T05:00:00+00:00，档位=docx-native" in r
    assert "[parse] 补遗1.docx：三件齐备" in r
    assert "[analysis] 已有产物：structure\n" in r
    assert "[analysis] 缺：" in r
    assert "[untracked]" not in r
    assert "[freshness] 无过期" in r


def test_missing_parse_product(env):
    task, _ = env
    _seed_sources_file(task, ["招标文件.docx"], "招标文件.docx")
    _seed_parse(task, "招标文件.docx", missing=("outline.json",))
    r = check_pipeline_state.invoke({})
    assert "[parse] 招标文件.docx：缺 outline.json（已有 md、meta.json）" in r


def test_never_parsed(env):
    task, _ = env
    _seed_sources_file(task, ["招标文件.docx", "补遗1.docx"], "招标文件.docx", [("补遗1.docx", "补遗")])
    _seed_parse(task, "招标文件.docx")
    r = check_pipeline_state.invoke({})
    assert "[parse] 补遗1.docx：无解析目录（从未解析）" in r


def test_broken_sources_json(env):
    task, _ = env
    proot = _wroot(task) / "parse"
    proot.mkdir(parents=True, exist_ok=True)
    (proot / "sources.json").write_text("{bad json", encoding="utf-8")
    r = check_pipeline_state.invoke({})
    assert "[sources] 确认单无法解析（JSON 语法错误" in r


def test_freshness_stale_reported_for_untouched(env):
    """来源重新解析晚于产物最后修改（mtime）：未动过的产物被标记；
    动过的（模型重写/用户编辑刷新 mtime）不标记——方向是漏报不误报。"""
    task, _ = env
    _seed_sources_file(task, ["招标文件.docx", "补遗1.docx"], "招标文件.docx", [("补遗1.docx", "补遗")])
    _seed_parse(task, "招标文件.docx", ts="2026-08-31T05:00:00+00:00")
    _seed_parse(task, "补遗1.docx", ts="2026-08-31T07:00:00+00:00")  # 补遗重新解析过
    _seed_analysis(task, "structure", mtime="2026-08-31T06:00:00+00:00")  # 自那之后未动
    _seed_analysis(task, "evaluation", mtime="2026-08-31T08:00:00+00:00")  # 动过（mtime 已刷新）
    r = check_pipeline_state.invoke({})
    assert (
        "补遗1.docx 解析生成=2026-08-31T07:00:00+00:00 晚于 structure.md 最后修改（2026-08-31T06:00:00+00:00）" in r
    )
    assert "可能基于旧版文件" in r
    assert "晚于 evaluation.md" not in r


def test_untracked_and_hidden_files(env):
    task, _ = env
    _seed_sources_file(task, ["招标文件.docx", "招标文件.pdf", "补遗1.docx"], "招标文件.docx", [], excluded=["招标文件.pdf"])
    sroot = artifact_store.sources_dir(task["id"])
    (sroot / "新上传.docx").write_bytes(b"x")
    (sroot / ".DS_Store").write_bytes(b"x")
    r = check_pipeline_state.invoke({})
    assert "[untracked] sources/ 中未纳入来源集合的文件：新上传.docx" in r
    assert ".DS_Store" not in r  # 隐藏文件不进候选
    assert "新上传.docx" in r.split("[candidates]")[1].split("[untracked]")[0]  # 候选清单包含


def test_revised_marker_reported(env):
    task, _ = env
    _seed_analysis(task, "structure", revised=True)
    r = check_pipeline_state.invoke({})
    assert "structure，修订=用户" in r


# ---------- [body] 正文阶段 ----------

_KEY = "tender.directory/tender-response-docs@1"


def _dir_content():
    return {
        "response_documents": [
            {
                "name": "技术部分",
                "scope": "",
                "directory": [
                    {"目录名称": "3.1 项目理解与需求分析", "level": 1, "children": [],
                     "交付形态": "正文编写", "来源位置": ["REQ-01"]},
                    {"目录名称": "3.2 总体设计方案", "level": 1, "children": [],
                     "交付形态": "混合", "来源位置": ["SCORE-02"]},
                    {"目录名称": "3.3 项目团队配置", "level": 1, "children": [],
                     "交付形态": "待核验", "来源位置": []},
                    {"目录名称": "附件：资质证书复印件", "level": 1, "children": [],
                     "交付形态": "模板或附件填充", "来源位置": ["MAND-02"]},
                ],
            }
        ]
    }


def _seed_directory(env, content=None):
    from app import publish

    publish.publish_artifact(_KEY, content or _dir_content(), task_id=env[0]["id"])


def _write_body(env, rel, text="正文\n", mtime=None):
    p = _wroot(env[0]) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mtime:
        ts = datetime.fromisoformat(mtime).timestamp()
        os.utime(p, (ts, ts))
    return p


def test_body_not_started_without_directory(env):
    r = check_pipeline_state.invoke({})
    assert "[body] 无目录产物" in r


def test_body_not_started_with_directory(env):
    _seed_directory(env)
    r = check_pipeline_state.invoke({})
    assert "[body] 未开始（无写作指引、无正文文件）" in r


def test_body_guide_sections_and_missing(env):
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", "指引表\n")
    _write_body(env, "body/关键事实与承诺.md", "清单\n")
    _write_body(env, "body/3.1 项目理解与需求分析.md")
    _write_body(env, "body/3.2 总体设计方案.md")
    r = check_pipeline_state.invoke({})
    assert "[body] 指引已生成；承诺清单已生成；已写 2 节" in r
    assert "[body] 目录节点未写正文：3.3 项目团队配置" in r
    assert "无对应目录节点" not in r  # 附件节点是模板填充（非正文叶子），不报缺也不算多余


def test_body_extra_file_after_outline_change(env):
    _write_body(env, "body/旧版遗留节.md")  # 先有旧文件（基于旧目录写的）
    _seed_directory(env)  # 后发布新目录（content.json mtime 更新）
    _write_body(env, "body/写作指引.md", "指引表\n")  # 指引晚于目录 → 不报过期
    r = check_pipeline_state.invoke({})
    assert "[body] body/ 文件无对应目录节点（标题不一致或目录已改版）：旧版遗留节" in r
    assert "目录产物更新晚于正文" in r and "旧版遗留节.md" in r.split("目录产物更新晚于正文")[1]


def test_body_stale_not_reported_when_written_after_publish(env):
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", "指引表\n")
    _write_body(env, "body/3.1 项目理解与需求分析.md")
    r = check_pipeline_state.invoke({})
    assert "目录产物更新晚于正文" not in r


def test_body_orphan_files_without_directory(env):
    _write_body(env, "body/3.1 项目理解与需求分析.md")
    r = check_pipeline_state.invoke({})
    assert "[body] 无目录产物（正文依据投标目录当前内容" in r
    assert "[body] 但 work/body/ 已有 1 个文件" in r


def test_body_multi_volume_layout(env):
    content = _dir_content()
    content["response_documents"].append({
        "name": "商务部分", "scope": "",
        "directory": [{"目录名称": "6.1 售后服务承诺", "level": 1, "children": [],
                       "交付形态": "正文编写", "来源位置": ["SCORE-09"]}],
    })
    _seed_directory(env, content)
    _write_body(env, "body/写作指引.md", "指引表\n")
    _write_body(env, "body/技术部分/3.1 项目理解与需求分析.md")
    _write_body(env, "body/商务部分/6.1 售后服务承诺.md")
    r = check_pipeline_state.invoke({})
    assert "已写 2 节" in r
    assert "[body] 目录节点未写正文：技术部分/3.2 总体设计方案、技术部分/3.3 项目团队配置" in r
    assert "无对应目录节点" not in r


# ---------- [body] docx 形态（现役）与旧 .md 兼容 ----------


def _make_docx(env, rel: str):
    from docx import Document

    p = _wroot(env[0]) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    Document().save(p)
    return p


def test_body_docx_sections_counted(env):
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", "指引表\n")
    _make_docx(env, "body/3.1 项目理解与需求分析.docx")
    _make_docx(env, "body/3.2 总体设计方案.docx")
    r = check_pipeline_state.invoke({})
    assert "[body] 指引已生成；承诺清单未生成；已写 2 节" in r
    assert "[body] 目录节点未写正文：3.3 项目团队配置" in r


def test_body_volume_file_excluded(env):
    """「整本-」合册产物是派生产物：不算节、不报「无对应目录节点」。"""
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", "指引表\n")
    _make_docx(env, "body/3.1 项目理解与需求分析.docx")
    _make_docx(env, "body/整本-技术部分.docx")
    r = check_pipeline_state.invoke({})
    assert "无对应目录节点" not in r
    assert "已写 1 节" in r


def test_body_template_fill_file_is_legitimate(env):
    """模板填充类叶子产出格式件节文件：合法节文件不误报 extra；未产出也不报缺。"""
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", "指引表\n")
    _make_docx(env, "body/3.1 项目理解与需求分析.docx")
    _make_docx(env, "body/3.2 总体设计方案.docx")
    _make_docx(env, "body/3.3 项目团队配置.docx")
    _make_docx(env, "body/附件：资质证书复印件.docx")
    r = check_pipeline_state.invoke({})
    assert "无对应目录节点" not in r
    assert "目录节点未写正文" not in r
    assert "已写 4 节" in r
    assert "叶子对账一致" in r


def test_body_docx_md_coexist_reports_fact(env):
    """同名 .docx/.md 并存：对账以 docx 为准（去重不双计），并存报事实。"""
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", "指引表\n")
    _write_body(env, "body/3.1 项目理解与需求分析.md", "旧稿\n")
    _make_docx(env, "body/3.1 项目理解与需求分析.docx")
    r = check_pipeline_state.invoke({})
    assert "[body] 同时存在 .docx 与 .md 的节：3.1 项目理解与需求分析" in r
    assert "旧稿残留，以 docx 为准" in r
    assert "已写 1 节" in r
