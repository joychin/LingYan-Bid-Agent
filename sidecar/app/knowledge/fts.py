"""FTS5 中文检索：jieba 写入/查询两侧同源分词 + 中文 bigram 补充。

unicode61 对连续 CJK 当单 token（整句 miss），jieba 两侧同源解决「相同词」命中；
但 jieba 可能把「资质证书」切成整词，查询「证书」（子串）仍 miss——写入侧对每个
中文 token 追加相邻 2-gram，保证任意两字词可命中（代价：body 约两倍膨胀，可接受）。
"""

from __future__ import annotations

import re

import jieba

# jieba 首次调用加载词典（约 0.5s），线程安全全局共享
_TOKEN_SAFE = re.compile(r"[\w\u4e00-\u9fff]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def _bigrams(word: str) -> list[str]:
    """中文 token 的相邻二字滑窗（len>=3 的词才需要；两字词自身即 bigram）。"""
    if len(word) < 3 or not _CJK.fullmatch(word):
        return []
    return [word[i : i + 2] for i in range(len(word) - 1)]


def segment_for_fts(text: str) -> str:
    """jieba 精确模式分词 + 中文 bigram，空格分隔（写入与查询共用）。"""
    if not text:
        return ""
    tokens: list[str] = []
    for w in jieba.cut(text, cut_all=False):
        w = w.strip()
        if not w:
            continue
        tokens.append(w)
        tokens.extend(_bigrams(w))
    return " ".join(tokens)


def build_match_expr(query: str) -> str | None:
    """查询 → FTS5 MATCH 表达式（token OR 连接，宽松召回；token 只留安全字符防语法注入）。"""
    tokens = _TOKEN_SAFE.findall(query or "")
    # jieba 切词后再过滤一次（中文词保留、标点丢弃）；英文数字 token 原样
    words: list[str] = []
    for tk in tokens:
        for w in jieba.cut(tk, cut_all=False):
            w = w.strip()
            if w and _TOKEN_SAFE.fullmatch(w):
                words.append(w)
    uniq = list(dict.fromkeys(words))
    if not uniq:
        return None
    return " OR ".join(f'"{w}"' for w in uniq)
