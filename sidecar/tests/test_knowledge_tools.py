"""双检索工具（素材分离模型）+ 残留扫描：事实查知识库（角色加权/业绩启发式）、
写法查素材库（用户勾选块+备注）、素材段隔离、evidence 行。"""

import json

from app import db
from app.knowledge import materials_lib as mlib
from app.knowledge import store
from app.knowledge.ingest import reindex_item
from app.knowledge.materials_lib import run_parse
from app.parse import outline_with_lines
from app.tools.check_residue import check_name_residue
from app.tools.search_knowledge import search_company_assets, search_references
from tests.util import init_env


def _setup(tmp_path, monkeypatch):
    init_env(tmp_path, monkeypatch)
    store.ensure_dirs()
    mlib.ensure_dirs()


def _seed(md: str, file_name: str, doc_type: str, meta: dict | None = None) -> str:
    """知识库条目（事实层）。"""
    md_path, outline_path, meta_path, _ = store.kb_parse_paths(file_name)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    outline_path.write_text(json.dumps(outline_with_lines(md), ensure_ascii=False), encoding="utf-8")
    meta_path.write_text("{}", encoding="utf-8")
    item = db.kb_insert_item(file_name=file_name, file_hash=file_name, title="t", ext=".txt")
    db.kb_update_item(item["id"], parse_status="ready", doc_type=doc_type)
    if meta:
        db.kb_update_item(item["id"], **{
            "business_metadata": json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else meta,
        })
    reindex_item(item["id"])
    return item["id"]


def _seed_block(file_name: str, md: str, title: str, note: str, lines: tuple[int, int]) -> str:
    """素材文件+块（写法层）。返回块 id。"""
    import hashlib

    src = mlib.mt_files_dir() / file_name
    src.write_text(md, encoding="utf-8")
    f = db.mt_insert_file(file_name=file_name, file_hash=hashlib.sha256(md.encode()).hexdigest())
    run_parse(f["id"])
    block = mlib.create_block(f["id"], title, note, [list(lines)])
    assert block, "素材块创建失败（区间无效？）"
    return block["id"]


def test_company_fact_verified_first_and_candidate(tmp_path, monkeypatch):
    """fact 类命中排前；历史标书业绩章（标题启发式）命中标「业绩候选·须核对」；
    纯写法段被排除。"""
    _setup(tmp_path, monkeypatch)
    _seed("# 资质\n\n张三持有 PMP 项目管理专业人士资格认证证书，编号 PM-001",
          "pm.txt", "personnel_certificate")
    md = (
        "# 项目业绩\n\n2021 年承建的智慧园区一体化平台项目，合同金额 1200 万元，验收优秀。\n\n"
        "# 服务方案\n\n运维服务体系组织与流程说明正文。"
    )
    _seed(md, "历史标书.txt", "past_proposal",
                {"doc_type": "past_proposal", "fields": {"project_name": {"value": "智慧园区项目"}}})

    out = search_company_assets.invoke({"query": "智慧园区 项目"})
    assert "公司资料命中" in out
    # 业绩章命中且带候选标注（启发式）
    assert "业绩候选·须核对" in out
    assert "项目业绩" in out
    # 纯写法段（服务方案）不出现
    assert "服务方案" not in out
    # evidence 行含 role 且可解析
    ev_line = next(ln for ln in out.splitlines() if ln.startswith("[evidence] "))
    ev = json.loads(ev_line[len("[evidence] "):])
    roles = [it["role"] for it in ev["items"]]
    assert "fact-candidate" in roles
    # 关联证明材料（同项目名的 fact 条目）
    _seed("# 合同\n\n智慧园区项目合同", "合同.txt", "contract_case",
          {"doc_type": "contract_case", "fields": {"project_name": {"value": "智慧园区项目"}}})
    out2 = search_company_assets.invoke({"query": "智慧园区 项目"})
    assert "关联证明材料：合同.txt" in out2


def test_company_statement_hit_ai_note(tmp_path, monkeypatch):
    """说明段（§statement）命中带「AI 整理」标注——财报正文的语义入口。"""
    _setup(tmp_path, monkeypatch)
    kid = _seed("# 审计\n\n表格数字正文。", "审计报告.txt", "financial_report")
    db.kb_update_item(kid, suggested_metadata=json.dumps(
        {"doc_type": "financial_report", "statement": "净资产 8.2 亿元（第7页）；营收 12.7 亿元（第5页）。"},
        ensure_ascii=False))
    reindex_item(kid)
    out = search_company_assets.invoke({"query": "净资产"})
    assert "AI 整理" in out and "8.2 亿元" in out


def test_flat_document_performance_visibility(tmp_path, monkeypatch):
    """平铺文档（全六级标题、无 level≤2）业绩盲区：顶层兜底段带标题路径 →
    业绩词表命中 fact-candidate。"""
    _setup(tmp_path, monkeypatch)
    md = (
        "###### 公司业绩清单\n\n2021 年承建某市政务云平台项目，合同金额 800 万元，验收优秀。\n\n"
        "###### 门户功能说明\n\n门户功能的写法正文说明内容补充文本较长一些。"
    )
    _seed(md, "平铺标书.txt", "past_proposal",
          {"doc_type": "past_proposal", "fields": {"project_name": {"value": "政务云项目"}}})
    out = search_company_assets.invoke({"query": "政务云 项目"})
    assert "业绩候选·须核对" in out
    assert "公司业绩清单" in out


