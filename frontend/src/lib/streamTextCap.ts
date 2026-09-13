/**
 * 流式思考文本尾部限长（2026-09-08 活卡内存暴涨修复）。
 *
 * 活卡把 8 路子代理的全部累计思考流挂成活 DOM（tender-body 整本 run 11 分钟
 * ≈30MB 文本，页面 WebContent footprint 涨到 11GB）。流式期间只渲染尾部一段：
 * DOM 体量与 MemoMarkdown 每次节流的全量重解析成本都从「随 run 无界增长」变为
 * 恒定。终态分语境（2026-09-13 修订）：活卡内（RunMessage，经 TraceLiveContext
 * 标记）终态同样封顶——run 期陆续完成的子代理卡随波次累积，整段思考常驻 DOM 是
 * 内存持续爬升主因；历史快照（点开才拉取、按需挂载）不受影响，渲染全文。
 *
 * 已知取舍：尾部切片可能截断 markdown 结构（代码块/表格从中间开始）——它是
 * 瞬态预览，终态视图是完整原文，接受。
 */

/** 流式期间单块思考的渲染上限（字符）。8 路并发下活卡思考文本恒 ≤ 8×cap。 */
export const STREAM_TEXT_CAP = 4000

export interface CappedStreamText {
  /** 交给渲染层的文本：未超长 = 原文；超长 = 提示行 + 尾部切片 */
  text: string
  /** 被折叠的字符数（0 = 未超长） */
  omitted: number
}

export function capStreamingText(
  text: string,
  cap: number = STREAM_TEXT_CAP,
  /** 提示行里的内容名词（思考/正文），默认沿用思考流 */
  noun: string = '思考',
): CappedStreamText {
  if (text.length <= cap) return { text, omitted: 0 }
  const omitted = text.length - cap
  return {
    text: `⋯已折叠前 ${omitted} 字的${noun}，结束后可查看完整内容\n\n${text.slice(-cap)}`,
    omitted,
  }
}
