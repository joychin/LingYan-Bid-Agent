"""派发拼装（dispatch_enrich）：tender-body-writer 派发说明的程序化补全。

契约要点：瘦派发→程序拼共享上下文；对不上/多义/已富文本→放行原文；
产出文本零 REQ/MAND/SCORE/TPL 编号（派发契约，编号会被写手镜像进正文）。
"""

import json
import re
from datetime import date

import pytest

from app import artifact_store, runctx
from app.dispatch_enrich import build_enriched_description
from tests.util import init_env

_KEY = "tender.directory/tender-response-docs@1"

# 内联写作方法论段的起始标记（dispatch_enrich 的固定抬头）。方法论文档自身含
# 「REQ/MAND/SCORE/TPL-xx 是内部对账编号，一个都不写进正文」这类禁令句与
# 「可用素材块」「公司材料与缺口」等段名，故「某数据块未出现」「编号零出现」
# 这类断言必须只看程序拼装的数据部分，不能扫全串（否则被方法论自身措辞误伤）。
_SKILL_MARK = "写作纪律（完整方法论已在下方给出"


def _data_part(out: str) -> str:
    """派发说明里程序拼装的数据部分（截去尾部内联的写作方法论）。"""
    return out.split(_SKILL_MARK)[0]


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
    # 开工硬纪律（2026-09-14 回读收敛批）：开局禁探测/禁内部编号
    assert "开局禁止 ls/glob 探测目录" in out
    assert "禁止检索或使用 REQ/MAND/SCORE/TPL 内部编号" in out
    # 要求清单=registry 解析的原文+出处，编号解析后即弃
    assert "- 投标人须具备低代码开发能力（出处：第三章 3.1，L100-L110）" in out
    assert "承诺清单全部值" in out
    assert "- 项目名称：测试项目（招标文件封面用）" in out
    assert "兄弟节开头摘要" in out and "门户与工作台" in out
    # 派发契约：编号零出现
    for tag in ("REQ-", "SCORE-", "MAND-", "TPL-"):
        assert tag not in _data_part(out)


def test_promise_missing_fallback_points_to_comment_channel(env):
    """承诺清单缺失的兜底文案走批注出口（2026-09-16 prompt 一致性批）。

    旧句「缺项一律写【待澄清：…】不得编造」教写内联占位——validate_body 判
    不过，且与同载荷内联方法论的「正文禁止【待补】【待澄清】占位文字」自相
    矛盾（同一条任务描述里两条相反指令，模型二选一）。"""
    tid = _seed(env, promise=False)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out, "派发拼装意外放行"
    data = _data_part(out)
    assert "清单文件缺失或为空" in data and "docx_comment_add" in data
    assert "【待澄清" not in data, "兜底文案不得教写内联占位"


def test_multi_section_dispatch_shared_plus_per_section(env):
    """多节派发（2026-09-15 模型自主拆分批）：首行顿号分隔多节名 → 共享块一份 +
    逐节块每节一份；兄弟摘要排除本任务全部节（同任务节互见没必要）。"""
    from docx import Document

    tid = _seed(env, sibling=True)
    # 把 3.2 预写成兄弟文件：多节任务派发时它不该出现在兄弟摘要里（是本任务的节）
    d = Document()
    d.add_paragraph("预写的总体设计方案正文。")
    d.save(str(artifact_store.work_dir(tid) / "body/3.2 总体设计方案.docx"))
    out = build_enriched_description("写 3.1 项目理解、3.2 总体设计", tid)
    assert out is not None
    assert out.startswith("写 3.1 项目理解、3.2 总体设计\n〔系统附")
    assert "本任务共 2 节" in out
    assert "逐节完成" in out
    # 逐节块：两节各一份【第 N 节】+输出路径+模式
    assert "【第 1 节：3.1 项目理解与需求分析】" in out
    assert "【第 2 节：3.2 总体设计方案】" in out
    assert f"输出路径：{tid}/work/body/3.1 项目理解与需求分析.docx" in out
    assert f"输出路径：{tid}/work/body/3.2 总体设计方案.docx" in out
    # 共享块只一份：承诺/前缀不随节数翻倍（只看数据段——内联方法论自身会提到这些词）
    assert _data_part(out).count("承诺清单全部值") == 1
    assert _data_part(out).count(f"任务目录前缀：{tid}/") == 1
    assert out.count("写作纪律（完整方法论已在下方给出") == 1
    # 兄弟摘要：无关节（门户与工作台）在、本任务的节（3.2）不在
    assert "- 门户与工作台：" in out
    assert "- 3.2 总体设计方案：" not in out
    # 派发契约：编号零出现
    for tag in ("REQ-", "SCORE-", "MAND-", "TPL-"):
        assert tag not in _data_part(out)


