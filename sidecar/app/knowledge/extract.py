"""工序③：类型判定 + 时间/身份字段 + 内容说明（一次 LLM 调用三合一，v3）。

设计要点：
- 不预设内容字段。机器消费的最小集保持结构化——时间锚点（freshness 计算）+
  身份锚点 project_name/client（来源标注/关联核对/残留扫描）；其余关键内容由
  LLM 自由提取进「内容说明 statement」，每条事实带出处锚点（第N页/LN）。
- 说明进检索索引（§statement 段）——事实类文件的正文常为表格/扫描，说明段是
  语义密度最高的可检索单元；命中标「AI 整理·数字须回原文核对」。
- 检索问题（questions）进独立 §questions 段——用「用户会怎么问」的口吻补字面检索的
  措辞缺口（正文印「医院」、用户问「医疗行业项目」）；归类词必须与内容真实对应。
- 写法类（历史标书/模板/方案）说明退化为 2–3 句结构概览（写法价值在章节与素材，
  不在说明），不生成检索问题。
"""

from __future__ import annotations

import json
import re

from .types import FIELD_LABELS, TYPES, guess_type_by_filename, normalize_field_keys

EXTRACT_SYSTEM = (
    "你是投标资料管理员，负责判断资料类型、抽取时间与项目信息、整理内容说明。只输出 JSON。"
)

_MIN_STATEMENT_CHARS = 20
_MAX_QUESTIONS = 8
_MAX_QUESTION_CHARS = 30

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_JSON_RE = re.compile(r"\{.*\}", re.S)

_EXTRACT_TMPL = """请阅读以下资料文本，完成三件事：判断类型、抽取锚点字段、整理内容说明。

## 预置类型（doc_type 必须从中选一个 code，禁止编造）
{type_list}

## 锚点字段（fields；认不出的不输出，每个带 source 出处如 "第1页"/"L12"）
- 时间锚点按所选类型抽：{time_fields}
- 若文档含项目名称/客户单位，输出 project_name / client（供来源标注与核对）

## 内容说明（statement）
- 若判定为写法类（past_proposal / reference_doc / technical_doc）：写 2–3 句结构概览
  （共几章、主要主题是什么），不逐条罗列
- 其他类型：**逐条列出关键内容**（数字/金额/编号/范围/等级/意见/人数等），每条事实后
  跟（第N页）或（LN）出处；300–800 字；禁止评论、推测、编造——认不出或文中没有的不写

## 检索问题（questions）
- 若判定为写法类：questions 输出空数组，跳过本节
- 其他类型：列 3–6 个「用户检索公司资料时会问的问题」短问句（每个 ≤20 字，如
  「公司规模多大？」「持有哪些软件著作权？」「做过哪些医疗行业项目？」）——
  覆盖这份资料能回答的主要维度；问句里的行业/规模/能力等归类词必须与文中内容
  真实对应（项目是医院的才许写「医疗行业」），文中没有的不写；问句本身不带出处

## 规则
1. 只依据文本真实出现的内容；文件名提示：{filename_hint}
2. fields 键用英文 code；模板外有固定名称的关键属性放 extra（中文键，如「认证范围」）
3. 只输出一个 JSON 对象，不要 markdown 代码块包裹，格式：
{{"doc_type": "<code>", "confidence": <0~1>, "statement": "…", "questions": ["…", …],
  "fields": {{"<code>": {{"value": "…", "source": "…"}}}},
  "extra": {{"<中文键>": {{"value": "…", "source": "…"}}}}}}

## 资料文本（文件名：{filename}）
{body}"""


def build_extract_prompt(filename: str, md_text: str, *, max_chars: int = 16000) -> str:
    """组装 prompt；长文头 70% + 尾 30% 截断（证照关键信息多在头尾）。"""
    type_list = "\n".join(f"- {t.code}：{t.name}" for t in TYPES.values())
    cur = guess_type_by_filename(filename)
    from .types import get_type

    t = get_type(cur)
    time_fields = "、".join(t.time_fields) if t and t.time_fields else "（该类型无固定时间锚点，有日期类信息可放 extra）"
    hint = f"文件名含「{t.name}」相关字样，优先考虑 {cur}" if t else "无（按内容判断）"
    if len(md_text) > max_chars:
        head = int(max_chars * 0.7)
        body = md_text[:head] + "\n\n…（中段省略）…\n\n" + md_text[-(max_chars - head):]
    else:
        body = md_text
    return _EXTRACT_TMPL.format(
        type_list=type_list, time_fields=time_fields, filename_hint=hint,
        filename=filename, body=body,
    )


def _parse_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def validate_suggested(data: dict, filename: str) -> dict:
    """LLM 输出 → 规范的 suggested dict（doc_type 兜底/键归一/字段分流/说明清洗）。"""
    doc_type = data.get("doc_type")
    if doc_type not in TYPES:
        doc_type = guess_type_by_filename(filename) or "other"

    fields_raw = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    extra_raw = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    fields = normalize_field_keys(fields_raw)
    # 键分流：注册锚点留在 fields，其余挪进 extra（中文键自由区）
    extra = dict(normalize_field_keys(extra_raw))
    for k in list(fields):
        if k not in FIELD_LABELS:
            extra[k] = fields.pop(k)
    fields = {
        k: v for k, v in fields.items()
        if isinstance(v, dict) and isinstance(v.get("value"), str) and v["value"].strip()
    }
    extra = {
        k: v for k, v in extra.items()
        if isinstance(v, dict) and isinstance(v.get("value"), str) and v["value"].strip()
    }

    statement = data.get("statement")
    statement = statement.strip() if isinstance(statement, str) else ""
    t = TYPES[doc_type]
    if t.role == "writing" or len(statement) < _MIN_STATEMENT_CHARS:
        # 写法类不需要长说明；事实类过短说明视为无效（宁缺毋滥，不产生空说明段）
        if t.role == "writing" and statement:
            statement = statement[:500]
        elif len(statement) < _MIN_STATEMENT_CHARS:
            statement = ""

    # 检索问题：写法类不生成（检索消费方是素材库）；去空/去重/超长丢弃，宁缺毋滥
    questions: list[str] = []
    if t.role != "writing" and isinstance(data.get("questions"), list):
        for q in data["questions"]:
            if not isinstance(q, str):
                continue
            q = q.strip()
            if q and len(q) <= _MAX_QUESTION_CHARS and q not in questions:
                questions.append(q)
            if len(questions) >= _MAX_QUESTIONS:
                break

    confidence = data.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    out = {"doc_type": doc_type, "fields": fields, "extra": extra}
    if statement:
        out["statement"] = statement
    if questions:
        out["questions"] = questions
    if confidence is not None:
        out["confidence"] = confidence
    return out


def run_extract(api_key: str, profile, filename: str, md_text: str) -> dict | None:
    """调 LLM 跑三合一抽取；返回规范 suggested dict，失败/不可解析返回 None。"""
    from langchain_deepseek import ChatDeepSeek

    model = ChatDeepSeek(api_key=api_key, base_url=profile.base_url, model=profile.model, timeout=90)
    resp = model.invoke([("system", EXTRACT_SYSTEM), ("user", build_extract_prompt(filename, md_text))])
    raw = getattr(resp, "content", "")
    if isinstance(raw, list):
        raw = "".join(x.get("text", "") or "" for x in raw if isinstance(x, dict))
    data = _parse_json(raw)
    if data is None:
        return None
    return validate_suggested(data, filename)
