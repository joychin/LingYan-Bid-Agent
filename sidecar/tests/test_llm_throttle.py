"""AIMD 并发闸单元测试：收缩/回升/下限上限/阻塞唤醒/注册表共享。

背压语义（hard=429 减半、soft=超时 −1、neutral 只归还、ok 连续 8 次回升）的
行为契约；配速接线（wrapper 侧）见 test_agent.py。
"""

import threading

import pytest

from app import llm_throttle


class _Clock:
    """可推进的假时钟：让收缩冷却窗（_SHRINK_COOLDOWN_S）在测试里可控。"""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _limiter(ceiling: int = 8, clock=None) -> llm_throttle.AIMDLimiter:
    return llm_throttle.AIMDLimiter(ceiling=ceiling, clock=clock or _Clock())


def test_hard_failure_halves_with_floor():
    clock = _Clock()
    lim = _limiter(clock=clock)
    for expected in (4, 2, 1, 1):  # 8→4→2→1→钉在下限
        clock.advance(llm_throttle._SHRINK_COOLDOWN_S)  # 每波间隔超出冷却窗=独立事件
        lim.acquire()
        lim.release(llm_throttle.HARD)
        assert lim.limit == expected


def test_soft_failure_decrements_with_floor():
    clock = _Clock()
    lim = _limiter(clock=clock)
    clock.advance(llm_throttle._SHRINK_COOLDOWN_S)
    lim.acquire()
    lim.release(llm_throttle.SOFT)
    assert lim.limit == 7
    lim2 = llm_throttle.AIMDLimiter(ceiling=1, clock=_Clock())
    lim2.acquire()
    lim2.release(llm_throttle.SOFT)
    assert lim2.limit == 1


def test_burst_failures_shrink_once():
    """同一波并发调用同时失败（本功能要治的核心场景）：8 个 429 几乎同时到达，
    只允许一次乘性减——否则 limit 从 8 被逐个砸到 1，而回升要 56 次成功。"""
    clock = _Clock()
    lim = _limiter(clock=clock)
    for _ in range(8):
        lim.acquire()
    for _ in range(8):
        lim.release(llm_throttle.HARD)  # 同一时刻（时钟未推进）
    assert lim.limit == 4, "一波 8 个 429 应只减半一次"


def test_shrink_resumes_after_cooldown():
    """冷却窗过期后仍可继续收缩：网关真的只有 1 路时逐波收敛到下限。"""
    clock = _Clock()
    lim = _limiter(clock=clock)
    lim.acquire()
    lim.release(llm_throttle.HARD)
    assert lim.limit == 4
    lim.acquire()
    lim.release(llm_throttle.HARD)  # 冷却窗内：跳过
    assert lim.limit == 4
    clock.advance(llm_throttle._SHRINK_COOLDOWN_S)
    lim.acquire()
    lim.release(llm_throttle.HARD)  # 新事件：继续收缩
    assert lim.limit == 2


def test_neutral_returns_permit_without_signal():
    lim = _limiter(ceiling=8)
    lim.acquire()
    lim.release(llm_throttle.NEUTRAL)
    assert lim.limit == 8
    assert lim.inflight == 0


def test_success_streak_grows_after_threshold():
    lim = _limiter(ceiling=8)
    lim._limit = 4  # 直接构造收缩后的档位（语义另测）
    for _ in range(7):
        lim.acquire()
        lim.release(llm_throttle.OK)
    assert lim.limit == 4  # 未满 8 次不回升
    lim.acquire()
    lim.release(llm_throttle.OK)
    assert lim.limit == 5
    # 回升后连续计数清零：再 8 次才 +1
    for _ in range(8):
        lim.acquire()
        lim.release(llm_throttle.OK)
    assert lim.limit == 6


def test_success_caps_at_ceiling():
    lim = _limiter(ceiling=2)
    for _ in range(20):
        lim.acquire()
        lim.release(llm_throttle.OK)
    assert lim.limit == 2


def test_failure_resets_success_streak():
    clock = _Clock()
    lim = _limiter(clock=clock)
    lim._limit = 4
    for _ in range(7):
        lim.acquire()
        lim.release(llm_throttle.OK)
    clock.advance(llm_throttle._SHRINK_COOLDOWN_S)
    lim.acquire()
    lim.release(llm_throttle.SOFT)  # 4→3 且清零连续计数
    assert lim.limit == 3
    for _ in range(8):
        lim.acquire()
        lim.release(llm_throttle.OK)
    assert lim.limit == 4  # 从 3 回升一次，不是两次