def test_multi_section_dispatch_any_unmatched_passthrough(env):
    """全部节名都对不上（分块与首行整体兜底都救不回）→ 整体放行（不半拼）。"""
    tid = _seed(env)
    assert build_enriched_description("写 一个不存在的节、另一个也没有的节", tid) is None


def test_partial_names_fallback_enriches_resolvable(env):
    """一真一假节名：碎片失败后首行整体兜底命中真节、按单节拼装——与 2026-09-15
    前旧版整段探针行为一致（对两节全瘦放行更糟）；假名留给模型自纠，对账/extra
    侧报告兜底。"""
    tid = _seed(env)
    out = build_enriched_description("写 3.1 项目理解、一个不存在的节", tid)
    assert out is not None
    assert "本任务共" not in out  # 单节形态
    assert f"输出路径：{tid}/work/body/3.1 项目理解与需求分析.docx" in out


def test_separator_inside_title_falls_back_to_whole_line(env):
    """节名自身含顿号且前缀撞库：碎片探针歧义全灭 → 首行整体单探针兜底命中，
    按单节拼装（防「人员、设备配置表」这类名字被当多节拆碎后整体放行成瘦派发）。"""
    content = _dir_content()
    content["response_documents"][0]["directory"] = [
        {"目录名称": "人员、设备配置表", "level": 1, "children": [], "交付形态": "正文编写"},
        {"目录名称": "人员、设备清单", "level": 1, "children": [], "交付形态": "正文编写"},
    ]
    tid = _seed(env, content=content)
    out = build_enriched_description("写 人员、设备配置表", tid)
    assert out is not None
    assert f"输出路径：{tid}/work/body/人员、设备配置表.docx" in out
    assert "本任务共" not in out  # 单节形态（非多节）


def test_intent_on_second_line_does_not_break_match(env):
    """意图句在第二行不参与匹配——旧实现把整段描述当单一探针，被意图句打碎后
    静默放行（瘦派发事故形态）；2026-09-15 起只解析首行。"""
    tid = _seed(env)
    out = build_enriched_description("写 3.1 项目理解\n重点补移动端表单细节", tid)
    assert out is not None
    assert out.startswith("写 3.1 项目理解\n重点补移动端表单细节\n〔系统附")
    assert f"输出路径：{tid}/work/body/3.1 项目理解与需求分析.docx" in out


def test_rich_description_multi_section_anchors(env):
    """富描述多节：每节一条带节名的输出路径锚点（区分哪条路径属哪节）。"""
    tid = _seed(env)
    rich = "写 3.1 项目理解、3.2 总体设计\n补充说明：" + "细节" * 160
    assert len(rich) > 300
    out = build_enriched_description(rich, tid)
    assert out is not None
    assert (
        f"输出路径（3.1 项目理解与需求分析）：{tid}/work/body/3.1 项目理解与需求分析.docx"
        in out
    )
    assert f"输出路径（3.2 总体设计方案）：{tid}/work/body/3.2 总体设计方案.docx" in out


