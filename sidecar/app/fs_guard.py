"""Agent 文件工具写保护（2026-08-29 产物体系修订 P0.3）。

FilesystemBackend 的 root 是整个 workspace，通用 write_file/edit_file 工具
理论上可以直改产物包内部（formal/*/current/content.json、manifest、恢复点、
threads/*/art_*、archive、skills），绕过 schema 校验、content_seq、恢复点与
「正式稿只能由用户转正写入」的边界。GuardedBackend 用**写路径黑名单**堵住
这一层：命中即返回 Result(error=...)，deepagents 会把它转成错误 ToolMessage，
不打崩 run（工具失败返回错误字符串的仓内铁则）。

边界（方案 v2 定稿）：
- 只拦写（write/edit/delete）；read/ls/grep/glob 完全放开——tender-analysis
  的导航硬纪律依赖 read_file 读解析大纲，一刀切会打断流水线；
- out/（任务工作台）与 drafts/（发布草稿区）正常可写；
- skills/ 拦写的额外理由：技能目录每次启动从 app/skills/ 同步覆盖，模型写入
  会被静默冲掉，属于必丢数据的路径。
"""

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import DeleteResult, EditResult, WriteResult

_WRITE_DENY_NOTE = (
    "该路径属于产物包保护区（正式稿/会话产物/归档/技能目录），"
    "不能用文件工具直接写入：产物请通过 read_artifact 读取、publish_artifact 发布；"
    "普通文件请写入当前任务的工作台或草稿目录。"
)

# 拒写的顶层目录段（workspace 根下任意深度命中即拒：formal/threads 在任务目录内）
_DENY_SEGMENTS = frozenset({"formal", "archive", "skills"})


def _is_protected(rel_parts: tuple[str, ...]) -> bool:
    """判断相对 workspace 的路径段是否在写保护黑名单。

    - formal/<task>/...、archive/<task>/...、skills/...：段级命中即拒
    - threads/<conv>/art_<id>/...：会话产物包目录拒（threads 下未来可能的
      scratch 等非包路径不拦，保留扩展空间）
    """
    for i, seg in enumerate(rel_parts):
        if seg in _DENY_SEGMENTS:
            return True
        if seg == "threads":
            rest = rel_parts[i + 2 :]  # i+1 是会话 id
            if any(s.startswith("art_") for s in rest):
                return True
    return False


class GuardedBackend(FilesystemBackend):
    """FilesystemBackend + 写路径黑名单：产物包内部对文件工具只读。"""

    def _deny(self, file_path: str) -> tuple[str, ...] | None:
        try:
            resolved = self._resolve_path(file_path)
        except (OSError, RuntimeError):
            return None  # 解析失败交给父类返回标准错误
        rel = resolved.relative_to(self.cwd)
        if _is_protected(rel.parts):
            return rel.parts
        return None

    def write(self, file_path: str, content: str) -> WriteResult:
        if self._deny(file_path) is not None:
            return WriteResult(error=f"[写入被拒绝] {file_path}：{_WRITE_DENY_NOTE}")
        return super().write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002
    ) -> EditResult:
        if self._deny(file_path) is not None:
            return EditResult(error=f"[写入被拒绝] {file_path}：{_WRITE_DENY_NOTE}")
        return super().edit(file_path, old_string, new_string, replace_all=replace_all)

    def delete(self, file_path: str) -> DeleteResult:
        if self._deny(file_path) is not None:
            return DeleteResult(error=f"[写入被拒绝] {file_path}：{_WRITE_DENY_NOTE}")
        return super().delete(file_path)
