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
    # 块只出现在 3.1 行（同块多派 2026-09-15 契约修正起为弱提示，不再是 issue）
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
    """同块多派=弱级提示（2026-09-15 契约修正：块=拷贝授权范围非注入原子，
    同一块的不同区间派不同节合法——2026-09-08「同块全文进两节」事故的现防线
    =各写手只注入自己需要的区间+节间查重，指引层降为提醒而非门禁）。"""
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n正文。\n", "服务方案", (3, 3))
    text = _guide(bid).replace("SCORE-02 | 【缺】", f"SCORE-02 | {bid}")
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]")  # 弱级提示不挡
    assert "素材块" in r and "《服务方案》" in r
    assert "同时派给 2 个节（3.1 项目理解与需求分析、3.2 总体设计方案）" in r
    assert "同一内容区间不得进两节" in r  # 区间纪律随行给出


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
    assert "[待办批注/占位] 无" in r


def test_section_placeholder_census_not_issue(env):
    """md 节是旧任务兼容形态（无批注能力）：内联占位维持清点进 notes，不判不过。"""
    _seed_directory(env)
    _write_body(env, "body/3.3 项目团队配置.md",
                "团队拟投入 5 人。\n\n【待补：项目经理一级建造师证书】\n\n【待澄清：驻场人数是否含后台】\n")
    r = validate_body.invoke({"section": "body/3.3 项目团队配置.md", "block_ids": []})
    assert r.startswith("[校验通过]")
    assert "[待办批注/占位] 共 2 处" in r
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


def test_section_block_id_range_suffix_usage(env):
    """block_ids 支持 blk_…:L起-L止 后缀（2026-09-15 注入粒度自选批）：只注入了
    块内区间时使用率按该区间算——整块口径会把子区间注入误报「未实质使用」；
    裸 id 行为不变；后缀解析由校验侧宽松处理（授权围栏在注入工具侧硬拦）。"""
    _seed_directory(env)
    lines = [
        f"第{i:02d}章：平台功能描述与实施方案详述，覆盖流程引擎、表单设计与业务模型能力第{i:02d}段展开说明。"
        for i in range(1, 61)
    ]
    md = "# 平台介绍\n\n" + "\n".join(lines) + "\n"
    # 块勾选全文（L1-L62）；节正文只承袭最后 3 段（第 58-60 章 → md L60-L62）
    bid = _seed_block("平台方案.txt", md, "平台大块", (1, 62))
    used = "\n".join(lines[57:])
    _write_body(env, "body/3.2 总体设计方案.md", f"## 3.2 总体设计方案\n\n{used}\n")
    # 裸 id：整块口径 → 3/60 低于阈值，报「未实质使用」（旧口径的误报形态）
    r = validate_body.invoke({"section": "body/3.2 总体设计方案.md", "block_ids": [bid]})
    assert r.startswith("[校验通过]")  # 提示不是门禁
    assert "未实质使用素材" in r
    # 后缀区间：按实际注入的区间算 → 不再误报
    r2 = validate_body.invoke(
        {"section": "body/3.2 总体设计方案.md", "block_ids": [f"{bid}:L60-L62"]}
    )
    assert r2.startswith("[校验通过]")
    assert "未实质使用素材" not in r2
    # 后缀不在块勾选范围内：校验侧宽松不崩（回落区间文本照算，提示与否随内容）
    r3 = validate_body.invoke(
        {"section": "body/3.2 总体设计方案.md", "block_ids": [f"{bid}:L1-L999"]}
    )
    assert r3.startswith("[校验通过]")


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


def test_guide_note_tool_name_warns(env):
    """缺口列混入工具名 → 提示级（2026-09-13 读者分离批）。

    动因：该列同时是给写手的指令与给用户的缺料点名，实测用户看到
    「格式件：docx_source_inject 拷第五章格式（L988-L1005）+revise 填…【缺：上述公司信息】」
    原话反馈「真看不懂」。执行链路由模式列 + 派发说明自动补，工具名是噪声。
    """
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n正文。\n", "块", (3, 3))
    text = _guide(bid).replace(
        "| 附件：资质证书复印件 | — | MAND-02 | — | 模板填充，列待填清单 |\n",
        "| 附件：资质证书复印件 | — | MAND-02 | — | "
        "格式件：docx_source_inject 拷第五章格式（L988-L1005）+revise 填空 |\n",
    )
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]")  # 提示不是门禁
    assert "缺口列混入工具名 docx_source_inject" in r
    assert "原件：<格式名> L起-L止" in r