def test_writer_skill_inlined_with_no_reread_hint(env):
    """写作方法论内联（2026-09-12）：写手子代理无 SkillsMiddleware，此前每节都要自己
    read_file 读一遍 section-writing.md（实测全库 215 次、205 次在子代理）；改为主代理
    派发时附全文 + 明确「不要再读」，省一次往返与一份回灌。"""
    tid = _seed(env)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    assert "写作纪律" in out and "不要再 read_file" in out
    # 内联的是方法论正文本身（标题为稳定锚点），不是路径引用
    assert "# 逐节写作细则（素材先行）" in out
    assert "## 素材修订（默认模式）" in out


def test_writer_skill_inline_degrades_when_missing(env, monkeypatch):
    """读不到方法论只损失该段，其余拼装照常（降级绝不打断派发）。"""
    tid = _seed(env)
    monkeypatch.setattr("app.dispatch_enrich._skill_text", lambda: None)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    assert "写作纪律" not in out
    assert f"输出路径：{tid}/work/body/3.1 项目理解与需求分析.docx" in out


def test_skill_text_cached_across_calls(env):
    """进程内缓存：同 run 多次派发复用同一字符串（单 run 内字节稳定，前缀缓存无伤）。"""
    from app import dispatch_enrich

    dispatch_enrich._skill_cache = None
    first = dispatch_enrich._skill_text()
    assert first and "逐节写作细则" in first
    assert dispatch_enrich._skill_cache is first  # 二次调用命中缓存
    assert dispatch_enrich._skill_text() is first


def test_skill_inline_no_internal_ids(env):
    """程序拼装的数据部分零编号（派发契约：REQ/MAND/SCORE/TPL 不进写手语境）。
    内联方法论自身含一句「编号一个都不写进正文」的禁令，故只扫数据部分。"""
    tid = _seed(env)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    for tag in ("REQ-", "SCORE-", "MAND-", "TPL-"):
        assert tag not in _data_part(out)


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


def test_rich_description_passthrough_when_first_line_unmatched(env):
    """富描述且首行对不上目录叶子 → 放行原文（宁可不猜原则不变）。"""
    tid = _seed(env)
    rich = "写 3.1 项目理解。" + "细节" * 160
    assert len(rich) > 300
    assert build_enriched_description(rich, tid) is None


def test_rich_description_gets_path_anchor(env):
    """富描述（>300 字）：语义信任原文，但仍注入最小路径锚点。

    2026-09-15 路径可靠性批：r_eedd621716b5 富描述被整体放行后，13 节由写手
    自选了章节子目录路径、合册只认出 46/59——输出路径是程序算的契约事实，
    不随描述长度丢失。"""
    tid = _seed(env)
    rich = "写 3.1 项目理解\n推理撰写模式。覆盖招标提出的稳定性要求：" + "细节" * 160
    assert len(rich) > 300
    out = build_enriched_description(rich, tid)
    assert out is not None
    # 原文完整保留（首行=模型原话），锚点块追加在末尾
    assert out.startswith("写 3.1 项目理解\n推理撰写模式。")
    assert out.endswith(
        f"\n〔系统附：路径锚点（程序自动生成，直接使用）：\n"
        f"任务目录前缀：{tid}/\n"
        f"输出路径：{tid}/work/body/3.1 项目理解与需求分析.docx\n"
        f"今天日期：{date.today().isoformat()}"
    )
    # 最小块：语义上下文不重复拼（承诺/素材/要求清单只在全量路径给）
    assert "承诺清单全部值" not in out
    assert "要求清单" not in out
    # 幂等：带锚点的描述再进一层不再拼装
    assert build_enriched_description(out, tid) is None


