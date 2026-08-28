"""中文编号标题识别：docx 无样式兜底与 pdf 无书签兜底共用。

标题文字印在原文行上（「第X章…」「一、…」「（一）…」），识别结果是
**可回原文验证的**——这是与已删除的字号判级（纯猜测、不可验证）的本质区别。
"""

from __future__ import annotations

import re

_CN_NUM = "一二三四五六七八九十百千零〇两"
HEADING_L1_RE = re.compile(rf"^第[{_CN_NUM}0-9]{{1,8}}(?:[章节篇]|部分)")
HEADING_L2_RE = re.compile(rf"^[{_CN_NUM}]{{1,6}}、")
HEADING_L3_RE = re.compile(rf"^[（(][{_CN_NUM}0-9]{{1,8}}[)）]")
# 整行只有章节号前缀（「第一章」「第三部分」单独成行，标题文字在下一行——
# 真实语料常见形态）；目录条目与正文标题拆行识别共用
LONE_PREFIX_RE = re.compile(rf"^第[{_CN_NUM}0-9]{{1,8}}(?:[章节篇]|部分)$")


def numbered_heading_level(text: str) -> int:
    """第X章→L1 / 一、→L2 /（一）→L3。

    行长 ≤60、不以句读结尾、**句读不出现在行中**——正则是前缀匹配，
    「第三章评标办法规定…」这类以编号开头的正文句子必须排除（标题不含
    逗号句号分号；顿号「、」常见于标题，不算句读）。"""
    if len(text) > 60 or text.endswith(("。", "；", "，", "：", ",", ";")):
        return 0
    if any(p in text for p in ("，", "。", ";", "；")):
        return 0
    if HEADING_L1_RE.match(text):
        return 1
    if HEADING_L2_RE.match(text):
        return 2
    if HEADING_L3_RE.match(text):
        return 3
    return 0
