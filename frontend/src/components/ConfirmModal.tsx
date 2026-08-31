import { BadgeCheck, X } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { useConfirmArtifact } from '@/hooks/useArtifacts'

/**
 * 确认卡（原地盖戳，不复制不搬家）：确认 = 草稿 → 已确认（可撤销，撤销入口在
 * 面板已确认行内）；说明恢复点兜底与「AI 重跑覆盖会降级回草稿」，确认时携带
 * 用户所见 content_seq（后端不符 409）。
 * ArtifactCard 与产物面板行共用；artifact 为 null 时不渲染。
 * （旧名 PromoteConfirmModal——promote 复制语义已废除，2026-08-31 更名。）
 */
export function ConfirmModal({ artifact, onClose }: { artifact: Artifact | null; onClose: () => void }) {
  const confirm = useConfirmArtifact()
  if (!artifact) return null

  return (
    <div className="ap-modal-mask" onClick={onClose}>
      <div className="ap-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ap-modal-head">
          <span>确认为正式成果</span>
          <button type="button" className="panel-btn" onClick={onClose} aria-label="关闭">
            <X />
          </button>
        </div>
        <div className="ap-modal-body">
          <p>
            将「{artifact.display_name}」确认为正式成果。确认后 AI 重跑覆盖它时会先降回草稿，
            需你重新确认。
          </p>
          <p className="ap-modal-note">
            确认不复制、不搬家；草稿快照进恢复点，可随时撤销。
          </p>
        </div>
        <div className="ap-modal-foot">
          <button type="button" className="ap-btn ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="ap-btn primary"
            disabled={confirm.isPending}
            onClick={() => {
              confirm.mutate(
                { id: artifact.artifact_id, seq: artifact.content_seq },
                { onSuccess: onClose },
              )
            }}
          >
            <BadgeCheck />
            确认为正式成果
          </button>
        </div>
      </div>
    </div>
  )
}