def test_material_card_resolved_from_guide(env):
    """素材列 blk id → 逐块名片（标题/字数/来源文件/区间/备注）：写手据此直接
    使用，不再每节重检索素材库（指引期检索的内容层复用）；区间随名片下发——
    块是拷贝授权范围，写手据此挑本节要注入的行号区间。"""
    from app import db

    f = db.mt_insert_file("历史标书-某政务项目.docx", file_hash="h_mt1")
    db.mt_replace_blocks(
        f["id"],
        [
            {
                "id": "blk_abc123def456",
                "title": "运维服务方案",
                "note": "通用运维章节，改项目名即可",
                "ranges": json.dumps([[10, 80]]),
                "chars": 1200,
            }
        ],
    )
    tid = _seed(env)
    out = build_enriched_description("写 3.2 总体设计", tid)
    assert out is not None
    assert "可用素材块（拷贝授权范围：据此列使用计划，按需整块或挑块内区间注入，无需再检索）：" in out
    assert "《运维服务方案》（约 1,200 字）" in out
    assert "来源文件：历史标书-某政务项目.docx" in out
    assert "id：blk_abc123def456" in out
    assert "区间：L10-L80" in out  # 区间随名片——写手挑 lines 的依据
    assert "备注：通用运维章节，改项目名即可" in out
    assert "SCORE-" not in _data_part(out)  # 派发契约：编号零出现


def test_material_section_absent_or_stale(env):
    """素材列无 blk id（—/【缺】）不拼块段；块 id 库里查不到 → 失效提示降级
    （写手自行检索），不是静默丢素材信息。"""
    tid = _seed(env)
    # 3.1 行素材列=—：无块段
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert out is not None
    assert "可用素材块" not in _data_part(out)
    # 3.2 行素材列=blk_abc123def456 但素材库无此块（未 seed）：失效提示
    out = build_enriched_description("写 3.2 总体设计", tid)
    assert out is not None
    assert "可用素材块（拷贝授权范围：据此列使用计划，按需整块或挑块内区间注入，无需再检索）：" in out
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
    assert "公司材料与缺口" not in _data_part(out)


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
    assert "TPL-" not in _data_part(out)


def test_multi_volume_path_sanitizes_volume_name(env):
    """册名含 : 等路径非法字符：输出路径与兄弟摘要目录都走 sanitize_name——与
    实际落点（docx_assemble_volume/check_pipeline）同口径，原样拼接指错路径
    （2026-09-10 review）。注：册名含 / 属「册名/标题」拆分协议的既有限制，不在此测。"""
    content = _multi_volume_content()
    content["response_documents"][0]["name"] = "技术:第一册"
    task = env[0]
    from app import publish

    publish.publish_artifact(_KEY, content, task_id=task["id"])
    wroot = artifact_store.work_dir(task["id"])
    from app.tools.body_contract import sanitize_name

    assert "技术:第一册" != sanitize_name("技术:第一册")  # 确认该名确实会被清洗
    vol_dir = wroot / "body" / sanitize_name("技术:第一册")
    vol_dir.mkdir(parents=True, exist_ok=True)
    from docx import Document as _D

    d = _D()
    d.add_paragraph("已写节的开头摘要文本。")
    d.save(str(vol_dir / "已写节.docx"))
    (wroot / "body/写作指引.md").write_text(
        "| 节 | 模式 | 依据 | 素材 | 缺口/备注 |\n|---|---|---|---|---|\n"
        "| 技术:第一册/投标函 | — | TPL-02 | — | 格式件：拷原件+填空 |\n",
        encoding="utf-8",
    )
    out = build_enriched_description("写投标函", task["id"])
    assert out is not None
    # 路径行=清洗后的册目录（原样拼「:」在部分文件系统上即非法路径）
    assert f"输出路径：{task['id']}/work/body/{sanitize_name('技术:第一册')}/投标函.docx" in out
    # 兄弟摘要目录同样清洗（清洗错误时摘要恒空——找不到目录）
    assert "已写节" in out


# ---------- 原件定位行（2026-09-10） ----------


def _seed_outline(env, fname: str, nodes: list) -> None:
    """往 work/parse/<文件名>/ 落一份 outline.json（标题树形态同 parse_document）。"""
    pdir = artifact_store.work_dir(env[0]["id"]) / "parse" / fname
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{fname}.outline.json").write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")


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
        assert tag not in _data_part(out)


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


# ---------- 转述节名脱靶（2026-09-10 实测形态） ----------


