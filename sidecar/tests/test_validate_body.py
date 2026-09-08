"""validate_body 工具：写作指引表校验（叶子有行/模式合法/块 id 可解析）+
正文节自查（占位清点/旧名残留/素材使用率）。"""

import hashlib

import pytest

from app import artifact_store, db, publish, runctx
from app.knowledge import materials_lib as mlib
from app.knowledge.materials_lib import run_parse
from app.tools.validate_body import validate_body
from tests.util import init_env

KEY = "tender.directory/tender-response-docs@1"


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_test", task["id"])
    mlib.ensure_dirs()
    yield task, conv
    runctx.clear_run()


def _wroot(task):
    return artifact_store.work_dir(task["id"])


def _dir_content():
    """单册目录：3 个需正文叶子（正文编写/混合/待核验）+ 1 个模板填充叶子。"""
    return {
        "response_documents": [
            {
                "name": "技术部分",
                "scope": "",
                "directory": [
                    {
                        "目录名称": "第三章 技术方案",
                        "level": 1,
                        "children": [
                            {"目录名称": "3.1 项目理解与需求分析", "level": 2, "children": [],
                             "交付形态": "正文编写", "来源位置": ["REQ-01"]},
                            {"目录名称": "3.2 总体设计方案", "level": 2, "children": [],
                             "交付形态": "混合", "来源位置": ["SCORE-02"]},
                            {"目录名称": "3.3 项目团队配置", "level": 2, "children": [],
                             "交付形态": "待核验", "来源位置": []},
                        ],
                    },
                    {"目录名称": "附件：资质证书复印件", "level": 1, "children": [],
                     "交付形态": "模板或附件填充", "来源位置": ["MAND-02"]},
                ],
            }
        ]
    }


def _seed_directory(env, content=None):
    publish.publish_artifact(
        KEY, content or _dir_content(),
        task_id=env[0]["id"], conversation_id=env[1]["id"],
    )


def _seed_block(file_name: str, md: str, title: str, lines: tuple[int, int]) -> str:
    """素材文件+块（复用 test_knowledge_tools 的种子方式）。返回块 id。"""
    src = mlib.mt_files_dir() / file_name
    src.write_text(md, encoding="utf-8")
    f = db.mt_insert_file(file_name=file_name, file_hash=hashlib.sha256(md.encode()).hexdigest())
    run_parse(f["id"])
    block = mlib.create_block(f["id"], title, "", [list(lines)])
    assert block, "素材块创建失败"
    return block["id"]


def _write_body(env, rel: str, text: str):
    p = _wroot(env[0]) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _guide(bid: str) -> str:
    # 块只出现在 3.1 行——同块多派在新校验下是 issue（一块只派一节）
    return (
        "# 写作指引\n\n"
        "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n"
        "|---|---|---|---|---|\n"
        f"| 3.1 项目理解与需求分析 | 素材修订 | REQ-01 | {bid} | — |\n"
        "| 3.2 总体设计方案 | 素材修订+推理撰写 | SCORE-02 | 【缺】 | 缺：总体方案素材 |\n"
        "| 3.3 项目团队配置 | 推理撰写 | — | 【缺】 | 缺：人员证书扫描件 |\n"
        "| 附件：资质证书复印件 | — | MAND-02 | — | 模板填充，列待填清单 |\n"
    )


# ---------- 指引校验 ----------


def test_guide_all_compliant(env):
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n服务方案正文若干行。\n", "服务方案", (3, 3))
    _write_body(env, "body/写作指引.md", _guide(bid))
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]")
    assert "⚠️" not in r


def test_guide_missing_row(env):
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n正文。\n", "块", (3, 3))
    text = _guide(bid).replace(
        "| 3.3 项目团队配置 | 推理撰写 | — | 【缺】 | 缺：人员证书扫描件 |\n", ""
    )
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert "[校验未通过]" in r
    assert "指引缺行：「3.3 项目团队配置」（交付形态=待核验）" in r


