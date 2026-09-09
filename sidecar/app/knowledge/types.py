"""知识库类型注册表（平台封闭注册，真值只在 sidecar，前端只做映射展示）。

类型是整条知识库的**唯一策略源**（v3，2026-09-03 内容角色模型；2026-09-04 章节块重构）：
- role = fact（证明我们有什么/做过什么）/ writing（这类内容怎么写）——浏览分组与
  检索加权的语义；**废除 v2 的 bucket**，角色由类型派生，不再独立存储。
- 章节块策略由 role 直接驱动（builds_chapters）：writing 类自动构建章节块
  （素材库=章节块集合），fact 类不构建（价值在字段+内容说明，靠检索问答消费）。
- time_fields = 时间字段锚点（机器消费的最小结构化集——freshness 计算依据）；
  其余内容一律不预设字段，由 LLM 自由提取进「内容说明 statement」（带出处锚点）。

类型清单不进表结构（kb_items.doc_type 存 code），加类型零迁移。
hint 注册序即优先级：reference 两类排在 technical_doc 前（「技术方案模板.docx」
应命中参考资料而非技术方案）；contract_case 的「合同」在 past_proposal 之前。
"""

from __future__ import annotations

from dataclasses import dataclass

# 字段 code → 中文标签。两族：时间锚点（freshness 计算）+ 身份锚点（project_name/
# client——章节卡的来源标注、关联证明材料匹配、旧名残留扫描都机械依赖它们）。
# 其余内容不预设，由 LLM 自由提取进「内容说明 statement」（带出处锚点）。
FIELD_LABELS: dict[str, str] = {
    "valid_from": "有效期自 / 发证日期",
    "valid_until": "有效期至",
    "sign_date": "签订 / 验收日期",
    "period": "年度",
    "doc_date": "落款 / 编制日期",
    "project_name": "项目名称",
    "client": "甲方 / 客户",
}

ROLE_FACT = "fact"
ROLE_WRITING = "writing"
ROLE_LABELS: dict[str, str] = {ROLE_FACT: "事实类资料", ROLE_WRITING: "写法类资料"}


@dataclass(frozen=True)
class KbDocType:
    code: str
    name: str
    time_fields: list[str]  # 时间锚点（FIELD_LABELS 的 key 子集）
    filename_hints: list[str]  # 文件名关键词（抽取 prompt 的强提示，非硬规则）
    role: str = ROLE_FACT


_TYPES = [
    KbDocType(
        "business_license", "营业执照",
        ["valid_from", "valid_until"],
        ["营业执照", "三证"],
    ),
    KbDocType(
        "qualification_certificate", "资质 / 体系证书",
        ["valid_from", "valid_until"],
        ["证书", "资质", "ISO", "CMMI", "认证", "许可证"],
    ),
    KbDocType(
        "personnel_certificate", "人员证书",
        ["valid_until"],
        ["人员", "项目经理", "职称", "从业资格", "安全员", "建造师"],
    ),
    KbDocType(
        "contract_case", "合同 / 业绩案例",
        ["sign_date"],
        ["合同", "业绩", "案例", "订单", "中标"],
    ),
    KbDocType(
        "acceptance_report", "验收报告",
        ["sign_date"],
        ["验收"],
    ),
    KbDocType(
        "financial_report", "财务 / 审计报告",
        ["period"],
        ["审计", "财报", "财务报表", "决算"],
    ),
    KbDocType(
        # 投标高频件（2026-09-08 补）：此前无归属类型落 other、不参与时效锚点
        "social_security", "社保缴纳证明",
        ["period"],
        ["社保", "参保", "缴纳证明"],
    ),
    KbDocType(
        "company_profile", "公司介绍",
        [],
        ["简介", "介绍", "宣传册"],
    ),
    KbDocType(
        "honor_ip", "荣誉 / 知识产权",
        ["valid_from"],
        ["奖", "荣誉", "专利", "软著", "著作权", "商标"],
    ),
    KbDocType(
        "past_proposal", "历史标书 / 投标文件",
        ["sign_date"],
        ["标书", "投标", "响应文件", "投标文件", "应答文件", "资信"],
        role=ROLE_WRITING,
    ),
    KbDocType(
        "reference_doc", "参考资料 / 模板范文",
        ["doc_date"],
        ["模板", "范文", "范本", "参考"],
        role=ROLE_WRITING,
    ),
    KbDocType(
        "technical_doc", "技术方案 / 白皮书",
        ["doc_date"],
        ["方案", "白皮书", "说明书", "技术"],
        role=ROLE_WRITING,
    ),
    KbDocType(
        "other", "其他",
        [],
        [],
    ),
]

TYPES: dict[str, KbDocType] = {t.code: t for t in _TYPES}


def get_type(code: str | None) -> KbDocType | None:
    return TYPES.get(code or "")


def type_name(code: str | None) -> str:
    t = get_type(code)
    return t.name if t else (code or "其他")


def role_of(code: str | None) -> str:
    """类型 → 内容角色；未判定（None）归事实类兜底（fact 是默认世界）。"""
    t = get_type(code)
    return t.role if t else ROLE_FACT


def builds_chapters(code: str | None) -> bool:
    """是否构建章节块：仅写法类（素材库=章节块集合；事实类靠字段+说明检索）。"""
    return role_of(code) == ROLE_WRITING


def guess_type_by_filename(filename: str) -> str | None:
    """文件名关键词 → 类型 code（规则预处理，作为 LLM 判定的强提示；不命中返回 None）。"""
    name = filename.lower()
    for t in _TYPES:
        for hint in t.filename_hints:
            if hint.lower() in name:
                return t.code
    return None


# 标签 → code 反向映射（LLM 历史输出可能用中文标签做键，读取/落库前归一）
_LABEL_TO_CODE: dict[str, str] = {v: k for k, v in FIELD_LABELS.items()}


def normalize_field_keys(fields: dict) -> dict:
    """字段键归一：中文标签键换成注册 code；已是 code 或映射不到的自由键原样保留。"""
    return {_LABEL_TO_CODE.get(k, k): v for k, v in fields.items()}


def types_payload() -> list[dict]:
    """给前端分组/下拉用（GET /api/kb/types）。"""
    return [
        {
            "code": t.code, "name": t.name,
            "role": t.role,
            "time_fields": t.time_fields,
        }
        for t in _TYPES
    ]