def test_guide_note_anaphora_warns(env):
    """【缺：上述…】代词回指 → 提示级（前端会把【缺】摘出来独立展示，代词摘出后读不通）。"""
    _seed_directory(env)
    bid = _seed_block("园区方案.txt", "# 方案\n\n正文。\n", "块", (3, 3))
    text = _guide(bid).replace(
        "| 附件：资质证书复印件 | — | MAND-02 | — | 模板填充，列待填清单 |\n",
        "| 附件：资质证书复印件 | — | MAND-02 | — | "
        "格式件：拷第五章格式；【缺：上述公司信息与法定代表人身份证复印件】 |\n",
    )
    _write_body(env, "body/写作指引.md", text)
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]")  # 提示不是门禁
    assert "缺口项用了代词回指" in r
    assert "请列具体字段名" in r



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


def test_global_broken_docx_isolated(env):
    """坏节隔离（2026-09-10 review）：单个损坏 docx 不拖垮全局——剔除并点名，
    其余节的承诺比对照常跑；全部损坏才失败。"""
    _write_body(env, "body/关键事实与承诺.md",
                "| 事项 | 值 | 说明 |\n|---|---|---|\n| 工期 | 90 天 | 拍板 |\n")
    _write_body(env, "body/3.1 项目理解.md", "工期 90 天。\n")
    bad = _wroot(env[0]) / "body" / "3.2 损坏节.docx"
    bad.write_bytes(b"not a docx at all")
    r = validate_body.invoke({"section": "body"})
    assert r.startswith("[校验通过] body 全局")  # 好节照常比对
    assert "承诺 1 项比对，1 项已落正文" in r
    assert "损坏节" in r and "body/3.2 损坏节.docx" in r
    # 全部损坏 → 明确失败而非「0 项已落正文」的误导通过
    (_wroot(env[0]) / "body" / "3.1 项目理解.md").unlink()
    (_wroot(env[0]) / "body" / "3.1 项目理解.docx").write_bytes(b"broken too")
    r2 = validate_body.invoke({"section": "body"})
    assert r2.startswith("[校验失败]") and "全部损坏" in r2


# ---------- docx 正文节（终稿视角校验） ----------


def _make_docx_section(env, rel: str, title: str, paragraphs: str = "") -> None:
    from app.tools.docx_ops import docx_section_create

    r = docx_section_create.invoke({"path": rel, "title": title, "paragraphs": paragraphs})
    assert r.startswith("[已创建]"), r


def test_section_docx_placeholder_is_issue(env):
    """docx 节内联占位判不过（占位文字会进交付稿）——待办正规落点是 Word 批注。"""
    _make_docx_section(env, "body/3.3 项目团队配置.docx", "3.3 项目团队配置",
                       "团队拟投入 5 人。\n【待补：项目经理证书】")
    r = validate_body.invoke({"section": "body/3.3 项目团队配置.docx", "block_ids": []})
    assert r.startswith("[校验未通过]")
    assert "P3：正文含内联占位「【待补：项目经理证书】」" in r  # P1=标题、P2=团队段、P3=占位段
    assert "docx_comment_add" in r


def test_section_docx_table_placeholder_t_label(env):
    """表格单元格里的占位按 T{t}R{r} 定位（与读视图格坐标互查，不再是越界 P 号）；
    docx 内联占位同样判不过。"""
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
    assert r.startswith("[校验未通过]")
    assert "T1R1：正文含内联占位" in r


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
    """终稿视角：插入修订的占位计为 issue、删除修订的占位不计（评委看到的是终稿）。"""
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
    assert r.startswith("[校验未通过]") and "共 1 处问题" in r
    assert "P3：正文含内联占位「【待澄清：插入的占位】」" in r
    assert "要删的占位" not in r


