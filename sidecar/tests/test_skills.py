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
    assert {"document-parse", "tender-analysis", "tender-outline"} <= names


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
