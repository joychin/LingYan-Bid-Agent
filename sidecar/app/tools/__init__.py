"""Agent 工具包。"""

from .ask_human import ask_human
from .assemble_tender import assemble_tender
from .check_residue import check_name_residue
from .parse_document import parse_document
from .publish import publish_artifact
from .read import read_artifact
from .search_knowledge import search_company_assets, search_references
from .task_progress import update_task_progress
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
    update_task_progress,
    fetch_url,
]