def test_section_docx_comment_census(env):
    """docx_comment_add 落的待办批注清点进 notes（收尾点名），不影响 [校验通过]。"""
    from app.tools.docx_ops import docx_comment_add

    _make_docx_section(env, "body/3.3 项目团队配置.docx", "3.3 项目团队配置",
                       "团队拟投入 5 人。")
    assert docx_comment_add.invoke({
        "path": "body/3.3 项目团队配置.docx", "after": "2",
        "text": "项目经理一级建造师证书编号缺失，需向用户确认后回填",
    }).startswith("[已加批注]")
    r = validate_body.invoke({"section": "body/3.3 项目团队配置.docx", "block_ids": []})
    assert r.startswith("[校验通过]")
    assert "[待办批注/占位] 共 1 处" in r
    assert "P2〔批注〕：项目经理一级建造师证书编号缺失" in r


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


def test_section_docx_direct_outline_note(env):
    """直挂大纲级别清点（提示级，2026-09-13 批）：历史拷贝残留的 outlineLvl 段
    在读视图里不可见，导航窗格却出现树外条目——清点点名（合册会自动摘出，
    不判不过）。"""
    from docx import Document as _Doc
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    _make_docx_section(env, "body/3.1 项目理解.docx", "3.1 项目理解", "正文一段。")
    p = _wroot(env[0]) / "body" / "3.1 项目理解.docx"
    doc = _Doc(str(p))
    para = doc.add_paragraph("附件11人员资格一览表")
    para._p.get_or_add_pPr().append(parse_xml(f'<w:outlineLvl {nsdecls("w")} w:val="2"/>'))
    doc.save(p)

    r = validate_body.invoke({"section": "body/3.1 项目理解.docx", "block_ids": []})
    assert r.startswith("[校验通过]")  # 提示不是门禁
    assert "〔大纲级别〕1 段直挂大纲级别（P3）" in r
    assert "合册会自动摘出" in r


def test_section_docx_numbered_heading_note(env):
    """标题段自动编号清点（提示级，2026-09-16 批）：素材拷入的编号标题段
    （直挂 numPr 或标题样式自带 numPr）在整本里按素材内部层级渲染——清点
    点名（合册两层剥除，不判不过）；正文列表段（非标题样式）不点名。"""
    from docx import Document as _Doc
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    _make_docx_section(env, "body/3.1 项目理解.docx", "3.1 项目理解", "正文一段。")
    p = _wroot(env[0]) / "body" / "3.1 项目理解.docx"
    doc = _Doc(str(p))
    # 标题段直挂 numPr
    head = doc.add_paragraph("素材小节标题甲")
    head.style = doc.styles["Heading 2"]
    head._p.get_or_add_pPr().append(parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="4"/><w:numId w:val="12"/></w:numPr>'
    ))
    # 正文列表段（Normal 样式，不命中标题判据）
    plain = doc.add_paragraph("列表项一条")
    plain._p.get_or_add_pPr().append(parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="13"/></w:numPr>'
    ))
    doc.save(p)

    r = validate_body.invoke({"section": "body/3.1 项目理解.docx", "block_ids": []})
    assert r.startswith("[校验通过]")  # 提示不是门禁
    assert "〔自动编号〕1 个标题段带自动编号（P3）" in r
    assert "合册会自动剥除" in r


# ---------- 表格通道批（2026-09-14）：md 残字扫描 + 图示对账 ----------


def _write_section(env, name: str, paragraphs: str, tables_json: str | None = None) -> None:
    from app.tools.docx_ops import docx_section_create

    docx_section_create.invoke(
        {"path": f"body/{name}", "title": name, "paragraphs": paragraphs, "body": tables_json or ""}
    )


