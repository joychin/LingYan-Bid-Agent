"""Agent 文件工具写保护（2026-08-29 产物体系修订 P0.3；2026-08-31 两态重构）。

FilesystemBackend 的 root 是整个 workspace，通用 write_file/edit_file 工具
理论上可以直改产物包内部（work/artifacts/*/content.json、meta.json、恢复点、
sources/、_meta/、archive、skills），绕过 schema 校验、content_seq、恢复点与
「来源只读 + 产物包对文件工具只读」的边界。GuardedBackend 用**写路径黑名单**
堵住这一层：命中即返回 Result(error=...)，deepagents 会把它转成错误 ToolMessage，
不打崩 run（工具失败返回错误字符串的仓内铁则）。

边界（两态重构定稿）：
- 拦写（write/edit/delete）与拦二进制读（read，2026-09-13 事故批）；ls/grep/glob 放开——
  tender-analysis 的导航硬纪律依赖 read_file 读解析大纲，文本读语义零变化；
- 文件变更串行 + 原子落盘（2026-09-13 并发编辑事故批）：write/edit/delete 全局
  单锁互斥 + tmp+os.replace 原子替换，治「同 turn 并发编辑同文件」的丢更新与
  撕裂读（见 _WRITE_LOCK 注释），读者不上锁；
- read 的二进制/图片拦截按扩展名（图片/PDF/Office）：read_file 会把整文件 base64
  内联进消息（无分页无截断），一张扫描件≈百万 token 即顶穿模型上下文；拒绝文案
  给出正确出口（docx_image_insert / parse_document / docx_section_read）；
- work/ 下的过程文件（parse/analysis/outline/body）正常可写——它们是一等草稿，
  AI 自由写读；**work/artifacts/ 产物包**与 sources/（来源）、_meta/（谱系）拦写；
- **<task>/_meta/staging/ 豁免**：两步发布流的设计草稿区（publish_artifact 工具
  指示模型先把契约 JSON 写到那里、发布时移动消费）——_meta 其余路径（谱系/
  恢复点）仍拒。FilesystemBackend.write 自带 parent mkdir，无需服务端预建；
- formal/、threads/ 是 2026-08-31 前旧布局的遗留段名，同样拒写（防文档注入诱导
  模型把内容写进孤儿产物包；不做数据兼容，只堵误写）；
- 产物包恒对文件工具只读，写入一律走 publish_artifact 管线（单一当前版本）；
- skills/ 拦写的额外理由：技能目录每次启动从 app/skills/ 同步覆盖，模型写入
  会被静默冲掉，属于必丢数据的路径。
"""

import os
import threading
import uuid
from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import DeleteResult, EditResult, ReadResult, WriteResult
from deepagents.backends.utils import perform_string_replacement

_WRITE_DENY_NOTE = (
    "该路径属于产物包保护区（来源/产物包/谱系/归档/技能目录），"
    "不能用文件工具直接写入：产物请通过 read_artifact 读取、publish_artifact 发布"
    "（发布草稿写到 <任务目录>/_meta/staging/，该目录可写）；"
    "普通工作文件请写入当前任务 work/ 下的过程目录（parse/analysis/outline/body）。"
)

# 拒写的目录段（workspace 根下任意深度命中即拒：sources/_meta/archive/skills +
# 旧布局遗留 formal/threads）。_meta 的 staging 子目录豁免（见 _is_protected）。
_DENY_SEGMENTS = frozenset({"sources", "_meta", "archive", "skills", "formal", "threads"})

