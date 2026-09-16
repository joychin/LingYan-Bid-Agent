import { describe, expect, it } from 'vitest'
import type { Artifact } from '@/api/client'
import { filterConversationArtifacts, placeArtifacts } from './artifactPlacement'

function artifact(id: string, runId: string | null, conversationId: string | null = 'c1'): Artifact {
  return {
    artifact_id: id,
    display_name: id,
    kind: 'tender.directory',
    schema_id: 'tender.directory',
    schema_version: 1,
    cardinality: 'task-single',
    editable: false,
    content_type: 'json',
    updated_at: '2026-09-06T00:00:00+00:00',
    source: { run_id: runId, thread_id: 'c1' },
    content_seq: 1,
    restore_available: false,
    path: 't1/work/artifacts/x',
    conversation_id: conversationId,
  }
}

describe('placeArtifacts', () => {
  it('产物挂回发布它的回合，保持列表原顺序', () => {
    const placed = placeArtifacts([artifact('a1', 'r1'), artifact('a2', 'r1'), artifact('a3', 'r2')], ['r1', 'r2'])
    expect(placed.byRun.get('r1')!.map((a) => a.artifact_id)).toEqual(['a1', 'a2'])
    expect(placed.byRun.get('r2')!.map((a) => a.artifact_id)).toEqual(['a3'])
    expect(placed.tail).toEqual([])
  })

  it('转录中没有对应回合的产物落尾部兜底（旧数据/活卡进行中）', () => {
    const placed = placeArtifacts([artifact('a1', 'r1'), artifact('a2', null), artifact('a3', 'r9')], ['r1'])
    expect(placed.byRun.get('r1')!.map((a) => a.artifact_id)).toEqual(['a1'])
    expect(placed.tail.map((a) => a.artifact_id)).toEqual(['a2', 'a3'])
  })

  it('空产物列表返回空落位', () => {
    const placed = placeArtifacts([], ['r1'])
    expect(placed.byRun.size).toBe(0)
    expect(placed.tail).toEqual([])
  })
})

describe('filterConversationArtifacts', () => {
  it('首发会话按 conversation_id 命中（现状口径不回归）', () => {
    const out = filterConversationArtifacts([artifact('a1', 'r1', 'c1'), artifact('a2', 'r2', 'c9')], 'c1', ['r1'])
    expect(out.map((a) => a.artifact_id)).toEqual(['a1'])
  })

  it('换会话重发的产物靠 source.run_id 命中本会话（provenance 冻结在首发会话）', () => {
    // 整本场景：首发于 c1（run r_old），后在 c2 的 run r_new 里重写重发
    const vol = artifact('vol', 'r_new', 'c1')
    const out = filterConversationArtifacts([vol], 'c2', ['r_new', 'r_other'])
    expect(out.map((a) => a.artifact_id)).toEqual(['vol'])
  })

  it('run 不属于本会话且首发会话也不匹配的产物被排除（他任务/他话题不串台）', () => {
    const out = filterConversationArtifacts([artifact('a1', 'r9', 'c9'), artifact('a2', null, 'c9')], 'c2', ['r_new'])
    expect(out).toEqual([])
  })

  it('无会话 id 返回空（无任务上下文）', () => {
    expect(filterConversationArtifacts([artifact('a1', 'r1', 'c1')], null, ['r1'])).toEqual([])
  })
})
