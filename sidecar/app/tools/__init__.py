"""Agent 工具包。"""

from .ask_human import ask_human
from .assemble_tender import assemble_tender
from .check_pipeline import check_pipeline_state
from .check_residue import check_name_residue
from .docx_ops import (
    docx_assemble_volume,
    docx_comment_add,
    docx_diagram_insert,
    docx_html_figure,
    docx_image_insert,
    docx_material_inject,
    docx_section_create,
    docx_section_read,
    docx_section_revise,
    docx_source_inject,
)
from .parse_document import parse_document
from .publish import publish_artifact
from .read import read_artifact
from .search_knowledge import search_company_assets, search_references
from .task_progress import update_task_progress
from .templates import list_templates
from .validate_analysis import validate_analysis
from .validate_body import validate_body
from .web_fetch import fetch_url

TOOLS = [
    parse_document,
    assemble_tender,
    ask_human,
    publish_artifact,
    read_artifact,
    search_company_assets,
    search_references,
    check_name_residue,
    check_pipeline_state,
    validate_analysis,
    validate_body,
    update_task_progress,
    fetch_url,
    list_templates,
    docx_section_create,
    docx_section_read,
    docx_material_inject,
    docx_source_inject,
    docx_image_insert,
    docx_comment_add,
    docx_diagram_insert,
    docx_html_figure,
    docx_section_revise,
    docx_assemble_volume,
]
