import { fromMarkdown } from 'mdast-util-from-markdown'

/**
 * 按顶层 mdast 节点把 markdown 切成块，供 MemoMarkdown 做块级 memo：
 * 流式追加时只有最后一块走完整 remark→hast→React 渲染管线，完成块因 content
 * 引用不变被 memo 跳过，整体解析成本从 O(n²) 降为 O(n)。
 *
 * 解析器与 react-markdown 内部完全同源（remark-parse → mdast-util-from-markdown），
 * 块语义天然一致：列表/表格/引用/围栏都是单节点不会被切碎（有序列表编号不重排），
 * 未闭合围栏到 EOF 是合法 code 节点。这是选它而非 marked-Lexer 或手写空行
 * 切割的原因。代价：每次调用全文重新解析一次（纯解析无 React，KB 级微秒成本）。
 */
/** 脚注引用 [^1] / 定义 [^1]: ——引用与定义必须在同一次解析内才能互相resolve，
 *  分块会破坏配对；检测到即整文单块（Streamdown parse-blocks 同款守卫）。 */
const FOOTNOTE_PATTERN = /\[\^[\w-]{1,200}\](?!:)|\[\^[\w-]{1,200}\]:/

export function splitMarkdownIntoBlocks(markdown: string): string[] {
  const text = markdown ?? ''
  if (!text.trim()) return []
  if (FOOTNOTE_PATTERN.test(text)) return [text]
  const root = fromMarkdown(text)
  const blocks: string[] = []
  for (const node of root.children) {
    const pos = node.position
    if (!pos || typeof pos.start.offset !== 'number' || typeof pos.end.offset !== 'number') {
      // 理论不发生（mdast 顶层节点都带 position）；兜底整文单块，退化为整文渲染
      return [text]
    }
    const raw = text.slice(pos.start.offset, pos.end.offset)
    if (raw.trim()) blocks.push(raw)
  }
  return blocks.length > 0 ? blocks : [text]
}
