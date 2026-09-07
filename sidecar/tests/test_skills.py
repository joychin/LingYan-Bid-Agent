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
    """tender-body 开工纪律锚点：指引确认门+承诺拍板、素材先行、并发派发必带清单。"""
    text = (skills_source_dir() / "tender-body" / "SKILL.md").read_text(encoding="utf-8")
    for kw in ("写作指引", "关键事实与承诺", "素材先行", "block_ids", "待补", "待澄清",
               "validate_body", "guide_path", "tender-body-writer", "兄弟节开头摘要",
               "不传就会编", "只重写我指定的章节", "共享\n  内容在前、节差异在后"):
        assert kw in text, f"tender-body/SKILL.md 缺少开工纪律关键词：{kw}"
