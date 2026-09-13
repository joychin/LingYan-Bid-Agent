"""整本标书契约：tender.volume / tender-volume-docx@1（文件型产物，2026-09-13）。

合册（docx_assemble_volume）产出的交付稿登记形态：包内除 content.json（机器
元信息）外还有整本 docx 本体（GET /artifacts/{aid}/file 取原始字节，前端
docx-preview 预览/下载）。发布唯一入口 = 合册工具的机械发布
（publish.publish_file_artifact）——LLM 的 staging 草稿流只走 JSON，二进制
进不去，天然防手滑。身份复用键 = 任务 + kind + display_name（册名）：多册
各一条，重合册覆盖同一条（详见 publish_file_artifact）。

cardinality 标 task-multi 但不走「恒新建」：publish_file_artifact 自带按
显示名复用的语义（publish_artifact 的 JSON 路径不碰，doc.note 行为不变）。
"""

from pydantic import BaseModel

from . import ContractDef

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TenderVolumeModel(BaseModel):
    """content.json 形状：机器元信息（前端统计行/AI read_artifact 消费）。"""

    filename: str  # 包内文件名（整本-<册名>.docx）
    book: str  # 册名（与 display_name 同值）
    size: int = 0
    # 信息性字段：zip 时间戳使重合册的二进制哈希必变，发布去重不走它
    # （走 docx 内容级比对，见 publish._zip_content_equal）
    sha256: str = ""
    merged_sections: int = 0
    images: int = 0
    comments: int = 0
    note: str = "整本为派生产物：内容修改请回节文件层改后重新合册，勿把整本当输入读回。"


TENDER_VOLUME = ContractDef(
    kind="tender.volume",
    schema_id="tender-volume-docx",
    schema_version=1,
    cardinality="task-multi",
    llm_write_mode="suggest",
    editable=False,
    default_display_name="整本标书",
    model=TenderVolumeModel,
    content_type=DOCX_MIME,
)
