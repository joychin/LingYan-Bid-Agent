"""派发拼装（dispatch_enrich）：tender-body-writer 派发说明的程序化补全。

契约要点：瘦派发→程序拼共享上下文；对不上/多义/已富文本→放行原文；
产出文本零 REQ/MAND/SCORE/TPL 编号（派发契约，编号会被写手镜像进正文）。
"""

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
