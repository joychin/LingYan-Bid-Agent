"""skills 结构校验（防半接入）：frontmatter 合法 + 引用的 references 文件存在。

deepagents SkillsMiddleware 加载时对非法 frontmatter 只打 warning 并跳过，
坏 skill 会静默失效——本测试把同样规则升级为硬失败。
"""

import re
from pathlib import Path

import pytest
import yaml

from app.config import skills_source_dir

SKILLS = sorted(p for p in skills_source_dir().iterdir() if (p / "SKILL.md").is_file())
assert SKILLS, "未发现任何 skill"


def test_at_least_expected_skills():
    names = {p.name for p in SKILLS}
    assert {"document-parse", "tender-analysis", "tender-outline", "tender-body", "tender-qa",
            "humanizer-zh"} <= names


@pytest.mark.parametrize("skill_dir", SKILLS, ids=lambda p: p.name)
def test_skill_frontmatter(skill_dir: Path):
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "缺少 frontmatter（--- 包裹）"
    fm = yaml.safe_load(m.group(1))
    assert isinstance(fm, dict), "frontmatter 不是映射"
    name = fm.get("name")
    assert name == skill_dir.name, f"name({name}) 必须等于目录名({skill_dir.name})"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), "name 须为小写字母数字单连字符"
    desc = fm.get("description")
    assert isinstance(desc, str) and 0 < len(desc) <= 1024, "description 须为 1~1024 字符"


@pytest.mark.parametrize("skill_dir", SKILLS, ids=lambda p: p.name)
def test_referenced_files_exist(skill_dir: Path):
    """SKILL.md 正文里引用的 references/*.md 必须真实存在（引用丢失=方法论断链）。"""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for rel in set(re.findall(r"references/[\w.-]+\.md", text)):
        assert (skill_dir / rel).is_file(), f"SKILL.md 引用的 {rel} 不存在"


@pytest.mark.parametrize("skill_dir", SKILLS, ids=lambda p: p.name)
def test_shared_files_referenced_exist(skill_dir: Path):
    """SKILL.md 里以全路径引用的 skills/_shared/*.md 必须真实存在（evidence-rules 同
    response-guidelines，一条规则一个家）。"""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for rel in set(re.findall(r"skills/_shared/([\w.-]+\.md)", text)):
        assert (skills_source_dir() / "_shared" / rel).is_file(), (
            f"{skill_dir.name} 引用的 _shared/{rel} 不存在"
        )


GUIDELINES = skills_source_dir() / "_shared" / "response-guidelines.md"


def test_response_guidelines_shared_file_exists():
    """用户回复规范共享文件存在（唯一源；_shared/ 无 SKILL.md 不算 skill）。"""
    assert GUIDELINES.is_file(), "_shared/response-guidelines.md 不存在"


def test_response_guidelines_typography_section():
    """规范含排版章节（Markdown 环境声明 + 结构化 + 篇幅 + 禁 emoji/寒暄）。"""
    text = GUIDELINES.read_text(encoding="utf-8")
    for kw in ("## 排版", "Markdown 渲染", "结论先行", "emoji", "寒暄"):
        assert kw in text, f"response-guidelines.md 缺少排版关键词：{kw}"


def test_response_guidelines_no_fabrication_rule():
    """规范含介绍不虚构硬规则（与主 prompt 反虚构句对应的完整版）。"""
    text = GUIDELINES.read_text(encoding="utf-8")
    for kw in ("不虚构", "概括层", "改名"):
        assert kw in text, f"response-guidelines.md 缺少反虚构关键词：{kw}"


@pytest.mark.parametrize("skill_dir", SKILLS, ids=lambda p: p.name)
def test_skills_reference_response_guidelines(skill_dir: Path):
    """每个业务 skill 的 SKILL.md 都引用用户回复规范（先读规范再执行）。"""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "_shared/response-guidelines.md" in text, (
        f"{skill_dir.name} 未引用 _shared/response-guidelines.md"
    )