# 二进制/图片读拦截（2026-09-13 事故批）。read_file 对非文本文件会把**整个文件
# base64 内联进消息**——无分页、无截断，一张扫描件 ≈ 百万 token，单次读即可把
# 子代理上下文顶穿模型上限（实测 1,565,843 字符 base64 → 1,113,773 token 请求），
# 且压缩自愈数学上救不了：巨型内容是最新一条消息，摘要只逐出旧消息。
# 事故链=并行 docx 写坏节文件 → 写手 read_file 读证书 PNG「看一眼」→ 上下文死亡。
# 出口：图片贴正文唯一通道=docx_image_insert（自读文件不经此层）；文本一律先解析。
_IMAGE_READ_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic", ".heif"})
_PDF_READ_SUFFIXES = frozenset({".pdf"})
_OFFICE_READ_SUFFIXES = frozenset({".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".xlsm"})

# ---------- 文件变更串行 + 原子落盘（2026-09-13 并发编辑事故批） ----------
#
# 事故形态（真实 run 复盘，r_f7c2c322ec21）：模型一 turn 并发发多条 edit_file 打
# 同一文件（ToolNode 线程池真并行），上游 read→replace→O_TRUNC 写回既无锁也
# 不原子，产生两类静默损坏——①后写整存覆盖先写=丢更新（工具还报成功，事后
# 逐字节复核 structure.md/写作指引.md 多处改丢）；②读者撞进他人截断窗口=撕裂
# 读（假「String not found」+ 文件混杂出幽灵残行）。修法两件各治一半：
# - _WRITE_LOCK 全局单锁：所有文件**变更**（write/edit/delete）互斥串行。临界区
#   是纯文件 IO、毫秒级（无 LLM/网络），跨文件串行代价≈0；不按路径分锁是刻意
#   的——省掉锁表增长与路径归一化两类簿记（docx_ops 按路径锁是因其操作秒级、
#   并发是刚需，量级不同取法不同）。读者（read/ls/grep/glob）不上锁：并行热路径，
#   撕裂读由原子替换根治。锁永不嵌套（本锁内不调用任何再取锁的代码）；
# - _atomic_write 原子替换：uuid 后缀 tmp 同目录 + os.replace，读者永远看到完整
#   旧版或完整新版。只做原子不锁不够：丢更新会从「偶尔报错」变成「永远静默丢」。
# 覆盖面=主代理/全部子代理/general-purpose 共享的同一 backend 实例（deepagents
# graph.py 三处 FilesystemMiddleware 同源注入），压缩中间件落 conversation_history
# 的写也经此层。edit 的报错文案复用上游 perform_string_replacement（单源，模型
# 重试路径行为零变化）。
_WRITE_LOCK = threading.Lock()


def _atomic_write(path: Path, content: str) -> None:
    """原子替换落盘：uuid 后缀 tmp 同目录 + os.replace，异常清理残件。"""
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _binary_read_error(file_path: str) -> str | None:
    """二进制/图片扩展名 → 人话拒绝文案（含正确工具出口）；文本返回 None。"""
    suffix = Path(file_path).suffix.lower()
    if suffix in _IMAGE_READ_SUFFIXES:
        return (
            f"[读取被拒绝] {file_path}：图片文件不能用 read_file 读——整图会以 base64 "
            "灌进上下文（一张扫描件≈百万 token，会撑爆模型）。要把图片插入正文请用 "
            "docx_image_insert（image 参数直接传此路径）；确认图片内容请让用户在知识库预览查看。"
        )
    if suffix in _PDF_READ_SUFFIXES:
        return (
            f"[读取被拒绝] {file_path}：PDF 是二进制文件，不能 read_file 直读。"
            "需要其文本内容请用 parse_document 解析；把某页贴进正文用 docx_image_insert"
            "（支持 PDF 按页渲染）。"
        )
    if suffix in _OFFICE_READ_SUFFIXES:
        if suffix in (".xls", ".xlsx", ".xlsm"):
            return (
                f"[读取被拒绝] {file_path}：Excel 是二进制文件，不能 read_file 直读。"
                "当前没有自动解析 Excel 的通道——需要核对表格内容请让用户在应用外"
                "打开确认，不要反复尝试读取。"
            )
        return (
            f"[读取被拒绝] {file_path}：Office 文档是二进制文件，不能 read_file 直读。"
            "读标书正文节请用 docx_section_read；需要其文本内容请用 parse_document 解析。"
        )
    return None


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
    """FilesystemBackend + 写路径黑名单 + 二进制/图片读拦截。

    读拦截只认扩展名（与上游二进制判定同基），文本读语义零变化；异步 aread
    是协议默认的 asyncio.to_thread(self.read, ...) 委托，覆写 read 一处即
    同步/异步双路生效。
    """

    def _deny(self, file_path: str) -> tuple[str, ...] | None:
        try:
            resolved = self._resolve_path(file_path)
        except (OSError, RuntimeError, ValueError):
            # ValueError：virtual_mode 对 ../ 越根/绝对路径逃逸抛的就是它——
            # 吞掉让父类用自己的标准错误返回，而不是异常穿出 guard 被中间件兜成通用串
            return None  # 解析失败交给父类返回标准错误
        rel = resolved.relative_to(self.cwd)
        if _is_protected(rel.parts):
            return rel.parts
        return None

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        err = _binary_read_error(file_path)
        if err is not None:
            return ReadResult(error=err)
        return super().read(file_path, offset=offset, limit=limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        if self._deny(file_path) is not None:
            return WriteResult(error=f"[写入被拒绝] {file_path}：{_WRITE_DENY_NOTE}")
        try:
            resolved = self._resolve_path(file_path)
        except (OSError, RuntimeError) as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e}")
        with _WRITE_LOCK:
            try:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(resolved, content)
                return WriteResult(path=file_path)
            except (OSError, UnicodeEncodeError) as e:
                return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002
    ) -> EditResult:
        if self._deny(file_path) is not None:
            return EditResult(error=f"[写入被拒绝] {file_path}：{_WRITE_DENY_NOTE}")
        try:
            resolved = self._resolve_path(file_path)
        except (OSError, RuntimeError) as e:
            return EditResult(error=f"Error editing file '{file_path}': {e}")
        # 读-改-写整段互斥 + 原子替换：不调 super().edit（其 O_TRUNC 落盘既有
        # 截断窗口又无法与本锁协同）；结构/报错文案与上游逐字对齐
        with _WRITE_LOCK:
            try:
                if not resolved.exists() or not resolved.is_file():
                    return EditResult(error=f"Error: File '{file_path}' not found")
                with open(resolved, "r", encoding="utf-8") as f:
                    content = f.read()
                old = old_string.replace("\r\n", "\n").replace("\r", "\n")
                new = new_string.replace("\r\n", "\n").replace("\r", "\n")
                result = perform_string_replacement(content, old, new, replace_all)
                if isinstance(result, str):
                    return EditResult(error=result)
                new_content, occurrences = result
                _atomic_write(resolved, new_content)
                return EditResult(path=file_path, occurrences=int(occurrences))
            except (OSError, UnicodeDecodeError, UnicodeEncodeError) as e:
                return EditResult(error=f"Error editing file '{file_path}': {e}")

    def delete(self, file_path: str) -> DeleteResult:
        if self._deny(file_path) is not None:
            return DeleteResult(error=f"[写入被拒绝] {file_path}：{_WRITE_DENY_NOTE}")
        with _WRITE_LOCK:  # unlink/rmtree 本身无截断窗口；上锁只为与写者定序
            return super().delete(file_path)
