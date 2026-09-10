"""派发拼装（dispatch_enrich）：tender-body-writer 派发说明的程序化补全。

契约要点：瘦派发→程序拼共享上下文；对不上/多义/已富文本→放行原文；
产出文本零 REQ/MAND/SCORE/TPL 编号（派发契约，编号会被写手镜像进正文）。
"""

import re

import pytest

from app import artifact_store, runctx
from app.dispatch_enrich import build_enriched_description
from tests.util import init_env

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
                ],
            }
        ],
        "registry": {
            "REQ-01": {"type": "需求", "text": "投标人须具备低代码开发能力", "出处": "第三章 3.1，L100-L110"},
            "SCORE-02": {"type": "评分点", "text": "总体架构完整性", "出处": "评标办法"},
        },
    }


def _multi_volume_content():
    return {
        "response_documents": [
            {
                "name": "商务技术册",
                "directory": [
                    {"目录名称": "投标函", "level": 1, "children": [], "交付形态": "混合"},
                ],
            },
            {"name": "报价册", "directory": [{"目录名称": "投标一览表", "level": 1, "children": []}]},
        ],
        "registry": {
            "TPL-02": {"type": "模板", "text": "投标函格式见附件二", "出处": "第三章 附件二"},
        },
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_test", task["id"])
    yield task, conv
    runctx.clear_run()


def _seed(env, content=None, guide=True, promise=True, sibling=False):
    """发布目录产物 + 指引/承诺/兄弟节文件，返回任务 id。"""
    from app import publish

    task = env[0]
    publish.publish_artifact(_KEY, content or _dir_content(), task_id=task["id"])
    wroot = artifact_store.work_dir(task["id"])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    if guide:
        (wroot / "body/写作指引.md").write_text(
            "# 写作指引\n\n"
            "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n|---|---|---|---|---|\n"
            "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | 无 |\n"
            "| 3.2 总体设计方案 | 素材修订 | SCORE-02 | blk_abc123def456 | 无 |\n",
            encoding="utf-8",
        )
    if promise:
        (wroot / "body/关键事实与承诺.md").write_text(
            "# 关键事实与承诺\n\n"
            "| 事项 | 值 | 说明 |\n|---|---|---|\n"
            "| 项目名称 | 测试项目 | 招标文件封面用 |\n"
            "| 免费维护期 | 3 年 | 招标要求 |\n",
            encoding="utf-8",
        )
    if sibling:
        from docx import Document

        d = Document()
        d.add_paragraph("本节阐述门户与工作台的统一登录与待办中心设计。")
        d.save(str(wroot / "body/门户与工作台.docx"))
    return task["id"]


def test_thin_dispatch_enriched_with_all_blocks(env):
    tid = _seed(env, sibling=True)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    # 首行=模型原话（UI 卡标题）
    assert out.startswith("写 3.1 项目理解\n〔系统附")
    assert f"任务目录前缀：{tid}/" in out
    assert f"输出路径：{tid}/work/body/3.1 项目理解与需求分析.docx" in out
    assert re.search(r"今天日期：\d{4}-\d{2}-\d{2}$", out, re.MULTILINE)  # 天级（写手拿不到任务上下文块）
    assert "写作模式：推理撰写" in out
    # 要求清单=registry 解析的原文+出处，编号解析后即弃
    assert "- 投标人须具备低代码开发能力（出处：第三章 3.1，L100-L110）" in out
    assert "承诺清单全部值" in out
    assert "- 项目名称：测试项目（招标文件封面用）" in out
    assert "兄弟节开头摘要" in out and "门户与工作台" in out
    # 派发契约：编号零出现
    for tag in ("REQ-", "SCORE-", "MAND-", "TPL-"):
        assert tag not in out


def test_abbreviation_needle_matches(env):
    """模型缩写（实测形态「重写低代码产品方案」vs 叶子「低代码开发平台产品方案”）：
    近似匹配需命中且唯一。"""
    content = _dir_content()
    content["response_documents"][0]["directory"] = [
        {"目录名称": "低代码开发平台产品方案", "level": 1, "children": [], "交付形态": "正文编写"},
    ]
    tid = _seed(env, content=content)
    out = build_enriched_description("重写低代码产品方案", tid)
    assert out is not None
    assert "输出路径" in out and "低代码开发平台产品方案.docx" in out


def test_no_match_returns_none(env):
    tid = _seed(env)
    assert build_enriched_description("重写一个不存在的节", tid) is None


def test_ambiguous_match_returns_none(env):
    """两个叶子同分（都包含探针）：多义放行，宁可不猜。"""
    content = _dir_content()
    content["response_documents"][0]["directory"][1]["目录名称"] = "3.1 项目理解与需求分析（补充）"
    tid = _seed(env, content=content)
    assert build_enriched_description("写 3.1 项目理解", tid) is None


def test_no_directory_returns_none(env):
    task, _ = env
    assert build_enriched_description("写 3.1 项目理解", task["id"]) is None


def test_guide_missing_degrades(env):
    """指引缺失：模式/要求段省略，路径/承诺仍拼（降级不失败）。"""
    tid = _seed(env, guide=False)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    assert "写作模式" not in out
    assert "交付形态：正文编写" in out
    assert "- 项目名称：测试项目" in out


def test_enrich_mark_idempotent(env):
    tid = _seed(env)
    assert build_enriched_description("〔系统附：本节派发上下文\n写 3.1 项目理解", tid) is None


def test_rich_description_passthrough(env):
    tid = _seed(env)
    rich = "写 3.1 项目理解。" + "细节" * 150
    assert len(rich) > 200
    assert build_enriched_description(rich, tid) is None


def test_material_card_resolved_from_guide(env):
    """素材列 blk id → 逐块名片（标题/字数/来源文件/备注）：写手据此直接使用，
    不再每节重检索素材库（指引期检索的内容层复用）。"""
    import json as _json

    from app import db

    f = db.mt_insert_file("历史标书-某政务项目.docx", file_hash="h_mt1")
    db.mt_replace_blocks(
        f["id"],
        [
            {
                "id": "blk_abc123def456",
                "title": "运维服务方案",
                "note": "通用运维章节，改项目名即可",
                "ranges": _json.dumps([[10, 80]]),
                "chars": 1200,
            }
        ],
    )
    tid = _seed(env)
    out = build_enriched_description("写 3.2 总体设计", tid)
    assert out is not None
    assert "可用素材块（直接据此列使用计划并注入，无需再检索）：" in out
    assert "《运维服务方案》（约 1,200 字）" in out
    assert "来源文件：历史标书-某政务项目.docx" in out
    assert "id：blk_abc123def456" in out
    assert "备注：通用运维章节，改项目名即可" in out
    assert "SCORE-" not in out  # 派发契约：编号零出现


def test_material_section_absent_or_stale(env):
    """素材列无 blk id（—/【缺】）不拼块段；块 id 库里查不到 → 失效提示降级
    （写手自行检索），不是静默丢素材信息。"""
    tid = _seed(env)
    # 3.1 行素材列=—：无块段
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    assert "可用素材块" not in out
    # 3.2 行素材列=blk_abc123def456 但素材库无此块（未 seed）：失效提示
    out = build_enriched_description("写 3.2 总体设计", tid)
    assert out is not None
    assert "可用素材块（直接据此列使用计划并注入，无需再检索）：" in out
    assert "- blk_abc123def456（已失效——请自行检索确认）" in out


def test_gap_column_forwarded_to_writer(env):
    """缺口列【知识库】命中 → 整段透传进派发块（2026-09-10 接线：公司事实
    唯一调度落点=指引缺口列，此前该列零消费、检索命中沉淀不进派发）。"""
    task = env[0]
    from app import publish

    publish.publish_artifact(_KEY, _dir_content(), task_id=task["id"])
    wroot = artifact_store.work_dir(task["id"])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n|---|---|---|---|---|\n"
        "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | "
        "【知识库】ISO9001 证书（注册号 0350324Q30696R1M，有效期至 2027-11-08，"
        "含图 1 张）；【缺：高新技术企业证书】 |\n",
        encoding="utf-8",
    )
    out = build_enriched_description("写 3.1 项目理解", task["id"])
    assert out is not None
    assert "公司材料与缺口" in out
    assert "【知识库】ISO9001 证书（注册号 0350324Q30696R1M，有效期至 2027-11-08，含图 1 张）" in out
    assert "【缺：高新技术企业证书】" in out


