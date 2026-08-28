import { useEffect, useRef, useState } from 'react'
import { Plus, Send, Square } from 'lucide-react'
import { ModelSelect } from './ModelSelect'

export interface ComposerProps {
  placeholder?: string
  model?: string
  running?: boolean
  disclaimer?: string
  onSend?: (text: string) => void
}

/** 底部输入区：圆角 24 输入框（自适应高度）+ 附件钮 + 模型胶囊 + 圆形发送 + 免责声明。 */
export function Composer({
  placeholder = '今天帮你做些什么？',
  model = 'Hy3',
  running = false,
  disclaimer = '内容由 AI 生成，请核实重要信息',
  onSend,
}: ComposerProps) {
  const [text, setText] = useState('')
  const taRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = '46px'
    el.style.height = `${Math.min(160, el.scrollHeight)}px`
  }, [text])

  const handleSend = () => {
    if (!text.trim() || running) return
    onSend?.(text)
    setText('')
  }

  return (
    <div className="composer">
      <div className="box">
        <textarea
          ref={taRef}
          value={text}
          placeholder={placeholder}
          rows={1}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
        />
        <div className="row">
          <button type="button" className="composer-plus" title="添加附件">
            <Plus />
          </button>
          <div className="right">
            <ModelSelect
              options={[{ id: 'demo', name: model, model: 'demo-model', imageSupport: false }]}
              value="demo"
              onChange={() => {}}
              onManage={() => {}}
            />
            <button
              type="button"
              className="send-btn"
              title={running ? '任务进行中' : '发送'}
              onClick={handleSend}
            >
              {running ? <Square /> : <Send />}
            </button>
          </div>
        </div>
      </div>
      {disclaimer && <div className="composer-disclaimer">{disclaimer}</div>}
    </div>
  )
}