def test_guide_invalid_mode_and_unknown_row(env):
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n正文。\n", "块", (3, 3))
    text = _guide(bid).replace("素材修订+推理撰写", "自由发挥").replace(
        "| 3.1 项目理解与需求分析", "| 9.9 不存在的节"
    )
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert "模式「自由发挥」不合法" in r
    assert "「9.9 不存在的节」不在目录叶子中" in r


def test_guide_stale_block_id(env):
    _seed_directory(env)
    _write_body(env, "body/写作指引.md", _guide("blk_" + "0" * 12))
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert "素材块 blk_000000000000 失效" in r


def test_guide_multi_volume_key(env):
    content = _dir_content()
    content["response_documents"].append({
        "name": "商务部分", "scope": "",
        "directory": [{"目录名称": "6.1 售后服务承诺", "level": 1, "children": [],
                       "交付形态": "正文编写", "来源位置": ["SCORE-09"]}],
    })
    _seed_directory(env, content)
    # 多册但指引用裸标题 → 叶子键是「册名/标题」，裸标题对不上
    _write_body(env, "body/写作指引.md", _guide("blk_" + "0" * 12).replace("blk_" + "0" * 12, "【缺】"))
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert "指引缺行：「商务部分/6.1 售后服务承诺」" in r
    for t in ("3.1 项目理解与需求分析", "3.2 总体设计方案", "3.3 项目团队配置"):
        assert f"「{t}」不在目录叶子中" in r


def test_guide_without_directory_warns(env):
    """无目录产物：叶子对账降级为 warning，模式/块校验仍执行。"""
    _write_body(env, "body/写作指引.md", _guide("blk_" + "0" * 12))
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert "无目录产物或内容不可读" in r
    assert "素材块 blk_000000000000 失效" in r


def test_guide_same_block_two_rows_is_issue(env):
    """同块多派=issue（2026-09-08 实测事故：同一 625 段素材块全文进了
    「总体建设方案」与「系统集成方案」两节）——注入两节即正文逐字重复。"""
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n正文。\n", "服务方案", (3, 3))
    text = _guide(bid).replace("SCORE-02 | 【缺】", f"SCORE-02 | {bid}")
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert "[校验未通过]" in r
    assert "素材块" in r and "《服务方案》" in r
    assert "同时派给 2 个节（3.1 项目理解与需求分析、3.2 总体设计方案）" in r
    assert "拆成小范围块" in r  # 修复出路随行给出


def test_guide_overlapping_blocks_on_same_file_warns(env):
    """马甲块：不同块 id、同素材文件、区间有交集、派不同节 → 弱级提示
    （历史重复建块不会被失效检查发现，点名核对；提示不是门禁）。"""
    _seed_directory(env)
    md = "\n".join(f"素材第{i}行内容，平台功能描述。" for i in range(1, 9)) + "\n"
    src = mlib.mt_files_dir() / "云枢平台.txt"
    src.write_text(md, encoding="utf-8")
    f = db.mt_insert_file(file_name="云枢平台.txt",
                          file_hash=hashlib.sha256(md.encode()).hexdigest())
    run_parse(f["id"])
    b1 = mlib.create_block(f["id"], "云枢低代码平台技术方案", "", [[2, 5]])
    b2 = mlib.create_block(f["id"], "BPM技术平台介绍", "", [[4, 7]])
    assert b1 and b2
    text = _guide(b1["id"]).replace("SCORE-02 | 【缺】", f"SCORE-02 | {b2['id']}")
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]")  # 弱级提示不是门禁
    assert "勾选区间重叠" in r
    assert "《云枢低代码平台技术方案》" in r and "《BPM技术平台介绍》" in r
    assert "云枢平台.txt" in r
    assert "同时派给" not in r  # 不同块 id 各派一节，不触发同块 issue


# ---------- 正文节校验 ----------


