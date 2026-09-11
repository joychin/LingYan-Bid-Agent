import { useCallback, useEffect, useRef, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { fetchActiveRuns, isTauri } from '@/api/client'
import { ModalShell } from '@/components/ui/ModalShell'

/**
 * 退出拦截（2026-09-12）：还有任务在跑时，关窗/cmd+Q 先弹确认——误关一下窗口
 * 无声杀掉跑了半小时的整本任务是最顺手的破坏路径。两条路径：
 * - 窗口关闭（X 钮）：onCloseRequested 拦截，确认后 destroy()（绕过 close-requested）
 * - 应用退出（cmd+Q/菜单）：Rust 侧 ExitRequested 拦下并 emit app:exit-requested，
 *   确认后 invoke('confirm_exit') 放行
 * 只数 status='running' 的 run：waiting_input 的暂停存活于 checkpoint，重启后
 * 仍可裁决续跑，退出无害，不打扰。
 * 浏览器模式（isTauri=false）不挂任何监听。
 */
export function ExitGuard() {
  const [exitSource, setExitSource] = useState<'close' | 'exit' | null>(null)
  // 确认退出后置位：窗口开始销毁期间可能再来 close 事件，直接放行
  const confirmedRef = useRef(false)
  // 一次检查在途时忽略后续触发（防重复弹窗；弹窗开着期间也靠它挡重复触发）；
  // 弹窗被取消时必须复位——否则 Rust 侧仍在拦退出、前端却把所有后续尝试吞掉，
  // app 从此退不出去
  const checkingRef = useRef(false)

  const handleExitAttempt = useCallback(async (source: 'close' | 'exit') => {
    if (confirmedRef.current || checkingRef.current) return
    checkingRef.current = true
    try {
      const { runs } = await fetchActiveRuns()
      if (runs.some((r) => r.status === 'running')) {
        setExitSource(source)
        return
      }
    } catch {
      // sidecar 不可达：没有证据表明有任务在跑，放行退出（拦死退出更糟）
    }
    confirmedRef.current = true
    if (source === 'close') await getCurrentWindow().destroy()
    else await invoke('confirm_exit')
  }, [])

  useEffect(() => {
    if (!isTauri()) return
    const win = getCurrentWindow()
    const unlistenClose = win.onCloseRequested((event) => {
      event.preventDefault()
      void handleExitAttempt('close')
    })
    return () => {
      void unlistenClose.then((f) => f())
    }
  }, [handleExitAttempt])

  useEffect(() => {
    if (!isTauri()) return
    let disposed = false
    let unlisten: (() => void) | null = null
    void listen('app:exit-requested', () => {
      void handleExitAttempt('exit')
    }).then((f) => {
      if (disposed) f()
      else unlisten = f
    })
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [handleExitAttempt])

  if (!exitSource) return null
  // 取消（按钮/点窗外）：关弹窗并复位在途记号，允许下一次退出尝试重新走检查
  const dismiss = () => {
    setExitSource(null)
    checkingRef.current = false
  }
  const confirm = () => {
    const source = exitSource
    setExitSource(null)
    confirmedRef.current = true
    if (source === 'close') void getCurrentWindow().destroy()
    else void invoke('confirm_exit')
  }
  return (
    <ModalShell onClose={dismiss} cardClassName="w-[min(90vw,420px)] p-5">
      <div className="flex flex-col gap-3">
        <div className="text-[15px] font-medium">还有任务正在运行</div>
        <div className="text-sm leading-relaxed text-muted-foreground">
          现在退出会中断任务。中断前的产出会保留，下次启动后可从断点继续或重新执行。
        </div>
        <div className="mt-1 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-secondary"
            onClick={dismiss}
          >
            取消
          </button>
          <button
            type="button"
            className="rounded-md bg-error px-3 py-1.5 text-sm text-white hover:opacity-90"
            onClick={confirm}
          >
            退出
          </button>
        </div>
      </div>
    </ModalShell>
  )
}
