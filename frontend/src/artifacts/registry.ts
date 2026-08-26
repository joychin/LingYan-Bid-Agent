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
