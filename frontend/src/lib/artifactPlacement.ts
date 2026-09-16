import type { Artifact } from '@/api/client'

/** 产物卡在转录里的落位：按发布 run 归组，其余兜底到尾部。 */
export type ArtifactPlacement = {
  /** run_id → 该 run 发布的产物（保持产物列表原顺序） */
  byRun: Map<string, Artifact[]>
  /** 转录中没有对应回合的产物（旧数据）→ 转录尾部 */
  tail: Artifact[]
}

/** 产物卡进本会话转录的口径：首发会话匹配，或最后一次发布的 run 属于本会话。
 *
 *  conversation_id 是 provenance（首发会话出处，重发永不更新——产物归任务，
 *  会话只是出处），单按它过滤会把「同任务新会话里重发的产物」永远挡在转录外
 *  （2026-09-16 实测：换会话重写整本后聊天只剩「本轮文件」chips）。source.run_id
 *  = last_run_id，每次真发布更新为最新 run——命中它即「本会话刚发布过」，卡由
 *  placeArtifacts 挂回该 run 的回合。 */
export function filterConversationArtifacts(
  artifacts: Artifact[],
  conversationId: string | null,
  transcriptRunIds: Iterable<string>,
): Artifact[] {
  if (!conversationId) return []
  const rids = new Set(transcriptRunIds)
  return artifacts.filter(
    (a) =>
      a.conversation_id === conversationId ||
      (a.source?.run_id != null && rids.has(a.source.run_id)),
  )
}

/** 产物卡挂回发布它的回合：source.run_id 与消息 run_id 同源。产物卡若恒
 *  追加在转录末尾，新消息一插入就会被挤到用户气泡之后（2026-09-06 实测），
 *  必须按发布回合落位；匹配不到回合的保留尾部兜底，不丢卡。 */
export function placeArtifacts(convArtifacts: Artifact[], transcriptRunIds: Iterable<string>): ArtifactPlacement {
  const known = new Set(transcriptRunIds)
  const byRun = new Map<string, Artifact[]>()
  const tail: Artifact[] = []
  for (const a of convArtifacts) {
    const rid = a.source?.run_id ?? null
    if (rid && known.has(rid)) {
      const list = byRun.get(rid)
      if (list) list.push(a)
      else byRun.set(rid, [a])
    } else {
      tail.push(a)
    }
  }
  return { byRun, tail }
}