def test_section_pass_with_material_used(env):
    _seed_directory(env)
    md = "# 服务方案\n\n本项目建设周期为 90 天，运维服务体系覆盖全网设备并承诺 2 小时响应。\n"
    bid = _seed_block("园区方案.txt", md, "服务方案", (3, 3))
    section = (
        "## 3.2 总体设计方案\n\n"
        "本项目建设周期为 90 天，运维服务体系覆盖全网设备并承诺 2 小时响应。\n\n"
        "在上述基础上，本项目进一步采用双活架构保障核心业务连续性。\n"
    )
    _write_body(env, "body/3.2 总体设计方案.md", section)
    r = validate_body.invoke({"section": "body/3.2 总体设计方案.md", "block_ids": [bid]})
    assert r.startswith("[校验通过]")
    assert "[占位/待澄清] 无" in r


def test_section_placeholder_census_not_issue(env):
    _seed_directory(env)
    _write_body(env, "body/3.3 项目团队配置.md",
                "团队拟投入 5 人。\n\n【待补：项目经理一级建造师证书】\n\n【待澄清：驻场人数是否含后台】\n")
    r = validate_body.invoke({"section": "body/3.3 项目团队配置.md", "block_ids": []})
    assert r.startswith("[校验通过]")  # 占位是清单不是错误（缺料不阻塞）
    assert "[占位/待澄清] 共 2 处" in r
    assert "L3：【待补：项目经理一级建造师证书】" in r


def test_section_low_overlap_warns(env):
    _seed_directory(env)
    md = "# 服务方案\n\n本项目建设周期为 90 天，运维服务体系覆盖全网设备并承诺 2 小时响应。\n"
    bid = _seed_block("园区方案.txt", md, "服务方案", (3, 3))
    _write_body(env, "body/3.2 总体设计方案.md",
                "## 3.2 总体设计方案\n\n本公司充分理解本项目需求，将组建专业团队全力保障。\n")
    r = validate_body.invoke({"section": "body/3.2 总体设计方案.md", "block_ids": [bid]})
    assert r.startswith("[校验通过]")  # 提示不是门禁
    assert "未实质使用素材" in r


def test_section_residue_warns_as_weak_signal(env):
    """残留来自素材文件名主干=弱级来源（通用产品词可能误报）→ 提示核对，
    不再是必须清零的 issue（2026-09-06「流程管理」误报修复）。"""
    _seed_directory(env)
    md = "# 服务方案\n\n运维服务体系正文内容若干。\n"
    bid = _seed_block("历史标书.txt", md, "服务方案", (3, 3))
    _write_body(env, "body/3.2 总体设计方案.md",
                "## 3.2 总体设计方案\n\n运维服务体系正文内容若干。\n\n本项目沿用历史标书的管理经验。\n")
    r = validate_body.invoke({"section": "body/3.2 总体设计方案.md", "block_ids": [bid]})
    assert r.startswith("[校验通过]")  # 弱级提示不是门禁
    assert "疑似残留" in r and "残留「历史标书」" in r


def test_guide_dash_mode_for_prose_leaf_warns(env):
    """表格类节点被目录错标为需正文时，指引写「—」降为提示（两条出路），
    不再把模型逼进修改循环（2026-09-06 评标索引表实测修复）。"""
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n正文。\n", "块", (3, 3))
    text = _guide(bid).replace("素材修订+推理撰写", "—").replace("素材修订", "—", 1)
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]")  # 提示不是门禁
    assert "表格/索引/填表类节点" in r
    assert "3.1 项目理解与需求分析」被目录标为需正文但模式写了「—」" in r


def test_section_without_block_ids_skips(env):
    _seed_directory(env)
    _write_body(env, "body/3.1 项目理解与需求分析.md", "正文内容。\n")
    r = validate_body.invoke({"section": "body/3.1 项目理解与需求分析.md"})
    assert "未传 block_ids" in r


def test_section_empty_file_is_issue(env):
    _seed_directory(env)
    _write_body(env, "body/3.1 项目理解与需求分析.md", "\n \n")
    r = validate_body.invoke({"section": "body/3.1 项目理解与需求分析.md", "block_ids": []})
    assert "正文为空" in r


# ---------- 入口与路径 ----------


