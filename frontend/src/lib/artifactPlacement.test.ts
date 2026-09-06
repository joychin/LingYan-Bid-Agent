import { describe, expect, it } from 'vitest'
import type { Artifact } from '@/api/client'
import { placeArtifacts } from './artifactPlacement'

function artifact(id: string, runId: string | null): Artifact {
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
