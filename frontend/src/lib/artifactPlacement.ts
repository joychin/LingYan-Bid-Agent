import type { Artifact } from '@/api/client'

/** 产物卡在转录里的落位：按发布 run 归组，其余兜底到尾部。 */
export type ArtifactPlacement = {
  /** run_id → 该 run 发布的产物（保持产物列表原顺序） */
  byRun: Map<string, Artifact[]>
  /** 转录中没有对应回合的产物（旧数据、活卡进行中的 run）→ 转录尾部 */
  tail: Artifact[]
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
