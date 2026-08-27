"""Agent 工具包。"""

from .assemble_tender import assemble_tender
from .ask_human import ask_human
from .parse_document import parse_document
from .publish import publish_artifact
from .read import read_artifact
from .search_knowledge import search_knowledge
from .task_progress import update_task_progress
from .web_fetch import fetch_url

TOOLS = [
    parse_document,
    assemble_tender,
    ask_human,
    publish_artifact,
    read_artifact,
    search_knowledge,
    update_task_progress,
    fetch_url,
]
