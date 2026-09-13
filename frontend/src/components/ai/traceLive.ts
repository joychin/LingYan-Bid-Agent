import { createContext } from 'react'

/** 活卡语境标记（2026-09-13 内存修复批）：RunMessage（运行中/HITL 暂停冻结的过程卡）
 *  内部置 true。子代理思考等长文本在活卡内**恒走尾部封顶**——run 结束前陆续完成的
 *  子代理卡会随波次累积，终态渲染整段思考 markdown 是 run 期内存持续爬升的主因之一；
 *  历史过程区（点开才拉取、按需挂载）默认 false 渲染全文。 */
export const TraceLiveContext = createContext(false)

/** 活卡内单块思考文本的渲染上限（字符）：尾部尾窗 + 折叠提示行；全文在 run 结束后
 *  的历史过程区（message-trace 按需拉取）可见。 */
export const TRACE_LIVE_TEXT_CAP = 12000