def test_skipped_shrink_still_resets_streak():
    """冷却窗内跳过的失败信号同样清零回升进度：背压期的成功不该推高 limit。"""
    clock = _Clock()
    lim = _limiter(clock=clock)
    lim._limit = 4
    lim.acquire()
    lim.release(llm_throttle.HARD)  # 4→2（首次收缩，进入冷却窗）
    for _ in range(7):
        lim.acquire()
        lim.release(llm_throttle.OK)  # 攒到 7 次
    lim.acquire()
    lim.release(llm_throttle.HARD)  # 冷却窗内：不收缩但清零
    assert lim.limit == 2
    for _ in range(7):
        lim.acquire()
        lim.release(llm_throttle.OK)
    assert lim.limit == 2, "清零后未满 8 次不应回升"


def test_acquire_blocks_at_limit_and_wakes_on_release():
    lim = _limiter(ceiling=1)
    lim.acquire()  # 占满唯一许可
    acquired = threading.Event()

    def blocked():
        lim.acquire()
        acquired.set()
        lim.release(llm_throttle.OK)

    t = threading.Thread(target=blocked, daemon=True)
    t.start()
    assert not acquired.wait(0.15), "满限时应阻塞等待"
    lim.release(llm_throttle.OK)  # 归还并唤醒
    assert acquired.wait(2), "归还后等待者应被唤醒"
    t.join(timeout=2)
    assert lim.inflight == 0


def test_wakes_on_limit_growth():
    """收缩回升（notify_all）同样唤醒等待者——limit 变化即广播。"""
    lim = _limiter(ceiling=2)
    lim.acquire()
    lim.acquire()  # 占满 2
    acquired = threading.Event()

    def blocked():
        lim.acquire()
        acquired.set()
        lim.release(llm_throttle.OK)

    t = threading.Thread(target=blocked, daemon=True)
    t.start()
    assert not acquired.wait(0.15)
    # 归还一个（limit 仍 2，inflight 1→有空位）
    lim.release(llm_throttle.OK)
    assert acquired.wait(2)
    t.join(timeout=2)
    assert lim.inflight == 1  # blocked 线程已归还，剩主线程持有的一个


def test_for_profile_shares_instance_per_id():
    a = llm_throttle.for_profile("test-profile-x", ceiling=8)
    b = llm_throttle.for_profile("test-profile-x", ceiling=8)
    c = llm_throttle.for_profile("test-profile-y", ceiling=8)
    assert a is b
    assert a is not c


def test_noop_limiter_passthrough():
    noop = llm_throttle.NoopLimiter()
    noop.acquire()  # 不阻塞不计数
    noop.release(llm_throttle.HARD)  # 不抛不调信号


# ---------- acquire 有界等待 + 取消轮询（2026-09-17 批次④） ----------


def test_acquire_cancel_check_raises():
    """等待期取消置位 → AcquireCancelled（原实现无界 wait，取消检查点只在流事件
    边界——闸收缩到 1 时点「停止」形同虚设）。首轮即在等待前探测，立即抛出。"""
    lim = _limiter(ceiling=1)
    lim.acquire()  # 占满唯一许可
    with pytest.raises(llm_throttle.AcquireCancelled, match="取消"):
        lim.acquire(cancel_check=lambda: True)


def test_acquire_timeout_after_budget():
    """许可长期不归还 + 预算耗尽 → AcquireTimeout（归类瞬时错误走断点重试，
    不再无限期挂死）。假时钟由旁路线程推进（acquire 在 wait 里睡真实 1s 轮询）。"""
    import time as _time

    clock = _Clock()
    lim = _limiter(ceiling=1, clock=clock)
    lim.acquire()

    def _tick():
        _time.sleep(0.05)
        clock.advance(301.0)

    threading.Thread(target=_tick, daemon=True).start()
    with pytest.raises(llm_throttle.AcquireTimeout):
        lim.acquire(cancel_check=lambda: False, budget_s=300.0)


def test_acquire_waits_then_succeeds_on_release():
    """正常排队语义不变：等待期取消未置位、他人归还许可 → 照常取得。"""
    lim = _limiter(ceiling=1)
    lim.acquire()
    threading.Timer(0.05, lambda: lim.release(llm_throttle.OK)).start()
    lim.acquire(cancel_check=lambda: False, budget_s=5.0)
    assert lim.inflight == 1  # 归还者在等待者取得前已把在飞数降回 0


def test_acquire_errors_classified_transient():
    """两类闸等待失败都归瞬时错误：超时重进 acquire（预算重置）、取消由重试循环
    按 cancelled 收尾（只在 cancel 已置位时抛出）。"""
    from app.agent import _is_llm_transient

    assert _is_llm_transient(llm_throttle.AcquireTimeout("闸等待超预算"))
    assert _is_llm_transient(llm_throttle.AcquireCancelled())