def test_md_residue_scan(env):
    """md 残字：行首 #/整行竖线表/「**」判不过（会印进交付稿），反引号降提示；
    有序编号「1. 」是中文正文合法形态不扫。"""
    _write_section(
        env, "残字节",
        "正常段落。\n## 小标题残字\n含**加粗**残字的段落。\n| 列一 | 列二 |\n1. 有序编号是合法形态\n含`反引号`的段。",
    )
    r = validate_body.invoke({"section": "body/残字节.docx"})
    assert r.startswith("[校验未通过]")
    assert "markdown 标题残字" in r
    assert "「**」加粗残字" in r
    assert "竖线拼的 markdown 表格残字" in r
    assert "反引号" in r and "⚠️" in r  # 反引号=提示级（⚠️ 段）
    assert "有序编号" not in r  # 1. 合法不扫

    _write_section(env, "干净节", "全部正常段落，无任何标记残字。")
    r2 = validate_body.invoke({"section": "body/干净节.docx"})
    assert "残字" not in r2


def test_figure_reconcile_and_guide_column(env):
    """指引图示列：类型词合法校验（warning）+ 节级对账三态（计划未产出点名/
    计划外插图提示/相符无提示）；旧 5 列指引缺图示列零影响。"""
    _seed_directory(env)
    wroot = _wroot(env[0])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    # 6 列指引：一行类型词不合法、一行计划 2 项、一行未计划
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 图示 | 缺口/备注 |\n"
        "|---|---|---|---|---|---|\n"
        "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | 饼图:占比 | — |\n"
        "| 3.2 总体设计方案 | 推理撰写 | SCORE-02 | — | 表:对比、甘特:进度 | — |\n"
        "| 3.3 项目团队配置 | 推理撰写 | — | — | — | — |\n",
        encoding="utf-8",
    )
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert "图示项「饼图:占比」记法须为「类型:主题」" in r

    # 3.2 计划 2 项、实收 0 张表 → 计划未产出点名（节名与指引行逐字对齐才对账）
    _write_section(env, "3.2 总体设计方案", "方案正文，无表格。")
    r2 = validate_body.invoke({"section": "body/3.2 总体设计方案.docx"})
    assert "指引计划 2 项、节内表格/图片 0 项" in r2
    assert "表:对比" in r2 and "甘特:进度" in r2

    # 3.3 未计划、推理撰写、有表 → 计划外提示
    import json as _json

    tbl = _json.dumps(
        [{"type": "p", "text": "配置如下："},
         {"type": "table", "header": ["岗位"], "rows": [["项目经理"]]}],
        ensure_ascii=False,
    )
    _write_section(env, "3.3 项目团队配置", "", tables_json=tbl)
    r3 = validate_body.invoke({"section": "body/3.3 项目团队配置.docx"})
    assert "指引未计划图示、节内有 1 项表格/图片" in r3

    # 3.1 计划与实收不符修正后……计划 1 项实收 1 张=相符无提示
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 图示 | 缺口/备注 |\n"
        "|---|---|---|---|---|---|\n"
        "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | 表:清单 | — |\n",
        encoding="utf-8",
    )
    _write_section(env, "3.1 项目理解与需求分析", "", tables_json=tbl)
    r4 = validate_body.invoke({"section": "body/3.1 项目理解与需求分析.docx"})
    assert "〔图示〕" not in r4

    # 原型类型词（2026-09-14 批二）：合法通过；图示对账实收计图片（a:blip）
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 图示 | 缺口/备注 |\n"
        "|---|---|---|---|---|---|\n"
        "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | 原型:审批界面 | — |\n",
        encoding="utf-8",
    )
    r5 = validate_body.invoke({"section": "body/写作指引.md"})
    assert "记法须为" not in r5


def test_guide_old_five_columns_still_valid(env):
    """旧 5 列指引（无图示列）照常通过——缺列取空串零影响。"""
    _seed_directory(env)
    wroot = _wroot(env[0])
    (wroot / "body").mkdir(parents=True, exist_ok=True)
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n"
        "|---|---|---|---|---|\n"
        "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | — |\n",
        encoding="utf-8",
    )
    r = validate_body.invoke({"section": "body/写作指引.md"})
    assert r.startswith("[校验通过]") or "图示" not in r
