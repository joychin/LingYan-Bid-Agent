/**
 * 侧栏「任务内会话」截断：折叠态每个任务只渲染最近 CONV_PREVIEW_LIMIT 条，
 * 更早的收进「显示更多」。例外会话（运行中/等待确认/未读/当前选中）永不折叠
 * ——原位并入可见集，哪怕超出限额，只折叠「沉默的老任务」。
 * 展开=一次全量不分页；展开态不持久化（重启回折叠）。
 */

/** 折叠态下每个任务内可见的会话数上限。 */
export const CONV_PREVIEW_LIMIT = 15

/**
 * 从「最近在前」的会话序列挑出当前应渲染的子集。
 * 折叠时以 LIMIT 个为基底、isException 命中项原位并入（visible 可能超 LIMIT）；
 * hiddenCount=0 表示折叠视图已是全量，调用方不应渲染「显示更多」按钮。
 */
export function pickVisibleConversations<T extends { id: string }>(
  all: readonly T[],
  isException: (c: T) => boolean,
  expanded: boolean,
): { visible: T[]; hiddenCount: number } {
  if (expanded || all.length <= CONV_PREVIEW_LIMIT) {
    return { visible: [...all], hiddenCount: 0 }
  }
  const visible = all.filter((c, i) => i < CONV_PREVIEW_LIMIT || isException(c))
  return { visible, hiddenCount: all.length - visible.length }
}
