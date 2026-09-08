"""前端结构化表格界面（写作指引/承诺清单）的序列化格式契约——金样例守护。

frontend/src/lib/workbenchTable.ts 的 serializeTableFile 只输出本文件硬编码的
标准表格式（与 frontend/src/lib/workbenchTable.test.ts 的金样例逐字节同源）；
sidecar 三个消费方（validate_body / check_pipeline / dispatch_enrich）必须原样
吃下。任一侧改格式（前端序列化漂移 / Python 解析收紧）此测试红——「前端序列化
格式 ⊆ Python 解析能力」的跨语言锁。
"""

import hashlib

import pytest

from app import artifact_store, db, publish, runctx
from app.dispatch_enrich import _promise_lines
from app.knowledge import materials_lib as mlib
from app.knowledge.materials_lib import run_parse
from app.tools.validate_body import _parse_guide_rows, validate_body
from tests.util import init_env

KEY = "tender.directory/tender-response-docs@1"

# 与 frontend/src/lib/workbenchTable.test.ts 的 GUIDE_GOLDEN 逐字节同源
GUIDE_GOLDEN = "\n".join([
    "# 写作指引",
    "",
    "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |",
    "|---|---|---|---|---|",
    "| 3.1 项目理解与需求分析 | 素材修订 | REQ-01、REQ-07 | blk_0123456789ab | — |",
    "| 3.2 总体设计方案 | 素材修订+推理撰写 | SCORE-02 | 【缺】 | 缺：总体方案素材 |",
    "| 3.3 项目团队配置 | 推理撰写 | — | 【缺】 | 缺：人员证书扫描件 |",
    "| 投标函 | — | MAND-03 | — | 格式件：拷原件+revise 填空 |",
    "",
])

# 与 frontend/src/lib/workbenchTable.test.ts 的 PROMISE_GOLDEN 逐字节同源
PROMISE_GOLDEN = "\n".join([
    "# 关键事实与承诺",
    "",
    "| 事项 | 值 | 说明 |",
    "|---|---|---|",
    "| 项目名称 | 测试项目 | 招标文件封面用 |",
    "| 免费维护期 | 3 年 | 招标要求 |",
    "",
])


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_test", task["id"])
    mlib.ensure_dirs()
    yield task, conv
    runctx.clear_run()


def test_guide_golden_parse_guide_rows():
    """金样例指引表：_parse_guide_rows（validate_body/check_pipeline 共用）行/列全解析。"""
    rows = _parse_guide_rows(GUIDE_GOLDEN.splitlines())
    assert len(rows) == 4
    _lineno, cells, cols = rows[0]
    assert cols["节"] == 0 and cols["模式"] == 1 and cols["素材"] == 3
    assert cells[cols["节"]] == "3.1 项目理解与需求分析"
    assert cells[cols["模式"]] == "素材修订"
    assert cells[cols["素材"]] == "blk_0123456789ab"
    assert rows[1][1][cols["模式"]] == "素材修订+推理撰写"
    assert rows[3][1][cols["模式"]] == "—"
    # 服务端「修订=用户」首行注释（用户在界面保存后自动盖）不影响表解析
    stamped = "<!-- 工作文件 | 修订=用户 2026-09-08T12:00:00Z -->\n" + GUIDE_GOLDEN
    assert len(_parse_guide_rows(stamped.splitlines())) == 4


def test_promise_golden_promise_lines(env):
    """金样例承诺表：dispatch_enrich._promise_lines 按位置取 cells[0]/[1] 正确。"""
    task = env[0]
    wroot = artifact_store.work_dir(task["id"])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    (wroot / "body/关键事实与承诺.md").write_text(PROMISE_GOLDEN, encoding="utf-8")
    assert _promise_lines(task["id"]) == [
        "- 项目名称：测试项目（招标文件封面用）",
        "- 免费维护期：3 年（招标要求）",
    ]


def _dir_content():
    """单册目录：叶子与金样例指引四行逐字对齐（3 需正文 + 1 模板填充）。"""
    return {
        "response_documents": [
            {
                "name": "技术部分",
                "scope": "",
                "directory": [
                    {"目录名称": "3.1 项目理解与需求分析", "level": 1, "children": [],
                     "交付形态": "正文编写", "来源位置": ["REQ-01", "REQ-07"]},
                    {"目录名称": "3.2 总体设计方案", "level": 1, "children": [],
                     "交付形态": "混合", "来源位置": ["SCORE-02"]},
                    {"目录名称": "3.3 项目团队配置", "level": 1, "children": [],
                     "交付形态": "待核验", "来源位置": []},
                    {"目录名称": "投标函", "level": 1, "children": [],
                     "交付形态": "模板或附件填充", "来源位置": ["MAND-03"]},
                ],
            }
        ]
    }


def test_guide_golden_validates_clean(env):
    """金样例（块 id 换真块）完整过 validate_body 指引校验——用户在界面编辑保存的
    格式就是 AI 自查会放行的格式。"""
    task = env[0]
    publish.publish_artifact(KEY, _dir_content(), task_id=task["id"], conversation_id=env[1]["id"])
    # 种真素材块（块 id 系统生成，金样例里的占位 id 原位替换）
    md = "# 方案\n\n服务方案正文若干行。\n"
    src = mlib.mt_files_dir() / "园区方案.txt"
    src.write_text(md, encoding="utf-8")
    f = db.mt_insert_file(file_name="园区方案.txt", file_hash=hashlib.sha256(md.encode()).hexdigest())
    run_parse(f["id"])
    bid = mlib.create_block(f["id"], "服务方案", "", [[3, 3]])["id"]

    wroot = artifact_store.work_dir(task["id"])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    (wroot / "body/写作指引.md").write_text(
        GUIDE_GOLDEN.replace("blk_0123456789ab", bid), encoding="utf-8"
    )

    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]"), r
    assert "⚠️" not in r