def test_tender_outline_unused_ids_disclosure():
    """tender-outline 第 5 步含未归位来源ID 的处置分支：归位或最终回复点名披露。

    组装器返回「未被任何目录节点引用的来源ID」时模型曾只字不提（评分项/模板
    遗漏归位用户无从知晓），此分支是披露义务的 skill 层锚点。
    """
    text = (skills_source_dir() / "tender-outline" / "SKILL.md").read_text(encoding="utf-8")
    for kw in ("未被任何目录节点引用", "重新组装", "最终回复"):
        assert kw in text, f"tender-outline/SKILL.md 缺少未归位披露分支关键词：{kw}"


def test_tender_body_kickoff_and_material_first():
    """tender-body 开工纪律锚点：两份确认件停轮汇报（2026-09-13 用户拍板弃
    ask_human 门，改为摆要点等用户输入框指示）、素材先行、派发短名+系统自动补全
    （2026-09-08 起模型罗列的必带清单改为程序拼装，见 dispatch_enrich）。"""
    text = (skills_source_dir() / "tender-body" / "SKILL.md").read_text(encoding="utf-8")
    for kw in ("写作指引", "关键事实与承诺", "素材先行", "block_ids", "待补", "待澄清",
               "validate_body", "停轮汇报指引", "停轮汇报承诺清单", "tender-body-writer",
               "兄弟节开头摘要", "由系统在派发时自动补全", "只重写我指定的章节", "封面"):
        assert kw in text, f"tender-body/SKILL.md 缺少开工纪律关键词：{kw}"
    # 弃门拍板守卫：开工两道 ask_human 门（确认指引/收承诺值）已删，正文里不再教
    # 这两处用 ask_human（第 0 步重写范围门保留，是另一码事）
    assert "ask_human 请用户确认" not in text and "ask_human 收承诺值" not in text


def test_tender_body_dispatch_grouping_discipline():
    """派发分组纪律锚点（2026-09-15 模型自主拆分批）：程序不再给均衡分波参考、
    分组归模型自主规划——数字锚点（轻节 3~5 捆/重节单独/每消息 ≤8 任务）、全覆盖
    自查、description 首行=节名清单契约。负向锚：旧「一节一个」硬规则不得回流。"""
    root = skills_source_dir() / "tender-body"
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    for kw in ("待写节清单", "3~5 个捆成一个任务", "单独成任务", "每消息 ≤8 个任务",
               "不按一级章节分批", "每一节都落进了某个任务", "逐字抄待写节清单",
               "由系统在派发时自动补全"):
        assert kw in skill, f"tender-body/SKILL.md 缺少派发分组纪律关键词：{kw}"
    assert "一节一个" not in skill, \
        "旧「一节一个」硬规则不得回流——派发分组粒度归模型（2026-09-15 拍板）"
    detail = (root / "references" / "section-writing.md").read_text(encoding="utf-8")
    for kw in ("逐节完成、全部节完成才收尾", "一节一段、一节不漏"):
        assert kw in detail, f"section-writing.md 缺少多节写手细则关键词：{kw}"


def test_tender_body_replay_reconciliation_anchor():
    """续跑对账锚点（2026-09-15 路径可靠性批）：中断落在波中间时存档整波回退，
    凭记忆重派=把写完的节整轮重写（r_eedd621716b5：59 节书派发 86 次）。纪律
    句与重派守卫（agent._ReplayGuardMiddleware）双层，此锚点防纪律句被删。"""
    text = (skills_source_dir() / "tender-body" / "SKILL.md").read_text(encoding="utf-8")
    for kw in ("断点续跑或中断后重新派发前", "对账已写节、已写的节不重派"):
        assert kw in text, f"tender-body/SKILL.md 缺少续跑对账关键词：{kw}"