def _perf_content():
    """大地任务实测目录片段：附件6/附件7 两张格式件表（派发脱靶事故现场）。"""
    return {
        "response_documents": [
            {
                "name": "技术部分",
                "scope": "",
                "directory": [
                    {"目录名称": "近三年承接类似项目情况一览表（附件6）", "level": 1, "children": [],
                     "交付形态": "格式跟随", "来源位置": ["TPL-09"]},
                    {"目录名称": "投标单位财务状况一览表（附件7）", "level": 1, "children": [],
                     "交付形态": "格式跟随", "来源位置": ["TPL-10"]},
                ],
            }
        ],
        "registry": {
            "TPL-09": {"type": "模板", "text": "按附件6格式填报近三年类似项目", "出处": "第三章 附件6"},
            "TPL-10": {"type": "模板", "text": "按附件7格式填报财务状况", "出处": "第三章 附件7"},
        },
    }


def test_paraphrased_name_misses_passthrough(env):
    """2026-09-10 实测形态：模型转述节名（「情况一览表」说成「业绩表」）→
    精确/包含/近似全不中（对最近叶 ratio≈0.385 < 0.55）→ 放行裸描述，
    子代理拿不到〔系统附〕块只能开局自救重读指引/清单——正是派发拼装
    要省的开销。「宁可不猜」设计的已知失败半径；若加兜底（表尾词变体
    匹配/附节无关罗盘两行），翻转本断言。"""
    tid = _seed(env, content=_perf_content())
    out = build_enriched_description("写类似项目业绩表", tid)
    assert out is None  # 实锚：转述改词 0 命中 → 放行


def test_echo_substring_name_enriches(env):
    """对照组（同日同批 31 派发中 30 例命中的典型形态）：派发短名是叶子名
    的子串回声（「财务状况一览表」⊂「投标单位财务状况一览表（附件7）」）→
    包含命中、正常拼装——边界：回声命中、改词脱靶。"""
    tid = _seed(env, content=_perf_content())
    out = build_enriched_description("写财务状况一览表", tid)
    assert out is not None
    assert "投标单位财务状况一览表（附件7）.docx" in out


def test_figure_column_transmitted_to_writer(env):
    """图示列透传（2026-09-14 表格通道批）：6 列指引的图示列随派发送达写手
    （计划先行——写手按清单逐项产出）；旧 5 列指引缺列零影响（无图示段）。"""
    tid = _seed(env)
    out = build_enriched_description("写 3.1 项目理解", tid)
    assert "本节图示清单" not in out  # 旧 5 列指引：无图示段

    wroot = artifact_store.work_dir(tid)
    content = _dir_content()
    content["response_documents"][0]["directory"].append(
        {"目录名称": "3.3 混合记法节", "level": 1, "children": [], "交付形态": "正文编写"}
    )
    tid = _seed(env, content=content)  # 重发布目录产物（同任务同契约=覆盖）
    wroot = artifact_store.work_dir(tid)
    (wroot / "body/写作指引.md").write_text(
        "# 写作指引\n\n"
        "| 节 | 模式 | 依据 | 素材 | 图示 | 缺口/备注 |\n|---|---|---|---|---|---|\n"
        "| 3.1 项目理解与需求分析 | 推理撰写 | REQ-01 | — | 分层:系统架构、表:对比 | 无 |\n"
        "| 3.2 总体设计方案 | 素材修订 | SCORE-02 | blk_abc123def456 | — | 无 |\n"
        "| 3.3 混合记法节 | 推理撰写 | REQ-03 | — | 表:对比、— | 无 |\n",
        encoding="utf-8",
    )
    out2 = build_enriched_description("写 3.1 项目理解", tid)
    assert "本节图示清单（指引计划，逐项产出" in out2
    assert "分层:系统架构、表:对比" in out2
    out3 = build_enriched_description("写 3.2 总体设计", tid)
    assert "本节图示清单" not in out3  # 「—」不透传
    # 混合项过滤与 validate_body 对账侧同款口径（2026-09-14 review 修复）：
    # 「表:对比、—」不把「—」当计划项透传
    out4 = build_enriched_description("写 3.3 混合记法", tid)
    assert "本节图示清单" in out4 and "表:对比" in out4
    assert "表:对比、—" not in out4
