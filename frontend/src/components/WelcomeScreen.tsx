/** 空会话欢迎语（任务内新建会话/历史空会话）：任务感知文案——归属由所在任务天然决定，
 *  不再有「先选任务」提示（「任务即房间」，2026-09-13）。 */
export function WelcomeScreen({
  taskTitle,
}: {
  /** 所属任务名（未归类旧会话无任务名时回落通用文案） */
  taskTitle?: string
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-6">
      <div className="text-center">
        <h2 className="text-lg font-semibold text-foreground">欢迎使用 Swift Agent</h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {taskTitle
            ? `在「${taskTitle}」中开始对话，或上传招标文件`
            : '直接在下方输入开始对话，也可上传招标文件'}
        </p>
      </div>
    </div>
  )
}