def test_references_hits_blocks_with_note(tmp_path, monkeypatch):
    """写法检索：命中用户素材块（标题+备注+区间+拷贝指引）；骨架=块清单。"""
    _setup(tmp_path, monkeypatch)
    md = "# 运维服务方案\n\n" + "\n".join(f"运维服务 SLA 承诺表述第{i}条补充说明文本。" for i in range(20))
    _seed_block("标书范文.txt", md, "运维 SLA 章节块", "政务云运维，写法成熟", (1, 12))
    _seed("# 证书\n\n张三的 PMP 证书", "pm.txt", "personnel_certificate")

    out = search_references.invoke({"query": "运维 承诺"})
    assert "写作素材命中" in out
    assert "禁止直接沿用" in out
    assert "《运维 SLA 章节块》" in out        # 块标题
    assert "政务云运维，写法成熟" in out       # 备注
    assert "check_name_residue" in out         # 拷贝指引
    assert "素材块全景" in out                 # 骨架=块清单
    assert "pm.txt" not in out                 # 知识库段不进写法检索
    ev_line = next(ln for ln in out.splitlines() if ln.startswith("[evidence] "))
    ev = json.loads(ev_line[len("[evidence] "):])
    assert any(it["role"] == "writing-reference" and it.get("ranges") for it in ev["items"])

    # 备注词命中（正文没有的词）
    out2 = search_references.invoke({"query": "政务云"})
    assert "《运维 SLA 章节块》" in out2


def test_empty_hints(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert "公司资料无命中" in search_company_assets.invoke({"query": "不存在的词xyzzy"})
    assert "写作素材无命中" in search_references.invoke({"query": "不存在的词xyzzy"})


def test_check_residue_detects_planted_name(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    kid = _seed("# 业绩\n\n内容", "旧项目.txt", "past_proposal",
                {"doc_type": "past_proposal",
                 "fields": {"project_name": {"value": "智慧园区一期"}, "client": {"value": "某市管委会"}}})
    text = "本项目为智慧园区一期建设项目。\n由某市管委会于 2021 年发包。\n本次全新方案。"
    out = check_name_residue.invoke({"text": text, "source_item_id": kid})
    assert "旧名残留告警" in out
    assert "智慧园区一期" in out and "某市管委会" in out
    assert "L1" in out and "L2" in out
    # 干净文本通过
    out2 = check_name_residue.invoke({"text": "全新方案无残留。", "source_item_id": kid})
    assert "残留扫描通过" in out2
    # 显式名单兜底
    out3 = check_name_residue.invoke({"text": "老东家华信科技承接。", "old_names": ["华信科技"]})
    assert "华信科技" in out3


def test_check_residue_accepts_mt_file_id(tmp_path, monkeypatch):
    """残留扫描 source_item_id 兼收素材文件 id（mt 前缀）——文件名主干入**弱级**
    名单（2026-09-06 分级：项目名常混通用产品词，命中是疑似提示非必须清零）。"""
    _setup(tmp_path, monkeypatch)
    md = "# 方案\n\n" + "正文内容说明。" * 10
    import hashlib

    src = mlib.mt_files_dir() / "智慧园区一期 方案.txt"
    src.write_text(md, encoding="utf-8")
    f = db.mt_insert_file(file_name="智慧园区一期 方案.txt",
                          file_hash=hashlib.sha256(md.encode()).hexdigest())
    out = check_name_residue.invoke({"text": "本方案基于智慧园区一期经验。", "source_item_id": f["id"]})
    assert "疑似残留提示" in out
    assert "智慧园区一期" in out
    assert "旧名残留告警" not in out  # 纯文件名来源=弱级，不进硬告警段


def test_check_residue_hard_and_soft_tiers_together(tmp_path, monkeypatch):
    """硬级（元数据项目名/显式名单）与弱级（文件名主干）同现时分段输出；
    通过文案带两级计数。"""
    _setup(tmp_path, monkeypatch)
    kid = _seed("# 业绩\n\n内容", "某项目 旧档案库.txt", "past_proposal",
                {"doc_type": "past_proposal",
                 "fields": {"project_name": {"value": "智慧园区一期"}}})
    text = "本项目沿用智慧园区一期经验，整理自旧档案库，老东家华信科技提供。"
    out = check_name_residue.invoke({"text": text, "source_item_id": kid, "old_names": ["华信科技"]})
    assert "旧名残留告警" in out
    assert "智慧园区一期" in out and "华信科技" in out
    assert "疑似残留提示" in out and "旧档案库" in out  # 文件名主干分段词≥4字入弱级
    # 硬级与弱级分段：弱级名不作为独立残留条目进「必须替换」段（行上下文引文除外）
    assert "残留「旧档案库」" not in out.split("疑似残留提示")[0]


def test_company_assets_image_hint(tmp_path, monkeypatch):
    """命中条目含抽取图时附「含图 N 张」提示与 docx_image_insert 指引；无图条目不带。"""
    _setup(tmp_path, monkeypatch)
    _seed("# 证书\n\n信息安全管理体系认证证书 ISO27001，编号 CN-001。", "ISO证书.txt",
          "qualification_certificate")
    _seed("# 证书\n\n张三持有 PMP 项目管理专业人士资格认证证书。", "pm.txt",
          "personnel_certificate")
    # 造抽取图（清单=listdir，无 DB 记录）
    img_dir = store.kb_images_dir("ISO证书.txt")
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "img_001.png").write_bytes(b"\x89PNG-fake")

    out = search_company_assets.invoke({"query": "ISO27001"})
    assert "公司资料命中" in out
    assert "含图 1 张" in out
    assert "docx_image_insert" in out
    assert "knowledge/parse/ISO证书/images/img_001.png" in out

    # 无图条目命中不带图片提示
    out2 = search_company_assets.invoke({"query": "PMP"})
    assert "公司资料命中" in out2
    assert "含图" not in out2
