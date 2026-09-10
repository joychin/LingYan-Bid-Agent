#!/usr/bin/env python3
"""按 index.html 里的 H1/H2/H3 标题用字，把 Noto Serif CJK SC Regular
子集化为自托管 woff2。改了标题文案后重跑。

必须用含中文字形的 CJK 字体（Noto Serif SC / 思源宋体）——纯拉丁衬线
（如 Source Serif 4）会让标题里「英文走 A 字体、中文走 B 字体」基线不齐。
源字体：https://github.com/notofonts/noto-cjk — SIL OFL 1.1
"""
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
OUT = ROOT / "assets" / "fonts" / "display-serif.woff2"

PATTERNS = [
    r"<h1[^>]*>(?P<t>.*?)</h1>",
    r"<h2[^>]*>(?P<t>.*?)</h2>",
    r"<h3[^>]*>(?P<t>.*?)</h3>",
]
# 兜底常用标点
EXTRA = "，。？！：；、「」·—…（）+%|/0123456789 AaBbCcDdEeRrNnPpMmQqSsTtVvWwXxIiOoUuYy "


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("用法: make_font_subset.py <SourceSerif4-Regular.ttf>")
    src = pathlib.Path(sys.argv[1])

    html = HTML.read_text(encoding="utf-8")
    chars = set(EXTRA)
    for pat in PATTERNS:
        for m in re.finditer(pat, html, re.S):
            text = re.sub(r"<[^>]+>", "", m.group("t"))
            text = text.replace("&nbsp;", " ").replace("&amp;", "&")
            chars.update(text)
    text = "".join(sorted(c for c in chars if not c.isspace() or c == " "))
    print(f"标题用字 {len(text)} 个")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(text)
        chars_file = f.name

    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable, "-m", "fontTools.subset", str(src),
            f"--text-file={chars_file}",
            "--flavor=woff2",
            f"--output-file={OUT}",
            "--layout-features=*",
            "--no-hinting",
            "--desubroutinize",
        ],
        check=True,
    )
    size = OUT.stat().st_size
    print(f"✓ 已生成 {OUT}（{size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
