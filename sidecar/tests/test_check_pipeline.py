"""check_pipeline_state 工具：任务流水线事实状态报告（纯事实、零结论）。"""

import json
import os
from datetime import datetime

import pytest

from app import artifact_store, runctx
from app.tools.check_pipeline import _balanced_waves, check_pipeline_state
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


# ---------- [body] 均衡分波参考 ----------

_GUIDE_HEADER = ["| 节 | 模式 | 依据 | 素材 | 缺口/备注 |", "|---|---|---|---|---|"]


def _write_guide(env, rows: list[str]):
    _write_body(env, "body/写作指引.md", "\n".join(_GUIDE_HEADER + rows) + "\n")


def test_balanced_waves_lpt_balance():
    """LPT 贪心：降序逐项补最轻波——2 波时权重 9..1 分成 23/22（蛇形奇偶交替是 25/20）。"""
    items = [(f"n{w}", w) for w in range(9, 0, -1)]
    waves = _balanced_waves(items)
    assert len(waves) == 2
    sums = [sum(w for _, w in wave) for wave in waves]
    assert sum(sums) == 45
    assert max(sums) - min(sums) <= 1


def test_balanced_waves_capacity_respected():
    """容量上限优先于负载均衡：10 + 九个 1 → 轻波满 8 项封顶，溢出项进重波。"""
    items = [("heavy", 10)] + [(f"l{i}", 1) for i in range(9)]
    waves = _balanced_waves(items)
    assert sum(len(w) for w in waves) == 10
    assert all(len(w) <= 8 for w in waves)


def test_balanced_waves_small_set_single_wave():
    assert [len(w) for w in _balanced_waves([(f"n{i}", 1) for i in range(8)])] == [8]
    assert _balanced_waves([]) == []


def test_body_wave_reference(env):
    """分波参考：格式件参与、物理附件排除、指引缺行兜底、已写节剔除、权重=基数+块数。"""
    content = _dir_content()
    content["response_documents"][0]["directory"].insert(0, {
        "目录名称": "投标函", "level": 1, "children": [],
        "交付形态": "模板或附件填充", "来源位置": ["MAND-03"],
    })
    content["response_documents"][0]["directory"].append({
        "目录名称": "3.4 实施与服务方案", "level": 1, "children": [],
        "交付形态": "正文编写", "来源位置": ["REQ-02"],
    })
    _seed_directory(env, content)
    _write_guide(env, [
        "| 投标函 | — | MAND-03 | — | 格式件：docx_source_inject 拷原件+revise 填空 |",
        "| 3.1 项目理解与需求分析 | 素材修订 | REQ-01 | blk_1a2b3c4d5e6f | — |",
        "| 3.2 总体设计方案 | 素材修订+推理撰写 | SCORE-02 | blk_0f1e2d3c4b5a | — |",
        "| 3.4 实施与服务方案 | 格式跟随 | REQ-02 | — | — |",
        "| 附件：资质证书复印件 | — | MAND-02 | — | 物理附件，列待填清单 |",
    ])  # 3.3 指引缺行 → 兜底补入
    r = check_pipeline_state.invoke({})
    assert "[body] 均衡分波参考" in r
    wave_text = r.split("均衡分波参考", 1)[1]
    # 投标函1 + 3.1(2+1块) + 3.2(max(2,3)+1块) + 3.3兜底1 + 3.4格式跟随1
    assert "第1波（权重和 10）" in wave_text
    assert "投标函" in wave_text
    assert "3.3 项目团队配置" in wave_text and "兜底" in wave_text
    assert "资质证书复印件" not in wave_text  # 物理附件不参与
    _make_docx(env, "body/3.1 项目理解与需求分析.docx")
    r = check_pipeline_state.invoke({})
    assert "均衡分波参考" in r  # 仍有 4 节待写 → 参考仍在
    wave_text = r.split("均衡分波参考", 1)[1]
    assert "3.1 项目理解与需求分析" not in wave_text  # 已写节剔除
    assert "第1波（权重和 7）" in wave_text  # 10 - 3.1 的权重 3


def test_body_wave_reference_multi_volume_keys(env):
    """多册分波键=「册名/标题」，与对账行同口径。"""
    content = _dir_content()
    content["response_documents"].append({
        "name": "商务部分", "scope": "",
        "directory": [{"目录名称": "6.1 售后服务承诺", "level": 1, "children": [],
                       "交付形态": "正文编写", "来源位置": ["SCORE-09"]}],
    })
    _seed_directory(env, content)
    _write_guide(env, [
        "| 技术部分/3.1 项目理解与需求分析 | 素材修订 | REQ-01 | — | — |",
        "| 技术部分/3.2 总体设计方案 | 推理撰写 | SCORE-02 | — | — |",
        "| 技术部分/3.3 项目团队配置 | 推理撰写 | SCORE-05 | — | — |",
        "| 商务部分/6.1 售后服务承诺 | 素材修订 | SCORE-09 | — | — |",
    ])
    r = check_pipeline_state.invoke({})
    wave_text = r.split("均衡分波参考", 1)[1]
    assert "商务部分/6.1 售后服务承诺" in wave_text
    assert "技术部分/3.3 项目团队配置" in wave_text
    assert "兜底" not in wave_text  # 指引行齐 → 无兜底


def test_body_wave_reference_skipped_when_few_pending(env):
    """待写节 <4 不值得分波：不出参考行（既有占位指引用例也不受影响）。"""
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", "指引表\n")
    r = check_pipeline_state.invoke({})
    assert "均衡分波参考" not in r
