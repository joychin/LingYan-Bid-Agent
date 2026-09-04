import type { PluggableList } from 'unified'
import remarkGfm from 'remark-gfm'

/** 共享 markdown 渲染插件：关闭单波浪号删除线。
 *  GFM 的 singleTilde 默认 true，会把「04~11 … REQ-01~10」这类编号区间里
 *  两个单波浪号配对渲染成删除线（LLM 输出高频踩坑）；~~双波浪~~ 删除线不受影响。 */
export const mdRemarkPlugins: PluggableList = [[remarkGfm, { singleTilde: false }]]

/** 预览层剔除整行 HTML 注释（产物头部元信息行、解析文件的页码锚点行）。
 *  react-markdown 无 rehype-raw 时会把注释转义成可见文字而非吞掉，
 *  这里按真实渲染语义（注释不可见）先行剔除；只剔整行，行内注释不动。 */
export function stripCommentLines(text: string): string {
  return text
    .split('\n')
    .filter((line) => !/^\s*<!--.*?-->\s*$/.test(line))
    .join('\n')
}
