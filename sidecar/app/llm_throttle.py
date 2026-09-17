"""LLM 客户端自适应并发闸（AIMD）。

动因（2026-09-15 调研批）：用户可自配任意 OpenAI 兼容网关，小网关/本地部署/免费档
的并发额度可能只有 1~3；而整本派发是同一消息 ≤8 个 task 并发齐发。窄额度网关下
排队请求要么 429 要么挂着等 180s 超时——都是瞬时错误，主 worker 从 checkpoint
整波重放，重放又是 8 路齐发，循环到 llm_unavailable：窄额度网关跑不了整本（单节
会话无并行派发反而正常，用户体感「时好时坏」）。行业共识（OpenAI Cookbook /
LiteLLM 部署冷却 / Netflix concurrency-limits）：429/超时是**背压信号**不是错误，
客户端 AIMD 配速（TCP 拥塞控制同源）是标准做法；Cline/Cursor 的 BYOK 模式均未
做此事（429 原样透传给用户）。

算法（进程内 per-profile，纯运行态）：
- acquire：在飞调用数 ≥ limit 时等待——**有界**（2026-09-17 改：等待预算 300s，
  超限抛 AcquireTimeout 归瞬时错误走断点重试；等待期每秒轮询取消闭包，取消
  检查点补进模型调用前的排队段。原「无界等待、持有者受 180s HTTP 超时约束」
  对流式不成立——180s 是单次读超时，网关持续吐 chunk 就能长期占住许可）；
- release(hard)（429）：limit 减半、下限 1——服务方明确说「太多了」，强信号；
- release(soft)（请求超时）：limit −1、下限 1——弱信号（过载的常见表现，但也可能
  是慢生成，故只减一档）；
- release(neutral)（其余异常）：只归还许可不调闸（400/断流等与容量无关）；
- release(ok)：连续 8 次成功 limit +1，上限与图并发步数对齐（调用方传入）；
- **收缩冷却窗 5s**：一次拥塞事件只允许一次乘性减——同一波并发调用同时失败是
  常态（8 路齐发撞窄额度网关），逐个减半会把 8 直接砸到 1 而回升要 56 次成功，
  一次抖动等于把 run 打成爬行；经典 AIMD 是「每拥塞窗口一次减」（见常量注释）。

窄网关 → 自动降到真实容量上交错推进（慢但能走完，task 派发形态不变）；宽网关 →
稳定在上限零感知。SDK 内建 max_retries=2 保留：瞬时抖动 SDK 层就地消化，闸门只接
持续背压信号。无 UI 无配置项——用户答不上来自己网关的额度，自适应就是为了不问
（「用户没做过的选择不落库」同款铁则的运行态版本）。

落点在 agent._NoThinkingRetryCompletions.create（openai SDK chat.completions 资源
的包装层）：主 agent 与全部子代理共享同一模型实例，流式/非流式调用都经 create
单点；流式许可持有到流耗尽/提前关闭（_UsageCapturingStream 的 on_release）。
LangChain 原生 rate_limiter 钩子只有 acquire 没有 release（框架不知道调用何时
结束），做不了并发数闸，故不走那条路。titler / KB 抽取 / vlm 是独立实例单发低频，
刻意不进闸。

已知边界（2026-09-15 review）：包装层挂在 `model.client`（chat.completions 资源）
上，langchain `BaseChatOpenAI._stream` 走 `self.client.create(**payload)` 正常分支
即被覆盖；仅 `include_response_headers=True` 或 LangSmith 网关（lsv2_ 前缀 key）
会改走 `self.client.with_raw_response.create(...)`——那条路经 `__getattr__` 委派
给内层、绕过闸门。我方两者都不成立（前者默认 False 且我们不设，后者是用户自建
网关），故当前不可达；将来若开 response headers 需一并收口。
"""

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class AcquireTimeout(Exception):
    """acquire 等待超预算（2026-09-17）：闸长期收缩且在飞许可不归还时的有界失败。

    归类瞬时错误——_run_agent_stream 断点重试循环接手（重试重新进 acquire，
    预算重置；重试耗尽落 llm_unavailable），不再无限期挂死。"""


class AcquireCancelled(Exception):
    """acquire 等待期用户取消（2026-09-17）：取消检查点补进模型调用前的等待段。

    语义同流事件边界的协作取消——调用方（_run_agent_stream）按 cancelled 收尾。"""


# release 语义（outcome 取值）
OK = "ok"            # 调用成功：连续计数 +1，满 _GROW_AFTER_SUCCESSES 次回升 +1
HARD = "hard"        # 429：limit 减半（下限 1）——服务方明确拒绝并发
SOFT = "soft"        # 请求超时：limit −1（下限 1）——过载弱信号
NEUTRAL = "neutral"  # 其余异常：只归还许可，不调闸

# acquire 等待预算（秒）与轮询粒度（秒）。预算须显著大于最慢许可持有期（流式
# 调用可持许可数分钟），只兜「闸收到 1 且在飞许可因异常路径未归还」的病态场景；
# 轮询粒度=取消检查点间隔（cancel_check 每轮询一次）。
_ACQUIRE_BUDGET_S = 300.0
_ACQUIRE_POLL_S = 1.0

# 连续成功多少次后 limit +1：探测频率的节流阀——太勤则贴着真实容量反复撞 429
# （AIMD 固有振荡），太懒则容量恢复后爬升慢；8 ≈ 一次「确认容量有余」的样本量
_GROW_AFTER_SUCCESSES = 8

