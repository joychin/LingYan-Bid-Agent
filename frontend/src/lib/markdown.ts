import type { PluggableList } from 'unified'
import remarkGfm from 'remark-gfm'

/** 共享 markdown 渲染插件：关闭单波浪号删除线。
 *  GFM 的 singleTilde 默认 true，会把「04~11 … REQ-01~10」这类编号区间里
 *  两个单波浪号配对渲染成删除线（LLM 输出高频踩坑）；~~双波浪~~ 删除线不受影响。 */
export const mdRemarkPlugins: PluggableList = [[remarkGfm, { singleTilde: false }]]
