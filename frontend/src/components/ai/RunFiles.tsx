/**
 * 「本轮文件」chips：run 终态后随最终回复展示（run 起止 work/ 快照 diff 的结果，
 * 经 GET /messages 挂在 assistant 消息上，SSE 零改动）。每枚 chip = 文件图标 +
 * 文件名 + 新建/修改徽标，点击打开工作台面板编辑该文件（path 与 WorkbenchFile.path
 * 同约定，相对 <task>/work/）。溢出收进「+N 个」；files 为空不渲染。
 */
import { useState } from 'react'
import { fileExtIcon } from '@/artifacts/registry'
import { wbDisplayName } from '@/lib/wbNames'
import type { Message } from '@/api/client'

const VISIBLE = 5

export function RunFiles({
  files,
  onOpen,
}: {
  files: Message['files']
  /** 缺省不响应点击（上游 prop 链是可选的；App 恒注入） */
  onOpen?: (path: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  if (!files?.length) return null
  const shown = expanded ? files : files.slice(0, VISIBLE)
  const hidden = files.length - shown.length
  return (
    <div className="run-files">
      <span className="run-files-label">本轮文件</span>
      <div className="run-files-chips">
        {shown.map((f) => {
          // 显示名与面板行/编辑器头部同源（lib/wbNames）；图标按真实路径取扩展名
          const name = wbDisplayName(f.path)
          const icon = fileExtIcon(f.path)
          return (
            <button
              key={f.path}
              type="button"
              className="run-file-chip"
              title={f.path}
              onClick={() => onOpen?.(f.path)}
            >
              <span className={`ft-ico ${icon.cls}`} aria-hidden>
                {icon.mark}
              </span>
              <span className="run-file-name">{name}</span>
              <span className={f.op === 'created' ? 'run-file-op run-file-op--created' : 'run-file-op'}>
                {f.op === 'created' ? '新建' : '修改'}
              </span>
            </button>
          )
        })}
        {hidden > 0 && (
          <button type="button" className="run-file-chip run-file-more" onClick={() => setExpanded(true)}>
            +{hidden} 个
          </button>
        )}
      </div>
    </div>
  )
}
