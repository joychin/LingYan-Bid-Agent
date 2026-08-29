import { Upload, X } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { usePromoteArtifact } from '@/hooks/useArtifacts'

/**
 * 转正确认卡（方案 v2 §4c）：不可逆动作才用模态——说明复制语义、覆盖警告与
 * 恢复点兜底，确认时携带用户所见 content_seq（后端不符返回 409 软确认）。
 * ArtifactCard 与产物面板行共用；artifact 为 null 时不渲染。
 */
export function PromoteConfirmModal({ artifact, onClose }: { artifact: Artifact | null; onClose: () => void }) {
  const promote = usePromoteArtifact()
  if (!artifact) return null

  return (
    <div className="ap-modal-mask" onClick={onClose}>
      <div className="ap-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ap-modal-head">
          <span>转为任务正式成果</span>
          <button type="button" className="panel-btn" onClick={onClose} aria-label="关闭">
            <X />
          </button>
        </div>
        <div className="ap-modal-body">
          <p>
            将「{artifact.display_name}」复制为任务正式成果，对本任务所有会话可见。
          </p>
          <p className="ap-modal-note">
            如果已有同类正式成果，将覆盖其当前内容；覆盖前自动保留恢复点。原会话产物不受影响。
          </p>
        </div>
        <div className="ap-modal-foot">
          <button type="button" className="ap-btn ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="ap-btn primary"
            disabled={promote.isPending}
            onClick={() => {
              promote.mutate(
                { id: artifact.artifact_id, seq: artifact.content_seq },
                { onSuccess: onClose },
              )
            }}
          >
            <Upload />
            转为任务正式成果
          </button>
        </div>
      </div>
    </div>
  )
}