def test_no_task_context(tmp_path, monkeypatch):
    init_env(tmp_path, monkeypatch)
    runctx.clear_run()
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验失败] 缺少任务上下文")


def test_path_escape_rejected(env):
    for bad in ("../analysis/structure.md", "/etc/hosts", "body/../../x.md"):
        r = validate_body.invoke({"section": bad})
        assert r.startswith("[校验失败]"), bad


def test_missing_file_and_non_md(env):
    _write_body(env, "body/notes.txt", "x")
    r = validate_body.invoke({"section": "body/nope.md"})
    assert r.startswith("[校验失败]") and "不存在" in r
    r = validate_body.invoke({"section": "body/notes.txt"})
    assert "只支持 .md" in r


# ---------- 全局承诺比对（section="body"） ----------


def test_global_promise_all_placed(env):
    _write_body(env, "body/关键事实与承诺.md",
                "| 事项 | 值 | 说明 |\n|---|---|---|\n| 工期 | 90 天 | 用户拍板 |\n| 响应时限 | 2小时 | 服务承诺 |\n")
    _write_body(env, "body/3.1 项目理解.md", "建设工期 90天。\n")  # 空格差异靠归一化命中
    _write_body(env, "body/3.2 总体设计方案.md", "故障响应时限 2 小时。\n")
    r = validate_body.invoke({"section": "body"})
    assert r.startswith("[校验通过] body 全局")
    assert "2 节正文，承诺 2 项比对，2 项已落正文" in r
    assert "⚠️" not in r


def test_global_promise_missing_reported(env):
    _write_body(env, "body/关键事实与承诺.md",
                "| 事项 | 值 | 说明 |\n|---|---|---|\n| 工期 | 90 天 | 拍板 |\n| 质保期 | 3 年 | 拍板 |\n")
    _write_body(env, "body/3.1 项目理解.md", "工期 90 天。\n")
    r = validate_body.invoke({"section": "body"})
    assert "1 项未落正文" in r
    assert "「质保期=3 年」未在任何正文出现" in r


def test_global_promise_no_list_skips(env):
    _write_body(env, "body/3.1 项目理解.md", "正文\n")
    r = validate_body.invoke({"section": "body"})
    assert "无关键事实与承诺清单" in r


def test_global_promise_bad_table_skips(env):
    _write_body(env, "body/关键事实与承诺.md", "随便写的不是表\n")
    _write_body(env, "body/3.1 项目理解.md", "正文\n")
    r = validate_body.invoke({"section": "body"})
    assert "不是「事项｜值｜说明」表" in r


