// splash 独立窗口的主题适配：与 main.tsx 首帧同键同值（小写 dark，tokens.css 的
// [data-theme="dark"] 对齐），首帧前执行防闪错。CSP 禁内联脚本故外链。
try {
  var t = localStorage.getItem('tender-agent.theme')
  if (t) document.documentElement.dataset.theme = t
} catch {
  /* localStorage 不可用时保持浅色默认 */
}