def test_gap_column_empty_not_forwarded(env):
    """缺口列「—」/「无」/空 → 不拼段（占位词非内容）。fixture 指引缺口列=「无」，
    3.2 行走素材名片路径、无公司材料段即天然覆盖。"""
    tid = _seed(env)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    assert "公司材料与缺口" not in out


def test_gap_column_bare_ids_stripped(env):
    """缺口列混入 REQ-42 等招标编号 → 剥净（零编号派发契约：编号会被写手
    镜像进正文）；CLAR 类澄清编号不剥（需原样带回待办）。"""
    task = env[0]
    from app import publish

    publish.publish_artifact(_KEY, _dir_content(), task_id=task["id"])
    wroot = artifact_store.work_dir(task["id"])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n|---|---|---|---|---|\n"
        "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | "
        "覆盖（REQ-42、SCORE-07）要求；口径待确认（CLAR-03，落批注） |\n",
        encoding="utf-8",
    )
    out = build_enriched_description("写 3.1 项目理解", task["id"])
    assert out is not None
    assert "公司材料与缺口" in out
    assert "（CLAR-03，落批注）" in out  # 澄清编号保留
    for tag in ("REQ-42", "SCORE-07", "REQ-", "SCORE-"):
        assert tag not in out


def test_multi_volume_path_and_format_note(env):
    """多册：输出路径带册目录；指引行按「册名/标题」拆分匹配；TPL 行带格式件提示。"""
    content = _multi_volume_content()
    task = env[0]
    from app import publish

    publish.publish_artifact(_KEY, content, task_id=task["id"])
    wroot = artifact_store.work_dir(task["id"])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n|---|---|---|---|---|\n"
        "| 商务技术册/投标函 | — | TPL-02 | — | 格式件：拷原件+填空 |\n",
        encoding="utf-8",
    )
    out = build_enriched_description("写投标函", task["id"])
    assert out is not None
    assert f"输出路径：{task['id']}/work/body/商务技术册/投标函.docx" in out
    assert "- 投标函格式见附件二（出处：第三章 附件二）" in out
    assert "本节含格式件" in out
    assert "TPL-" not in out