def test_tender_body_material_objection_channel():
    """素材异议出口（2026-09-13）：用户手选素材与本节要求不符时，写手此前只有
    「顺从」和「沉默」两种反应（不许重检索、不许跳过注入、不许改指引、不许问人），
    没有反弹回路。现放开一条受限通道：仍照常注入改写（不动产物路径），另留一条
    「素材异议」批注 + 摘要单列，收尾逐条点名、改不改归用户拍板。
    三处必须配套（缺一处即通道断开）：写手侧规则、方法论细则、主线程收尾点名。
    """
    root = skills_source_dir() / "tender-body"
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    # 主线程收尾点名 + 素材列归用户拍板（写手无改指引权限）
    for kw in ("素材异议", "归用户拍板", "重派该节"):
        assert kw in skill, f"tender-body/SKILL.md 缺少素材异议收尾关键词：{kw}"
    detail = (root / "references" / "section-writing.md").read_text(encoding="utf-8")
    # 方法论细则：仍注入 + 批注带回（跳过=丢图丢样式，改换块=路径分叉）
    for kw in ("素材异议", "仍照常注入并改写", "docx_comment_add"):
        assert kw in detail, f"section-writing.md 缺少素材异议细则关键词：{kw}"


def test_tender_body_material_column_range_contract():
    """素材契约批（2026-09-15）锚点：块=拷贝授权范围非注入原子——同一块可派
    多个节（各写手只注入自己需要的行号区间）、同一内容区间不得进两节、
    同主题优先素材块（知识库只补证书图/核对/未覆盖事实）。旧「一块只派一节」
    教学不得回流——它就是 BPM 大块只进总体架构节、流程各节零引用的病灶。"""
    root = skills_source_dir() / "tender-body"
    guide = (root / "references" / "guide-format.md").read_text(encoding="utf-8")
    for kw in ("同一块可派多个节", "同一内容区间不得进两节", "优先素材块",
               "块大不必拆块", "docx_material_inject 传 lines"):
        assert kw in guide, f"guide-format.md 缺少素材列契约关键词：{kw}"
    assert "一块只派一节" not in guide, \
        "旧的「一块只派一节」教学不得回流——块=拷贝授权范围非注入原子"
    detail = (root / "references" / "section-writing.md").read_text(encoding="utf-8")
    for kw in ("拷贝授权范围", "blk_…:L起-L止"):
        assert kw in detail, f"section-writing.md 缺少区间自选教学关键词：{kw}"
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    assert "拷贝授权范围非注入原子" in skill, "SKILL.md 缺少注入粒度自选教学"


def test_tender_body_table_channel_teaching():
    """表格通道批（2026-09-14）教学锚点：五层教学落地——SKILL 指引期图示规划/
    第 2 步混排路由/收尾图示产出、section-writing 正向示例（模型模仿示例远胜
    遵守规则）、guide-format 图示列契约；旧「paragraphs 换行分段一次成形」的
    纯散文教学不得回流（它就是 0 自建表的抑制源）。"""
    root = skills_source_dir() / "tender-body"
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    for kw in ("图示列随模式同轮填", "不为丰富而丰富", "不进计划的能力等于不存在",
               "body 块序列（段落+表格混排", "docx_diagram_insert",
               "表格类内容不用流水句铺", "图示产出情况"):
        assert kw in skill, f"tender-body/SKILL.md 缺少表格通道教学关键词：{kw}"
    detail = (root / "references" / "section-writing.md").read_text(encoding="utf-8")
    for kw in ("body 块序列", "\"type\": \"table\"", "docx_diagram_insert",
               "kind=\"layered\"", "kind=\"gantt\"", "计划先行"):
        assert kw in detail, f"section-writing.md 缺少表格通道示例/路由关键词：{kw}"
    assert "一次成形于 `docx_section_create` 的 paragraphs（换行分段）" not in detail, \
        "旧的纯散文一次成形教学不得回流——它是模型 0 自建表的抑制源"
    guide = (root / "references" / "guide-format.md").read_text(encoding="utf-8")
    for kw in ("| 节 | 模式 | 依据 | 素材 | 图示 | 缺口/备注 |", "类型:主题",
               "docx_diagram_insert", "kind=radial", "原型（系统界面原型，docx_html_figure"):
        assert kw in guide, f"guide-format.md 缺少图示列契约关键词：{kw}"
    # 界面原型教学（2026-09-14 批二）：SKILL 路由 + 方法论写法细则
    for kw in ("docx_html_figure", "界面原型 · 示意图"):
        assert kw in skill, f"tender-body/SKILL.md 缺少界面原型教学关键词：{kw}"
    for kw in ("## 界面原型（docx_html_figure）", "全部样式内联", "禁脚本、禁外链",
               "改用文字描述界面"):
        assert kw in detail, f"section-writing.md 缺少界面原型细则关键词：{kw}"
    # 流程图（2026-09-14 批三 mermaid 消费方）：模型给 JSON 拓扑、程序转 mermaid——
    # 「模型永不手写 mermaid」的纪律锚点（错误形态：非法 spec 当场报错）
    for kw in ('kind="flow"', "程序转 mermaid 渲染", "shape=\"diamond\""):
        assert kw in detail, f"section-writing.md 缺少流程图教学关键词：{kw}"


