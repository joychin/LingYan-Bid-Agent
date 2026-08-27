"""知识库条目类型注册表（平台封闭注册，真值只在 sidecar，前端只做映射展示）。

类型的作用：检索过滤 + 抽取字段模板 + 确认表单预填。类型清单不进表结构
（kb_items.doc_type 存 code，字段全收 JSON 列），加类型零迁移。

三层模型的轻量版：类型（本表封闭）+ 每类少量字段模板 + 开放自由字段兜底
（LLM 可输出模板外的字段，表单照常展示）。
"""

from __future__ import annotations

from dataclasses import dataclass

# 字段 code → 中文标签（表单展示与抽取 prompt 共用）
FIELD_LABELS: dict[str, str] = {
    "company_name": "单位名称",
    "uscc": "统一社会信用代码",
    "legal_rep": "法定代表人",
    "valid_from": "有效期自 / 发证日期",
    "valid_until": "有效期至",
    "cert_name": "证书 / 文件名称",
    "cert_no": "证书编号",
    "issuer": "发证 / 出具机构",
    "person_name": "姓名",
    "project_name": "项目名称",
    "client": "甲方 / 客户",
    "amount": "金额",
    "sign_date": "签订 / 验收日期",
    "period": "年度",
    "title": "名称",
    "ip_type": "类型",
}


@dataclass(frozen=True)
class KbDocType:
    code: str
    name: str
    fields: list[str]  # 字段模板（FIELD_LABELS 的 key）
    filename_hints: list[str]  # 文件名关键词（规则预处理强提示，加速/纠偏 LLM）


_TYPES = [
    KbDocType(
        "business_license", "营业执照",
        ["company_name", "uscc", "legal_rep", "valid_from", "valid_until"],
        ["营业执照", "三证"],
    ),
    KbDocType(
        "qualification_certificate", "资质 / 体系证书",
        ["cert_name", "cert_no", "issuer", "valid_from", "valid_until"],
        ["证书", "资质", "ISO", "CMMI", "认证", "许可证"],
    ),
    KbDocType(
        "personnel_certificate", "人员证书",
        ["person_name", "cert_name", "cert_no", "valid_until", "issuer"],
        ["人员", "项目经理", "职称", "从业资格", "安全员", "建造师"],
    ),
    KbDocType(
        "contract_case", "合同 / 业绩案例",
        ["project_name", "client", "amount", "sign_date"],
        ["合同", "业绩", "案例", "订单", "中标"],
    ),
    KbDocType(
        "acceptance_report", "验收报告",
        ["project_name", "client", "sign_date"],
        ["验收"],
    ),
    KbDocType(
        "financial_report", "财务 / 审计报告",
        ["company_name", "period", "issuer"],
        ["审计", "财报", "财务报表", "决算"],
    ),
    KbDocType(
        "company_profile", "公司介绍",
        ["company_name"],
        ["简介", "介绍", "宣传册"],
    ),
    KbDocType(
        "technical_doc", "技术方案 / 白皮书",
        ["title"],
        ["方案", "白皮书", "说明书", "技术"],
    ),
    KbDocType(
        "honor_ip", "荣誉 / 知识产权",
        ["title", "ip_type", "issuer", "valid_from"],
        ["奖", "荣誉", "专利", "软著", "著作权", "商标"],
    ),
    KbDocType(
        "other", "其他",
        ["title"],
        [],
    ),
]

TYPES: dict[str, KbDocType] = {t.code: t for t in _TYPES}


def get_type(code: str | None) -> KbDocType | None:
    return TYPES.get(code or "")


def type_name(code: str | None) -> str:
    t = get_type(code)
    return t.name if t else (code or "其他")


def guess_type_by_filename(filename: str) -> str | None:
    """文件名关键词 → 类型 code（规则预处理，作为 LLM 抽取的强提示；不命中返回 None）。"""
    name = filename.lower()
    for t in _TYPES:
        for hint in t.filename_hints:
            if hint.lower() in name:
                return t.code
    return None


# 标签 → code 反向映射（LLM 历史输出可能用中文标签做键，读取/落库前归一）
_LABEL_TO_CODE: dict[str, str] = {v: k for k, v in FIELD_LABELS.items()}


def normalize_field_keys(fields: dict) -> dict:
    """字段键归一：中文标签键换成注册 code；已是 code 或映射不到的自由键原样保留。

    早期 prompt 只给过中文标签，存量 suggested/business 可能是标签键——归一后
    前端「模板 code ∪ 已有值键」合并才不会渲染出两个同名输入框。
    """
    return {_LABEL_TO_CODE.get(k, k): v for k, v in fields.items()}


def types_payload() -> list[dict]:
    """给前端下拉/分组用（GET /api/kb/types）。"""
    return [
        {"code": t.code, "name": t.name, "fields": t.fields} for t in _TYPES
    ]


# ---------------------------------------------------------------------------
# 元数据抽取 prompt（文本管线：docx / 文本 PDF / VL 转写后的 md 共用一条）
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM = "你是投标资料管理员，负责从公司资料文本中识别文档类型并抽取关键字段。只输出 JSON。"

_EXTRACT_TMPL = """请阅读以下资料文本，判断文档类型并抽取字段。

## 预置类型（doc_type 必须从中选一个 code，禁止编造）
{type_list}

## 字段模板（所选类型优先抽这些字段；有价值的模板外字段也可放进 extra）
{field_list}

## 规则
1. 只依据文本中真实出现的内容，禁止推测编造；认不出的字段不输出（不要输出空值）
2. fields 的键必须使用字段模板列出的英文 code（如 company_name），禁止用中文标签做键
3. extra 的键用简短中文标签（如「履约情况」「项目内容」）——它是自由字段，中文键可直接在确认表单展示
4. 每个字段给 source 出处（如 "p:1" 表示第 1 页、"L12" 表示 markdown 第 12 行、或直接引用原文片段）
5. confidence 为你对类型判断的把握（0~1）
6. 文件名提示：{filename_hint}
7. 只输出一个 JSON 对象，不要 markdown 代码块包裹，格式：
{{"doc_type": "<code>", "confidence": <0~1>, "fields": {{"<字段code>": {{"value": "...", "source": "..."}}}}, "extra": {{"<中文标签>": {{"value": "...", "source": "..."}}}}, "summary": "一句话概括这份材料"}}

## 资料文本（文件名：{filename}）
{body}"""


def build_extract_prompt(filename: str, md_text: str, *, max_chars: int = 16000) -> str:
    """组装抽取 prompt；长文窗口截断（头 70% + 尾 30%，证照关键信息多在头尾）。"""
    type_list = "\n".join(f"- {t.code}：{t.name}" for t in _TYPES)
    field_list = "\n".join(
        f"- {t.name}（{t.code}）：{'、'.join(f'{f}（{FIELD_LABELS.get(f, f)}）' for f in t.fields) or '（无固定字段）'}"
        for t in _TYPES
    )
    hint = guess_type_by_filename(filename)
    filename_hint = f"文件名含「{TYPES[hint].name}」相关字样，优先考虑 {hint}" if hint else "无（按内容判断）"
    if len(md_text) > max_chars:
        head = int(max_chars * 0.7)
        body = md_text[:head] + "\n\n…（中段省略）…\n\n" + md_text[-(max_chars - head):]
    else:
        body = md_text
    return _EXTRACT_TMPL.format(
        type_list=type_list,
        field_list=field_list,
        filename_hint=filename_hint,
        filename=filename,
        body=body,
    )
