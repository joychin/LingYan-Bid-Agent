"""知识库入库管线：txt 真解析 + mock LLM 抽取全流程、图片 VL 降级、确认不被覆盖、重触发。"""

import json

from app import db
from app.knowledge import store
from app.knowledge.ingest import run_ingest
from tests.util import init_env


class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """返回固定 suggested_metadata JSON 的假 ChatDeepSeek。"""

    last_prompt = None

    def __init__(self, **kwargs):
        pass

    def invoke(self, messages):
        last = messages[-1]
        _FakeLLM.last_prompt = last[1] if isinstance(last, tuple) else last.content
        return _FakeResp(
            json.dumps(
                {
                    "doc_type": "qualification_certificate",
                    "confidence": 0.9,
                    "fields": {"cert_name": {"value": "ISO9001 质量管理体系认证", "source": "L1"}},
                    "summary": "ISO9001 证书",
                },
                ensure_ascii=False,
            )
        )


def _setup(tmp_path, monkeypatch, with_llm=True):
    init_env(tmp_path, monkeypatch)
    store.ensure_dirs()
    if with_llm:
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        import langchain_deepseek

        monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", _FakeLLM)


def _upload(tmp_path, name: str, content: bytes) -> str:
    src = store.kb_files_dir() / name
    src.write_bytes(content)
    import hashlib

    digest = hashlib.sha256(content).hexdigest()
    item = db.kb_insert_item(file_name=name, file_hash=digest, title=src.stem, ext=src.suffix)
    return item["id"]


