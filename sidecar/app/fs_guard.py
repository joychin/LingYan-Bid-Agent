"""Agent 文件工具写保护（2026-08-29 产物体系修订 P0.3；2026-08-31 两态重构）。

FilesystemBackend 的 root 是整个 workspace，通用 write_file/edit_file 工具
理论上可以直改产物包内部（work/artifacts/*/content.json、meta.json、恢复点、
sources/、_meta/、archive、skills），绕过 schema 校验、content_seq、恢复点与
「来源只读 + 产物包对文件工具只读」的边界。GuardedBackend 用**写路径黑名单**
堵住这一层：命中即返回 Result(error=...)，deepagents 会把它转成错误 ToolMessage，
不打崩 run（工具失败返回错误字符串的仓内铁则）。

边界（两态重构定稿）：
- 只拦写（write/edit/delete）；read/ls/grep/glob 完全放开——tender-analysis
  的导航硬纪律依赖 read_file 读解析大纲，一刀切会打断流水线；
- work/ 下的过程文件（parse/analysis/outline/body）正常可写——它们是一等草稿，
  AI 自由写读；**work/artifacts/ 产物包**与 sources/（来源）、_meta/（谱系）拦写；
- **<task>/_meta/staging/ 豁免**：两步发布流的设计草稿区（publish_artifact 工具
  指示模型先把契约 JSON 写到那里、发布时移动消费）——_meta 其余路径（谱系/
  恢复点）仍拒。FilesystemBackend.write 自带 parent mkdir，无需服务端预建；
- formal/、threads/ 是 2026-08-31 前旧布局的遗留段名，同样拒写（防文档注入诱导
  模型把内容写进孤儿产物包；不做数据兼容，只堵误写）；
- 产物状态（草稿/已确认）不影响拦写口径——产物包恒对文件工具只读，写入一律走
  publish_artifact 管线（草稿发布 / 用户确认盖戳）；
- skills/ 拦写的额外理由：技能目录每次启动从 app/skills/ 同步覆盖，模型写入
  会被静默冲掉，属于必丢数据的路径。
"""

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import DeleteResult, EditResult, WriteResult

_WRITE_DENY_NOTE = (
    "该路径属于产物包保护区（来源/产物包/谱系/归档/技能目录），"
    "不能用文件工具直接写入：产物请通过 read_artifact 读取、publish_artifact 发布"
    "（发布草稿写到 <任务目录>/_meta/staging/，该目录可写）；"
    "普通工作文件请写入当前任务 work/ 下的过程目录（parse/analysis/outline/body）。"
)

# 拒写的目录段（workspace 根下任意深度命中即拒：sources/_meta/archive/skills +
# 旧布局遗留 formal/threads）。_meta 的 staging 子目录豁免（见 _is_protected）。
_DENY_SEGMENTS = frozenset({"sources", "_meta", "archive", "skills", "formal", "threads"})


def _is_protected(rel_parts: tuple[str, ...]) -> bool:
    """判断相对 workspace 的路径段是否在写保护黑名单。

    - sources/...、archive/...、skills/...、formal/...、threads/...：段级命中即拒
    - _meta/...：谱系拒，**_meta/staging/... 豁免**（两步发布流的模型草稿区）
    - work/artifacts/<aid>/...：产物包目录拒（work 下的过程文件不拦）
    """
    for i, seg in enumerate(rel_parts):
        if seg in _DENY_SEGMENTS:
            if seg == "_meta" and i + 1 < len(rel_parts) and rel_parts[i + 1] == "staging":
                continue  # <task>/_meta/staging/**：发布草稿区，模型可写
            return True
        if seg == "artifacts" and i >= 1 and rel_parts[i - 1] == "work":
            return True
    return False


class GuardedBackend(FilesystemBackend):
    """FilesystemBackend + 写路径黑名单：产物包/来源对文件工具只读。"""

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
