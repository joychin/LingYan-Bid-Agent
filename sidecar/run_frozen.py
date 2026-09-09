"""PyInstaller 冻结入口（仅打包产物使用，日常开发走 `python -m app.main`）。

app/main.py 全是相对导入（`from . import config`），PyInstaller 把入口脚本按顶层
脚本分析，相对导入在冻结环境运行时必炸（no known parent package）——此 wrapper 以
常规导入拿 main() 再转调，顺带避免 `python -m app.main` 下模块以 __main__ 与
app.main 两个名字各执行一次的副作用（main.py 日志幂等守卫注释的教训）。

自检：`run_frozen.py --smoke` 逐个导入高风险依赖并触发其数据文件加载，供打包后
冻结产物冒烟（打包收集是否齐全以实测为准，不信任静态承诺）。
"""

import json
import sys


def _smoke() -> int:
    checks: dict[str, str] = {}

    def check(name: str, fn) -> None:
        try:
            checks[name] = fn()
        except Exception as e:  # noqa: BLE001 - 冒烟要把每项失败原因都带出来
            checks[name] = f"FAIL: {type(e).__name__}: {e}"

    check("pymupdf", lambda: __import__("pymupdf").__version__)

    def _jieba() -> str:
        import jieba

        return f"{len(list(jieba.cut('知识库检索冒烟测试')))} tokens"

    check("jieba(dict.txt)", _jieba)

    def _fts5() -> str:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE smoke USING fts5(x)")
        return "fts5 ok"

    check("sqlite3(FTS5)", _fts5)

    def _trafilatura() -> str:
        import trafilatura

        # 无网络抽取：走 settings 加载 + html→文本管线
        text = trafilatura.extract("<html><body><p>冒烟文本</p></body></html>")
        return "extract ok" if text and "冒烟" in text else f"unexpected: {text!r}"

    check("trafilatura(settings.cfg)", _trafilatura)

    def _docx() -> str:
        import docx

        docx.Document()  # 包内默认模板可加载（漏收集 = 建文档即炸）
        return f"{getattr(docx, '__version__', '?')} default.docx ok"

    check("python-docx(default.docx)", _docx)

    def _base_template() -> str:
        # 基准版式模板是唯一「漏收集不崩溃、只静默退化为英文默认版式」的 datas 项
        # （spec 注释原文），静默退化型必须靠冒烟断言盯住
        from app.tools.docx_ops import _BASE_TEMPLATE

        if not _BASE_TEMPLATE.is_file():
            raise FileNotFoundError(f"基准版式模板缺失: {_BASE_TEMPLATE}")
        return f"{_BASE_TEMPLATE.name} ok"

    check("app/resources 模板", _base_template)

    def _openai() -> str:
        # 触发 _resources_proxy 的字符串 import_module("openai.resources") 懒代理
        from openai.resources import chat  # noqa: F401

        return f"{__import__('openai').__version__} resources ok"

    check("openai(lazy resources)", _openai)

    def _agent_stack() -> str:
        import deepagents  # noqa: F401
        import langchain_core  # noqa: F401
        import langchain_openai  # noqa: F401
        from langchain_deepseek import ChatDeepSeek  # noqa: F401
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401

        return "deepagents/langchain/langgraph ok"

    check("agent stack", _agent_stack)

    def _server_stack() -> str:
        import fastapi  # noqa: F401
        import sse_starlette  # noqa: F401
        import uvicorn  # noqa: F401
        from uvicorn.protocols.http.auto import AutoHTTPProtocol  # noqa: F401

        return "fastapi/uvicorn/sse ok"

    check("server stack", _server_stack)

    check("app.main", lambda: "fastapi app ok" if __import__("app.main").main.app else "empty")

    failed = {k: v for k, v in checks.items() if str(v).startswith("FAIL")}
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    # Windows 的 stdout/stderr 默认走 locale 编码（cp1252），冒烟门的 json 中文
    # 输出在冻结环境必炸（mac/Linux 默认 UTF-8 无此问题）——统一切 UTF-8，
    # errors=replace 兜底个别库写出的极端字符。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # 无 reconfigure 的极旧 Python 维持原状

    if "--smoke" in sys.argv:
        sys.exit(_smoke())
    from app.main import main

    main()