# 收缩冷却窗（秒）：一次拥塞事件只允许一次乘性减。
# 动因=**同一波并发调用会同时失败**：整本派发 8 路齐发撞上窄额度网关时，8 个 429
# 几乎同时到达，逐个减半会把 limit 从 8 直接砸到 1（8→4→2→1→1…），而回升要
# 56 次连续成功——一次网关抖动就把整个 run 打成爬行。经典 AIMD 的口径是「每个
# 拥塞窗口/事件一次减」，不是「每个丢包一次减」（TCP 同源）；行业对应物=LiteLLM
# 的部署冷却窗（`cooldown_time`）。取值=同一波失败的到达跨度量级（并发请求同时
# 结束，429 秒级到达；180s 超时波也在一处收口）——5s 可把一波塌缩成一次减，
# 又不会把「网关真的只有 2 路」这种持续拥塞的连续多波误并（各波间隔远超 5s，
# 照常逐波收敛）。
_SHRINK_COOLDOWN_S = 5.0


class AIMDLimiter:
    """进程内自适应并发闸（Condition 实现；全部读写都在锁内）。"""

    def __init__(self, floor: int = 1, ceiling: int = 8, clock=time.monotonic):
        self._cond = threading.Condition()
        self._floor = floor
        self._ceiling = ceiling
        self._limit = ceiling  # 从满速起步：宽网关零感知，遇背压再收缩
        self._inflight = 0
        self._streak = 0
        self._last_shrink = float("-inf")  # 冷却窗时钟（clock() 语义）
        self._clock = clock

    @property
    def limit(self) -> int:
        with self._cond:
            return self._limit

    @property
    def inflight(self) -> int:
        with self._cond:
            return self._inflight

    def acquire(
        self,
        cancel_check: Callable[[], bool] | None = None,
        budget_s: float = _ACQUIRE_BUDGET_S,
    ) -> None:
        """有界等待取许可（2026-09-17 由无界 wait 改）。

        - cancel_check：取消探测闭包（None=非 run 态/测试直构），每轮询一次——
          原实现无界阻塞且全链取消检查点只在流事件边界，闸收缩到 1 时排在闸后
          的模型调用会无限期等待，「停止」在最需要它的窄网关场景失效；
        - budget_s：等待预算，超限抛 AcquireTimeout（归类瞬时错误走断点重试）。
        """
        deadline = self._clock() + budget_s
        with self._cond:
            while self._inflight >= self._limit:
                if cancel_check is not None and cancel_check():
                    raise AcquireCancelled("模型调用排队等待许可时被取消（用户停止）")
                if self._clock() >= deadline:
                    raise AcquireTimeout(
                        f"并发闸等待许可超预算 {budget_s:.0f}s（limit={self._limit}，"
                        "在飞许可未归还），按瞬时错误重试"
                    )
                self._cond.wait(timeout=min(_ACQUIRE_POLL_S, max(0.0, deadline - self._clock())))
            self._inflight += 1
    def release(self, outcome: str = NEUTRAL) -> None:
        with self._cond:
            self._inflight -= 1
            if outcome == HARD:
                self._shrink(self._limit // 2, "429 背压")
            elif outcome == SOFT:
                self._shrink(self._limit - 1, "超时背压")
            elif outcome == OK:
                self._streak += 1
                if self._streak >= _GROW_AFTER_SUCCESSES and self._limit < self._ceiling:
                    self._limit += 1
                    logger.info(
                        "llm 并发闸回升 → %d（连续 %d 次成功）", self._limit, self._streak
                    )
                    self._streak = 0
            self._cond.notify_all()

    def _shrink(self, target: int, reason: str) -> None:
        """乘性/加性收缩（锁内调用）；冷却窗内的后续失败信号只归还许可不调闸。"""
        self._streak = 0  # 背压期成功不计入回升进度
        now = self._clock()
        if now - self._last_shrink < _SHRINK_COOLDOWN_S:
            logger.debug("llm 并发闸收缩跳过（冷却窗内 %s）", reason)
            return
        new = max(self._floor, target)
        if new != self._limit:
            logger.info("llm 并发闸收缩 %d → %d（%s）", self._limit, new, reason)
        self._limit = new
        self._last_shrink = now



class NoopLimiter:
    """空闸：wrapper 缺省/测试直构时完全透传（不做任何配速）。"""

    def acquire(self, cancel_check: Callable[[], bool] | None = None, budget_s: float = _ACQUIRE_BUDGET_S) -> None:
        pass  # 签名对齐 AIMDLimiter（调用方统一传参）

    def release(self, outcome: str = NEUTRAL) -> None:
        pass


# per-profile 注册表：同 profile 的模型实例（跨 run、rebuild 后重建的）共享同一把
# 闸——跨 run 互护网关；纯运行态不落库、不清（撞线学习同款口径，profile 删了
# 留一条旧闸无害）。ceiling 由调用方传入（agent._MAX_CONCURRENT_STEPS 单源，避免
# 循环导入）。
_LIMITERS: dict[str, AIMDLimiter] = {}
_LIMITERS_GUARD = threading.Lock()


def for_profile(profile_id: str, *, ceiling: int) -> AIMDLimiter:
    """取（或建）该 profile 的并发闸；同 profile 恒同一实例。"""
    with _LIMITERS_GUARD:
        lim = _LIMITERS.get(profile_id)
        if lim is None:
            lim = AIMDLimiter(ceiling=ceiling)
            _LIMITERS[profile_id] = lim
        return lim