def test_ingest_txt_full_pipeline(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    body = "# 资质证书\n\nXXX 公司持有的 ISO9001 质量管理体系认证证书，证书编号 CN-001，有效期至 2028 年。".encode()
    kid = _upload(tmp_path, "iso证书.txt", body)
    item = run_ingest(kid)

    assert item["parse_status"] == "ready"
    assert item["extract_status"] == "done"
    assert item["doc_type"] == "qualification_certificate"
    suggested = json.loads(item["suggested_metadata"])
    assert suggested["fields"]["cert_name"]["value"].startswith("ISO9001")
    # 产物三件套落盘
    md_path, outline_path, meta_path = store.kb_parse_paths("iso证书.txt")
    assert md_path.is_file() and outline_path.is_file() and meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["conversion"] == "txt-passthrough"
    # 检索段已建
    from app.knowledge import fts

    assert db.kb_search_segments(fts.build_match_expr("ISO9001"), limit=3)


def test_ingest_image_vlm_unavailable_degrades(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)  # VLM 未配置（env 无 VLM_*）
    kid = _upload(tmp_path, "营业执照.jpg", b"\xff\xd8\xff\xe0fakejpg")
    # 预置历史 0 字节 md（旧版本会落空 md），验证重新识别能自愈清掉
    md_path, _, meta_path = store.kb_parse_paths("营业执照.jpg")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("", encoding="utf-8")
    item = run_ingest(kid)
    # 降级：原件收下、parse ready、不落 md（md_ready=false → 前端走原件预览）、抽取跳过
    assert item["parse_status"] == "ready"
    assert item["extract_status"] == "skipped"
    assert not md_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["conversion"] == "vision-unavailable"
    assert any("没有可用的图片识别模型" in w for w in meta["warnings"])
    assert (store.kb_files_dir() / "营业执照.jpg").is_file()  # 原件保留


def test_ingest_cloud_only_ext_degrades_when_unconfigured(tmp_path, monkeypatch):
    """.doc 无云端文档解析：降级为仅存档（ready + 无 md + 提示配置），不 failed。"""
    _setup(tmp_path, monkeypatch)
    kid = _upload(tmp_path, "a.doc", b"xx")
    item = run_ingest(kid)
    assert item["parse_status"] == "ready"
    md_path, _, meta_path = store.kb_parse_paths("a.doc")
    assert not md_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["conversion"] == "parse-unavailable"
    assert any("文档解析未配置" in w for w in meta["warnings"])


def test_ingest_cloud_only_ext_parses_when_configured(tmp_path, monkeypatch):
    """.doc 配了云端文档解析：走 parse_via_baidu，产出 md 可检索。"""
    _setup(tmp_path, monkeypatch)
    from app import baidu_ocr

    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")

    fake = baidu_ocr.parse.ParseResult(
        md="# 营业执照\n\n统一社会信用代码 91320XXX（云端解析结果）" * 3,
        info={"conversion": "paddleocr-vl", "pages": 1, "tables": 0},
    )
    monkeypatch.setattr(baidu_ocr, "parse_via_baidu", lambda src: fake)
    kid = _upload(tmp_path, "b.doc", b"xx")
    item = run_ingest(kid)
    assert item["parse_status"] == "ready"
    from app.knowledge import fts

    assert db.kb_search_segments(fts.build_match_expr("营业执照"), limit=3)


def test_extract_failure_does_not_block_search(tmp_path, monkeypatch):
    """LLM 抽取失败：parse ready + 检索可用 + extract failed（独立状态）。"""
    _setup(tmp_path, monkeypatch)

    class _Boom:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            raise RuntimeError("llm down")

    import langchain_deepseek

    monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", _Boom)
    kid = _upload(tmp_path, "b.txt", ("# 资料\n\n公司拥有信息安全服务资质证书与专业团队，" + "服务过多家大型客户并获得好评。" * 3).encode())
    item = run_ingest(kid)
    assert item["parse_status"] == "ready"
    assert item["extract_status"] == "failed"
    from app.knowledge import fts

    assert db.kb_search_segments(fts.build_match_expr("资质"), limit=3)


def test_no_llm_key_skips_extract(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, with_llm=False)
    kid = _upload(tmp_path, "c.txt", b"# x\n\n" + "内容".encode() * 100)
    item = run_ingest(kid)
    assert item["extract_status"] == "skipped"


def test_business_metadata_never_overwritten(tmp_path, monkeypatch):
    """确认后重触发：重抽取只覆盖 suggested，business 不动（用户确认是真值）。"""
    _setup(tmp_path, monkeypatch)
    kid = _upload(tmp_path, "d.txt", "# 证书\n\nCCC 认证证书 编号 X-1，覆盖足够长的正文内容以确保达到抽取门槛。".encode())
    run_ingest(kid)
    db.kb_update_item(
        kid,
        review_status="confirmed",
        business_metadata=json.dumps({"doc_type": "business_license", "fields": {"uscc": {"value": "MANUAL"}}}),
    )
    item = run_ingest(kid)  # 重触发
    biz = json.loads(item["business_metadata"])
    assert biz["fields"]["uscc"]["value"] == "MANUAL"
    assert item["review_status"] == "confirmed"


def test_extract_prompt_carries_filename_hint(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _upload(tmp_path, "营业执照.txt", ("# 证\n\n" + "统一社会信用代码 91110000XYZ 数据内容补齐。" * 5).encode())
    kid = [it["id"] for it in db.kb_list_items() if it["file_name"] == "营业执照.txt"][0]
    run_ingest(kid)
    assert _FakeLLM.last_prompt is not None
    assert "营业执照" in _FakeLLM.last_prompt  # 文件名提示进 prompt


def test_extract_label_keys_normalized(tmp_path, monkeypatch):
    """LLM 偶发用中文标签做键：落库前归一为注册 code（否则表单出现重复字段）。"""

    class _LabelKeyLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return _FakeResp(
                json.dumps(
                    {
                        "doc_type": "business_license",
                        "confidence": 0.9,
                        "fields": {"单位名称": {"value": "华信", "source": "L2"}},
                        "extra": {"成立时间": {"value": "2012", "source": "L3"}},
                    },
                    ensure_ascii=False,
                )
            )

    _setup(tmp_path, monkeypatch)
    import langchain_deepseek

    monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", _LabelKeyLLM)
    kid = _upload(tmp_path, "e.txt", ("# 证\n\n华信公司统一社会信用代码与基本信息的正文内容。" * 3).encode())
    item = run_ingest(kid)
    suggested = json.loads(item["suggested_metadata"])
    assert suggested["fields"] == {"company_name": {"value": "华信", "source": "L2"}}
    # 「成立时间」不在标签表（模板外自由键）——原样保留，不强行归一
    assert suggested["extra"] == {"成立时间": {"value": "2012", "source": "L3"}}
