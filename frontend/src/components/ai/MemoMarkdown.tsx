import { memo, useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import { mdRemarkPlugins } from '@/lib/markdown'
import { splitMarkdownIntoBlocks } from '@/lib/markdownBlocks'

/** markdown 自定义组件（表格/链接/行内代码）：模块级单例。引用稳定是块级 memo
 *  的前提——不要在渲染中内联构造 components 对象。 */
export const markdownComponents = {
  table: (props: React.ComponentPropsWithoutRef<'table'>) => (
    // 只留横向滚动：助手区是通栏扁平设计（无卡片），外框/白底/圆角会在白底上
    // 悬出一个多余边框盒，格线由 th/td 自带 border 表达
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  th: (props: React.ComponentPropsWithoutRef<'th'>) => (
    <th className="border px-3 py-1.5 text-left font-semibold" {...props} />
  ),
  td: (props: React.ComponentPropsWithoutRef<'td'>) => (
    <td className="border px-3 py-1.5 align-top" {...props} />
  ),
  a: (props: React.ComponentPropsWithoutRef<'a'>) => (
    <a className="text-primary underline" target="_blank" rel="noreferrer" {...props} />
  ),
  code: (props: React.ComponentPropsWithoutRef<'code'>) => (
    <code className="rounded bg-muted px-1 py-0.5 text-[0.9em]" {...props} />
  ),
}

/** 单块渲染，memo 在 content 引用上：流式追加时完成块的 content 切片不变，
 *  直接跳过 remark→hast→React 全管线。 */
const MemoBlock = memo(function MemoBlock({
  md,
  components,
}: {
  md: string
  components?: Components
}) {
  return (
    <ReactMarkdown remarkPlugins={mdRemarkPlugins} components={components}>
      {md}
    </ReactMarkdown>
  )
})

/** 分块 memo 的 markdown 渲染器（Streamdown/LibreChat 同思路）：
 *  按顶层 mdast 节点切块（lib/markdownBlocks），块间 DOM 与整文渲染完全等价
 *  （都是 .bubble 下的平铺块元素）。聊天流式表面一律走本组件，禁止裸
 *  ReactMarkdown 直渲流式文本；静态一次性内容（processor/查看器）可继续裸用。 */
export function MemoMarkdown({
  text,
  components,
}: {
  text: string
  components?: Components
}) {
  const blocks = useMemo(() => splitMarkdownIntoBlocks(text), [text])
  return (
    <>
      {blocks.map((b, i) => (
        <MemoBlock key={i} md={b} components={components} />
      ))}
    </>
  )
}