def test_global_body_dir_missing(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_test", task["id"])
    r = validate_body.invoke({"section": "body"})
    runctx.clear_run()
    assert r.startswith("[校验失败]") and "body" in r


# ---------- docx 正文节（终稿视角校验） ----------


def _make_docx_section(env, rel: str, title: str, paragraphs: str = "") -> None:
    from app.tools.docx_ops import docx_section_create

    r = docx_section_create.invoke({"path": rel, "title": title, "paragraphs": paragraphs})
    assert r.startswith("[已创建]"), r


def test_section_docx_placeholder_p_numbering(env):
    _make_docx_section(env, "body/3.3 项目团队配置.docx", "3.3 项目团队配置",
                       "团队拟投入 5 人。\n【待补：项目经理证书】")
    r = validate_body.invoke({"section": "body/3.3 项目团队配置.docx", "block_ids": []})
    assert r.startswith("[校验通过]")  # 占位是清单不是错误
    assert "[占位/待澄清] 共 1 处" in r
    assert "P3：【待补：项目经理证书】" in r  # P1=标题、P2=团队段、P3=占位段


def test_section_docx_table_placeholder_t_label(env):
    """表格单元格里的占位按 T{t}R{r} 定位（与读视图格坐标互查，不再是越界 P 号）。"""
    from docx import Document as _Doc

    _make_docx_section(env, "body/3.2 总体设计方案.docx", "3.2 总体设计方案", "方案正文。")
    p = _wroot(env[0]) / "body" / "3.2 总体设计方案.docx"
    doc = _Doc(str(p))
    t = doc.add_table(rows=1, cols=2)
    t.style = "Table Grid"
    t.cell(0, 0).text = "分项报价"
    t.cell(0, 1).text = "【待补：分项报价表金额】"
    doc.save(p)
    r = validate_body.invoke({"section": "body/3.2 总体设计方案.docx", "block_ids": []})
    assert r.startswith("[校验通过]")
    assert "[占位/待澄清] 共 1 处" in r
    assert "T1R1：分项报价 | 【待补：分项报价表金额】" in r


def test_section_docx_residue_uses_pt_labels(env):
    """docx 节的残留命中也按 P 段号/T 行号定位（与占位清点同一路标签——
    段落+表格行拼接序列里的 L 行号模型对不上读视图）。"""
    from docx import Document as _Doc

    _seed_directory(env)
    md = "# 服务方案\n\n运维服务体系正文内容若干。\n"
    bid = _seed_block("历史标书.txt", md, "服务方案", (3, 3))
    _make_docx_section(env, "body/3.2 总体设计方案.docx", "3.2 总体设计方案",
                       "运维服务体系正文内容若干。")
    p = _wroot(env[0]) / "body" / "3.2 总体设计方案.docx"
    doc = _Doc(str(p))
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    t.cell(0, 0).text = "本项目沿用历史标书的管理经验。"
    doc.save(p)
    r = validate_body.invoke({"section": "body/3.2 总体设计方案.docx", "block_ids": [bid]})
    assert r.startswith("[校验通过]")  # 弱级提示不是门禁
    assert "疑似残留" in r and "残留「历史标书」" in r
    assert "T1R1：本项目沿用历史标书" in r  # 命中在表格行，按 T 标签定位


def test_section_docx_accepted_view_census(env):
    """终稿视角：插入修订的占位计入、删除修订的占位不计（评委看到的是终稿）。"""
    import json

    from app.tools.docx_ops import docx_section_revise

    _make_docx_section(env, "body/3.1 项目理解与需求分析.docx", "3.1",
                       "第一段。\n【待补：要删的占位】")
    edits = json.dumps([
        {"para": 3, "action": "delete"},  # P3=【待补】段（P1=标题、P2=第一段）
        {"para": 2, "action": "insert_after", "text": "【待澄清：插入的占位】"},
    ])
    assert docx_section_revise.invoke(
        {"path": "body/3.1 项目理解与需求分析.docx", "edits": edits}
    ).startswith("[已修订]")
    r = validate_body.invoke({"section": "body/3.1 项目理解与需求分析.docx", "block_ids": []})
    assert "[占位/待澄清] 共 1 处" in r
    assert "P3：【待澄清：插入的占位】" in r
    assert "要删的占位" not in r


def test_section_docx_material_overlap_no_warning(env):
    """素材贴底稿的节（docx 注入同源文本）：重叠率远超提示线，不误报。"""
    _seed_directory(env)
    md = "# 服务方案\n\n本项目建设周期为 90 天，运维服务体系覆盖全网设备并承诺 2 小时响应。\n"
    bid = _seed_block("园区方案.txt", md, "服务方案", (3, 3))
    _make_docx_section(env, "body/3.2 总体设计方案.docx", "3.2 总体设计方案",
                       "本项目建设周期为 90 天，运维服务体系覆盖全网设备并承诺 2 小时响应。")
    r = validate_body.invoke({"section": "body/3.2 总体设计方案.docx", "block_ids": [bid]})
    assert r.startswith("[校验通过]")
    assert "未实质使用素材" not in r


def test_section_docx_table_block_overlap_no_warning(env):
    """表格为主的素材块：块 md 表格行（| a | b |）与节 docx 表格行（a | b 视图
    拼格）在归一化剥格式符号后 shingle 命中——不再误报「未实质使用」
    （2026-09-08 实证修复：格式差稀释重叠率）。"""
    from docx import Document as _Doc

    _seed_directory(env)
    md = (
        "# 服务方案\n\n"
        "| 人员角色 | 配置要求 | 资质要求 |\n"
        "|---|---|---|\n"
        "| 项目经理 | 1 人 | PMP认证且具有十年大型园区运维项目管理经验 |\n"
        "| 网络工程师 | 2 人 | 思科CCIE认证且具有五年核心网络运维实战经验 |\n"
        "| 系统工程师 | 2 人 | 红帽RHCE认证且具有五年数据中心系统运维经验 |\n"
    )
    bid = _seed_block("历史人员配置.txt", md, "人员配置", (3, 7))
    _make_docx_section(env, "body/3.3 项目团队配置.docx", "3.3 项目团队配置",
                       "项目团队按以下配置组建。")
    p = _wroot(env[0]) / "body" / "3.3 项目团队配置.docx"
    doc = _Doc(str(p))
    t = doc.add_table(rows=3, cols=3)
    t.style = "Table Grid"
    rows = [
        ("项目经理", "1 人", "PMP认证且具有十年大型园区运维项目管理经验"),
        ("网络工程师", "2 人", "思科CCIE认证且具有五年核心网络运维实战经验"),
        ("系统工程师", "2 人", "红帽RHCE认证且具有五年数据中心系统运维经验"),
    ]
    for ri, cells in enumerate(rows):
        for ci, val in enumerate(cells):
            t.cell(ri, ci).text = val
    doc.save(p)
    r = validate_body.invoke({"section": "body/3.3 项目团队配置.docx", "block_ids": [bid]})
    assert r.startswith("[校验通过]")
    assert "未实质使用素材" not in r


def test_global_promise_docx_sections_and_volume_excluded(env):
    """全局比对收 docx 节；「整本-」合册产物是派生物不参与（改内容回节文件层）。"""
    _write_body(env, "body/关键事实与承诺.md",
                "| 事项 | 值 | 说明 |\n|---|---|---|\n| 工期 | 90 天 | 拍板 |\n| 质保期 | 3 年 | 拍板 |\n")
    _make_docx_section(env, "body/3.1 项目理解.docx", "3.1 项目理解", "建设工期 90天。")
    _make_docx_section(env, "body/整本-技术部分.docx", "整本", "质保期 3 年。")
    r = validate_body.invoke({"section": "body"})
    assert "1 节正文，承诺 2 项比对，1 项已落正文" in r
    assert "「质保期=3 年」未在任何正文出现" in r


def test_global_dup_sections_reported_without_promise_list(env):
    """节间查重独立于承诺清单：无清单也照跑（2026-09-08 事故形态——同一素材
    块全文进了两个节；修「没承诺清单就不查重」的漏洞）。"""
    shared = (
        "本平台采用云原生多租户架构，表单引擎支持百级组件拖拽配置，"
        "流程引擎覆盖串并行审批与会签回退，仪表盘支持多维数据建模与实时刷新。"
    ) * 3
    _write_body(env, "body/商务技术册/总体建设方案.md", f"总体概述一段。\n\n{shared}\n")
    _write_body(env, "body/商务技术册/系统集成方案.md", f"集成架构一段。\n\n{shared}\n")
    r = validate_body.invoke({"section": "body"})
    assert "无关键事实与承诺清单" in r  # 清单缺失照常说明
    assert "节间查重 1 对疑似重复" in r
    assert "「商务技术册/总体建设方案」与「商务技术册/系统集成方案」内容重叠约" in r
    assert "拆块或改写" in r


def test_global_dup_short_sections_not_flagged(env):
    """短节（<5 shingle，承诺行级别）不进两两比对——共享承诺值不误报。"""
    _write_body(env, "body/关键事实与承诺.md",
                "| 事项 | 值 | 说明 |\n|---|---|---|\n| 工期 | 90 天 | 拍板 |\n")
    _write_body(env, "body/3.1 项目理解.md", "工期承诺 90 天。\n")
    _write_body(env, "body/3.2 总体设计.md", "工期口径 90 天。\n")
    r = validate_body.invoke({"section": "body"})
    assert "节间疑似重复" not in r
    assert "⚠️" not in r