# ---------- 原件定位行（2026-09-10） ----------

import json as _json


def _seed_outline(env, fname: str, nodes: list) -> None:
    """往 work/parse/<文件名>/ 落一份 outline.json（标题树形态同 parse_document）。"""
    pdir = artifact_store.work_dir(env[0]["id"]) / "parse" / fname
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{fname}.outline.json").write_text(_json.dumps(nodes, ensure_ascii=False), encoding="utf-8")


def test_source_location_unique_marker_match(env):
    """附件标记双现且唯一命中：定位行随派发块下发，区间+条目名可直接喂
    docx_source_inject。"""
    tid = _seed(env)
    _seed_outline(
        env,
        "谈判文件.docx",
        [
            {"标题": "第一章 公告", "level": 1, "start_line": 1, "end_line": 40, "children": []},
            {"标题": "附件14：承诺书", "level": 1, "start_line": 666, "end_line": 689, "children": []},
        ],
    )
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    # 3.1 与 outline 无命中：不带定位行（宁可不带）
    assert "原件定位" not in out


def test_source_location_emitted_for_format_section(env):
    """格式件节（附件标记）唯一命中 → 带「原件定位」行。"""
    content = _dir_content()
    content["response_documents"][0]["directory"] = [
        {"目录名称": "承诺书（附件14）", "level": 1, "children": [], "交付形态": "正文编写"},
    ]
    content["registry"]["REQ-01"] = {
        "type": "需求", "text": "按附件14格式出具承诺书", "出处": "第三章 附件14",
    }
    tid = _seed(env, content=content, guide=False, promise=True)
    (artifact_store.work_dir(tid) / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n|---|---|---|---|---|\n"
        "| 承诺书（附件14） | 格式跟随 | REQ-01 | — | 无 |\n",
        encoding="utf-8",
    )
    _seed_outline(
        env,
        "谈判文件.docx",
        [
            {"标题": "第一章 公告", "level": 1, "start_line": 1, "end_line": 40, "children": []},
            {"标题": "附件13：投标保证金", "level": 1, "start_line": 652, "end_line": 665, "children": []},
            {"标题": "附件14：承诺书", "level": 1, "start_line": 666, "end_line": 689, "children": []},
        ],
    )
    out = build_enriched_description("写承诺书", tid)
    assert out is not None
    assert "原件定位：谈判文件.docx L666-L689（附件14：承诺书）" in out
    for tag in ("REQ-", "SCORE-", "MAND-", "TPL-"):
        assert tag not in out


def test_source_location_ambiguous_across_files(env):
    """同标题命中两个文件：歧义不带（跨文件多义放行）。"""
    content = _dir_content()
    content["response_documents"][0]["directory"] = [
        {"目录名称": "承诺书（附件14）", "level": 1, "children": [], "交付形态": "正文编写"},
    ]
    tid = _seed(env, content=content)
    node = {"标题": "附件14：承诺书", "level": 1, "start_line": 10, "end_line": 20, "children": []}
    _seed_outline(env, "A文件.docx", [node])
    _seed_outline(env, "B文件.docx", [dict(node)])
    out = build_enriched_description("写承诺书", tid)
    assert out is not None
    assert "原件定位" not in out


def test_source_location_adjacent_shell_merged(env):
    """「表1：报价表」标题壳与正文条目相邻（≤2 行）：合并为同一区间——治
    两节点形态（标题壳区间几乎为空、正文在隔壁节点）。"""
    content = _dir_content()
    content["response_documents"][0]["directory"] = [
        {"目录名称": "报价表（首次报价）（表1）", "level": 1, "children": [], "交付形态": "正文编写"},
    ]
    tid = _seed(env, content=content)
    _seed_outline(
        env,
        "谈判文件.docx",
        [
            {"标题": "表1：报价表（首次报价）", "level": 3, "start_line": 447, "end_line": 448, "children": []},
            {"标题": "报价表（首次报价）", "level": 3, "start_line": 449, "end_line": 463, "children": []},
            {"标题": "表2：报价表（最终报价）", "level": 3, "start_line": 464, "end_line": 465, "children": []},
        ],
    )
    out = build_enriched_description("写报价表（首次报价）（表1）", tid)
    assert out is not None
    # 447-448 壳 + 449-463 正文合并（464 的表2 不含：标记不同不命中、也不相邻合并）
    assert "原件定位：谈判文件.docx L447-L463" in out
