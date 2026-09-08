/** 空状态（无选中会话 / 新建会话草稿页）：欢迎文案；所属任务在输入框左侧胶囊选择或就地新建。 */
export function WelcomeScreen({ hasTask = false }: { /** 已绑定任务（选中会话或草稿页已挑任务）：副标题不再提示「先选任务」 */ hasTask?: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-6">
      <div className="text-center">
        <h2 className="text-lg font-semibold text-foreground">欢迎使用 Swift Agent</h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {hasTask ? '直接在下方输入开始对话，也可上传招标文件' : '在下方输入框选择或新建所属任务后开始对话，也可上传招标文件'}
        </p>
      </div>
    </div>
  )
}
