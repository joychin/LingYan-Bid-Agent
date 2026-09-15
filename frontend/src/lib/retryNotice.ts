/** agent.retry 等待期提示的纯计算件（组件渲染测不了 node 环境，逻辑抽纯函数测）。

 * 倒计时从事件到达时刻起算（receivedAt），误差 ≤ SSE 传播延迟；归零后重试已
 * 发出、在等服务方响应，文案退化为无秒数形态。 */

export type RetryScope = "main" | "sub";

/** 剩余等待秒数：ceil 保证显示值 ≥ 实际剩余（宁可多显 1s 也不闪 0 又跳回）。 */
export function retrySecondsLeft(waitSeconds: number, receivedAt: number, now: number): number {
  if (waitSeconds <= 0) return 0;
  const elapsed = (now - receivedAt) / 1000;
  return Math.max(0, Math.ceil(waitSeconds - elapsed));
}

export function retryScopeLabel(scope: RetryScope): string {
  return scope === "sub" ? "子代理" : "主线程";
}

/** shimmer 文案：第 N/T 次 · 失败源（· 剩余秒数后）。 */
export function retryNoticeText(opts: {
  attempt: number;
  total: number;
  scope: RetryScope;
  secondsLeft: number;
}): string {
  const base = `模型服务不稳，正在自动重试（第 ${opts.attempt}/${opts.total} 次 · ${retryScopeLabel(opts.scope)}）`;
  return opts.secondsLeft > 0 ? `${base} · ${opts.secondsLeft}s 后…` : `${base}…`;
}