def test_tender_body_attachment_shell_and_outline_toc_node():
    """结构缺口批（2026-09-14）锚点：①物理附件全无知识库命中→建壳节（标题+贴入
    位行+批注）——「线下准备/不建节」旧口径不得回流（营业执照废标级资格件曾在
    整本里零落点）；②tender-outline 每册树封面后必有「目录」节点（合册机械生成
    目录页、前置区不占章号）——此前 outline 无此规则、合册端支持空转，目录页
    从未产出。三处配套：SKILL 三分法、section-writing 物理附件节、guide-format
    模式列与目录行示例。
    """
    body = skills_source_dir() / "tender-body"
    skill = (body / "SKILL.md").read_text(encoding="utf-8")
    assert "全无命中→建壳节" in skill and "贴入位" in skill, \
        "tender-body/SKILL.md 三分法第三分支必须是建壳节"
    assert "不建节不派发——目录页由合册机械生成" in skill, "SKILL 缺目录节点免派发教学"
    assert "线下准备」登记到待填清单" not in skill, "旧「线下准备不建节」口径不得回流"
    detail = (body / "references" / "section-writing.md").read_text(encoding="utf-8")
    assert "全无命中 → 建壳节" in detail and "（此处贴入：XXX 复印件，加盖公章）" in detail, \
        "section-writing.md 物理附件节缺建壳节细则"
    assert "维持「线下准备」" not in detail, "旧口径不得回流"
    guide = (body / "references" / "guide-format.md").read_text(encoding="utf-8")
    assert "全无命中→建壳节+批注" in guide and "| 目录 | — |" in guide, \
        "guide-format.md 模式列三分与目录行示例缺失"
    outline = skills_source_dir() / "tender-outline"
    gen = (outline / "references" / "generate.md").read_text(encoding="utf-8")
    for kw in ("**目录页节点**", "机械\n   生成目录页", "前置区", "不占章号"):
        assert kw in gen, f"tender-outline/generate.md 缺目录页节点规则关键词：{kw}"
    oskill = (outline / "SKILL.md").read_text(encoding="utf-8")
    assert "封面后固定 `- 目录`" in oskill, "tender-outline/SKILL.md 缺目录节点提点"


def test_tender_body_contract_names_anchored():
    """body_contract 契约名 ↔ 技能教学文本锚点（2026-09-14 硬编码复核批）。

    写作指引/承诺清单/整本前缀的常量真值在 tools/body_contract.py（check_pipeline
    /validate_body/dispatch_enrich/docx_ops 逻辑点均 import 它），但 tender-body
    的 SKILL.md 与 references 以字面量教学同一名——常量改名而文档没跟，模型按
    旧名找文件、工具按新名对账，静默失配。本锚点断言常量值仍出现在教学文本：
    改名不更新文档即红（改常量时三份文档同批改）。
    """
    from app.tools import body_contract

    body = skills_source_dir() / "tender-body"
    texts = [
        (body / "SKILL.md").read_text(encoding="utf-8"),
        (body / "references" / "guide-format.md").read_text(encoding="utf-8"),
        (body / "references" / "section-writing.md").read_text(encoding="utf-8"),
    ]
    combined = "\n".join(texts)
    for token in (
        body_contract.GUIDE_NAME,
        body_contract.PROMISE_NAME,
        body_contract.VOLUME_PREFIX,
    ):
        assert token in combined, (
            f"tender-body 技能文档缺契约名「{token}」——body_contract 常量改名须同步教学文本"
        )
