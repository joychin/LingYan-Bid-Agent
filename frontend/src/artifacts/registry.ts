/**
 * Artifact Processor 注册表（artifact-system-design.md §6）。
 *
 * 客户端只维护 kind+schema → Processor 的映射；契约真值在 sidecar（/api/contracts）。
 * 新契约接入清单（设计文档 §13）第 3 步：在此注册对应 Processor。
 * 未命中契约的 Artifact 由 Open Host 显示「不支持该类型」，不做隐式 JSON 兜底。
 */

import type { ComponentType } from 'react'
import type { Artifact } from '@/api/client'
import { artifactKey, listContracts } from '@/api/client'
import { DirectoryProcessor } from '@/components/processors/DirectoryProcessor'
import { NoteProcessor } from '@/components/processors/NoteProcessor'

export interface ProcessorProps {
  artifact: Artifact
  /** 当前内容的原始 JSON 文本；解析与防御性校验由各 Processor 自理 */
  content: string
}

export interface ArtifactProcessor {
  /** 与服务端契约 key 一致：kind/schema_id@version */
  key: string
  /** 处理程序显示名（不支持提示/标题用） */
  title: string
  Component: ComponentType<ProcessorProps>
}

const PROCESSORS: Record<string, ArtifactProcessor> = {
  'tender.directory/tender-response-docs@1': {
    key: 'tender.directory/tender-response-docs@1',
    title: '目录处理器',
    Component: DirectoryProcessor,
  },
  // 通用笔记：未注册类型的统一收拢形态（P4），保证 LLM 的自由产物一定打得开
  'doc.note/note-md@1': {
    key: 'doc.note/note-md@1',
    title: '笔记',
    Component: NoteProcessor,
  },
}

export function resolveProcessor(a: Artifact): ArtifactProcessor | undefined {
  return PROCESSORS[artifactKey(a)]
}

/** kind → 列表短标签（产物面板/卡片第二行用）。 */
export function contractLabel(kind: string): string {
  const map: Record<string, string> = {
    'tender.directory': '目录',
    'doc.note': '笔记',
  }
  return map[kind] ?? kind
}

/** 产物 kind → 文件树/聊天卡图标（语义型色板：按内容性质选色 + 字符）。
 *  新增 kind 时同步在 workspace.css 加对应 .ft-ico--xxx 类，并考虑加 .ft-ico--card 变体大小。
 *  未来规划预留位（未实施）：
 *    tender.body      → 紫 #7c3aed + 'B'   投标正文
 *    tender.analysis  → 橙 #f59e0b + 'A'   七节要点
 *    tender.outline   → 黄 #eab308 + 'O'   大纲初稿
 *    tender.flow      → 蓝 #2563eb + 'F'   流程图 */
export interface KindIcon {
  /** 套在 .ft-ico 上的色板类（背景色由此提供） */
  cls: string
  /** 方块内字符 */
  mark: string
}

const KIND_ICON: Record<string, KindIcon> = {
  'tender.directory': { cls: 'ft-ico--dir', mark: '≡' },
  'doc.note': { cls: 'ft-ico--md', mark: 'M' },
}

export function kindIcon(kind: string): KindIcon | null {
  return KIND_ICON[kind] ?? null
}

/** 启动对账：sidecar 契约目录 vs 客户端 Processor 覆盖，缺失即告警（半接入状态防漏）。 */
export async function reconcileContracts(): Promise<void> {
  try {
    const { contracts } = await listContracts()
    const uncovered = contracts.filter((c) => !PROCESSORS[c.key])
    if (uncovered.length > 0) {
      console.warn(
        '[artifacts] 服务端存在客户端未覆盖的契约：',
        uncovered.map((c) => c.key).join(', '),
      )
    }
  } catch {
    /* sidecar 不可达时静默（SidecarBanner 已有状态提示） */
  }
}
