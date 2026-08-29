import { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  FileText,
  History,
  Maximize2,
  Minimize2,
  NotebookPen,
  Pencil,
  Upload,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * 产物面板 v3 · 原型（2026-08-29 修订方案阶段 1，仅供 preview.html 预览，不接真实 App）。
 *
 * 验证三个 UI 主张（方案 v2 定稿）：
 * 1. 作用域分组列表替代三根文件夹树——任务正式成果 / 本会话产物 / 任务工作台三分组，
 *    轻组头（VS Code OUTLINE 式小字），最深缩进 ≤2 层；
 * 2. 行 = 主动作（打开）+ 一个状态标（[任务基线]/[待转正]/[可重生成]），
 *    提升动作（转正/存为笔记）hover 显现；
 * 3. 右侧工作区：点击产物后面板从 300px 导航扩展为「导航 + 编辑区」并排（880px），
 *    替代居中模态；转正/覆盖确认保留小模态。
 *
 * 全部假数据 + 本地 state，零 API。转正信息对演示：正式稿「投标目录」与同名草稿
 * 上下分组相邻（方案 v2 走查结论：树形态把这对信息拆在两处）。
 */

type Status = 'baseline' | 'pending' | 'regen'

interface FakeRow {
  id: string
  name: string
  kind: 'dir' | 'note' | 'file'
  status: Status
  /** 状态标文案 */
  statusLabel: string
}

const FORMAL_ROWS: FakeRow[] = [
  { id: 'f1', name: '投标目录', kind: 'dir', status: 'baseline', statusLabel: '任务基线' },
  { id: 'f2', name: '需求矩阵', kind: 'note', status: 'baseline', statusLabel: '任务基线' },
]

const CONV_ROWS: FakeRow[] = [
  // 与正式稿同名相邻——转正信息对（走查截图问题 1 的解法演示）
  { id: 'c1', name: '投标目录（草稿）', kind: 'note', status: 'pending', statusLabel: '待转正' },
  { id: 'c2', name: '商务策略备选', kind: 'note', status: 'pending', statusLabel: '待转正' },
]

const WB_SECTIONS: { id: string; title: string; rows: FakeRow[] }[] = [
  {
    id: 'parse',
    title: '解析',
    rows: [
      { id: 'p1', name: 'AI--谈判文件.md', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'p2', name: '投标表格.md', kind: 'file', status: 'regen', statusLabel: '可重生成' },
    ],
  },
  {
    id: 'analysis',
    title: '分析',
    rows: [
      { id: 'a1', name: '待澄清', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'a2', name: '废标条款', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'a3', name: '评分标准', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'a4', name: '商务技术要求', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'a5', name: '格式要求', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'a6', name: '资格要求', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'a7', name: '递交要求', kind: 'file', status: 'regen', statusLabel: '可重生成' },
      { id: 'a8', name: '结构事实', kind: 'file', status: 'regen', statusLabel: '可重生成' },
    ],
  },
  {
    id: 'outline',
    title: '目录',
    rows: [
      { id: 'o1', name: '投标目录（草稿）', kind: 'file', status: 'regen', statusLabel: '可重生成' },
    ],
  },
]

/** 假目录编辑器数据：复刻走查截图里 DirectoryProcessor 的真实形态（纯样式复刻）。 */
const WS_BANNER = '来源核对：4 个来源未被目录引用（MAND-05、SCORE-05、TPL-05、TPL-17）'
const WS_CHIPS = [
  '项目名称：AI 应用智能体设计及应用（谈判采购）',
  '采购人：中国石油天然气股份有限公司浙江油田分公司',
  '递交截止：2026 年 6 月 15 日上午 11:00（北京时间）',
  '采购方式：竞争性谈判；不接受联合体',
]
const WS_NODES: {
  name: string
  badges: { label: string; cls: string }[]
  desc: string
  depth: number
}[] = [
  { name: '封面（附件1）', badges: [{ label: 'MAND-01', cls: 'mand' }, { label: 'TPL-01', cls: 'tpl' }], desc: '按附件1封面填写项目名称、投标人并盖章签字', depth: 0 },
  { name: '谈判响应声明（附件2）', badges: [{ label: 'MAND-02', cls: 'mand' }, { label: 'TPL-02', cls: 'tpl' }], desc: '按附件2模板作实质响应承诺并盖章签字', depth: 0 },
  { name: '法定代表人资格证明书（附件3）', badges: [{ label: 'MAND-03', cls: 'mand' }, { label: 'TPL-03', cls: 'tpl' }], desc: '按附件3填写法定代表人信息并附身份复印件', depth: 0 },
  { name: '报价说明及首次报价表（表1）', badges: [{ label: 'MAND-06', cls: 'mand' }, { label: 'TPL-06', cls: 'tpl' }, { label: 'REQ-06', cls: 'req' }, { label: 'SCORE-01', cls: 'score' }], desc: '报价说明（按标准/高精度智能体开发单价报价）+首次报价表，装订在正文内', depth: 0 },
  { name: '服务商基本情况表（附件5）', badges: [{ label: 'MAND-07', cls: 'mand' }, { label: 'TPL-08', cls: 'tpl' }], desc: '按附件5表格填写公司基本概况并盖章', depth: 0 },
  { name: '技术方案', badges: [{ label: 'REQ-11', cls: 'req' }, { label: 'SCORE-03', cls: 'score' }], desc: '按技术要求逐项响应，覆盖架构、功能、实施与质保', depth: 0 },
  { name: '系统架构', badges: [{ label: 'REQ-12', cls: 'req' }], desc: '总体架构、部署拓扑与数据流', depth: 1 },
  { name: '功能实现', badges: [{ label: 'REQ-13', cls: 'req' }, { label: 'SCORE-04', cls: 'score' }], desc: '逐项对应招标技术指标的功能点说明', depth: 1 },
  { name: '售后服务与质保', badges: [{ label: 'REQ-15', cls: 'req' }, { label: 'SCORE-06', cls: 'score' }], desc: '服务响应时限、质保期承诺与培训安排', depth: 0 },
]

export function ArtifactPanelNext() {
  const [mode, setMode] = useState<'nav' | 'ws'>('nav')
  const [openId, setOpenId] = useState<string | null>(null)
  const [wbOpen, setWbOpen] = useState(true)
  const [promoteId, setPromoteId] = useState<string | null>(null)

  const openRow = (row: FakeRow) => {
    setOpenId(row.id)
    setMode('ws')
  }

  return (
    <div className="ap-slot">
      <aside className={cn('ap-shell', mode === 'ws' && 'wide')}>
        {/* ---------- 导航列（nav 态 300px / ws 态 260px，同一列） ---------- */}
      <div className="ap-nav">
        <div className="ap-head">
          <span className="ap-head-title">产物 · AI 应用智能体投标</span>
          <div className="ap-head-actions">
            {mode === 'ws' ? (
              <button type="button" className="panel-btn" title="收起编辑器" onClick={() => setMode('nav')}>
                <Minimize2 />
              </button>
            ) : (
              <button
                type="button"
                className="panel-btn"
                title="展开工作区（演示）"
                onClick={() => {
                  setOpenId((prev) => prev ?? 'f1')
                  setMode('ws')
                }}
              >
                <Maximize2 />
              </button>
            )}
          </div>
        </div>

        <div className="ap-body">
          {/* 任务正式成果 */}
          <div className="ap-group">
            <div className="ap-group-head">
              <span>任务正式成果</span>
              <span className="ap-count">2</span>
            </div>
            {FORMAL_ROWS.map((row) => (
              <NavRow
                key={row.id}
                row={row}
                active={openId === row.id}
                onOpen={() => openRow(row)}
              />
            ))}
          </div>

          {/* 本会话产物 */}
          <div className="ap-group">
            <div className="ap-group-head">
              <span>本会话产物</span>
              <span className="ap-count">2</span>
            </div>
            {CONV_ROWS.map((row) => (
              <NavRow
                key={row.id}
                row={row}
                active={openId === row.id}
                onOpen={() => openRow(row)}
                onPromote={() => setPromoteId(row.id)}
              />
            ))}
          </div>

          {/* 任务工作台：默认折叠一层，组内小节平铺 */}
          <div className="ap-group">
            <button type="button" className="ap-group-head clickable" onClick={() => setWbOpen((v) => !v)}>
              <span>任务工作台</span>
              {wbOpen ? <ChevronDown className="ap-chev" /> : <ChevronRight className="ap-chev" />}
            </button>
            {wbOpen && (
              <div className="ap-wb">
                {WB_SECTIONS.map((sec) => (
                  <div key={sec.id} className="ap-sub">
                    <div className="ap-sub-head">{sec.title}</div>
                    {sec.rows.map((row) => (
                      <NavRow key={row.id} row={row} compact active={openId === row.id} onOpen={() => openRow(row)} />
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ---------- 工作区（仅 ws 态）：假目录编辑器 ---------- */}
      {mode === 'ws' && (
        <div className="ap-ws">
          <div className="ap-ws-head">
            <FileText className="ap-ws-docico" />
            <span className="ap-ws-title">投标目录</span>
            <span className="ap-scope-badge">任务正式成果 · 本任务共享</span>
            <div className="ap-ws-actions">
              <button type="button" className="ap-btn">
                <Pencil />
                编辑目录
              </button>
              <button type="button" className="ap-btn ghost">
                <History />
                恢复上一版
              </button>
            </div>
          </div>

          <div className="ap-ws-body">
            <div className="ap-banner">
              <span className="ap-banner-ico">!</span>
              <span>{WS_BANNER}</span>
            </div>
            <div className="ap-chips">
              {WS_CHIPS.map((c) => (
                <span key={c} className="ap-chip">
                  {c}
                </span>
              ))}
            </div>

            <div className="ap-doc">
              <div className="ap-doc-head">
                <FileText />
                <span>响应文件（整册装订）</span>
                <span className="ap-doc-meta">15 个顶层章节</span>
              </div>
              {WS_NODES.map((node) => (
                <div key={node.name} className="ap-node" style={{ paddingLeft: 12 + node.depth * 18 }}>
                  <span className="ap-node-name">{node.name}</span>
                  {node.badges.map((b) => (
                    <span key={b.label} className={cn('ap-src', b.cls)}>
                      {b.label}
                    </span>
                  ))}
                  <div className="ap-node-desc">{node.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ---------- 转正确认小模态（不可逆动作才用模态） ---------- */}
      {promoteId && (
        <div className="ap-modal-mask" onClick={() => setPromoteId(null)}>
          <div className="ap-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ap-modal-head">
              <span>转为任务正式成果</span>
              <button type="button" className="panel-btn" onClick={() => setPromoteId(null)}>
                <X />
              </button>
            </div>
            <div className="ap-modal-body">
              <p>
                将「{CONV_ROWS.find((r) => r.id === promoteId)?.name}」复制为任务正式成果，
                对本任务所有会话可见。
              </p>
              <p className="ap-modal-note">
                如果已有同类正式成果，将覆盖其当前内容；覆盖前自动保留恢复点。原会话产物不受影响。
              </p>
            </div>
            <div className="ap-modal-foot">
              <button type="button" className="ap-btn ghost" onClick={() => setPromoteId(null)}>
                取消
              </button>
              <button type="button" className="ap-btn primary" onClick={() => setPromoteId(null)}>
                <Upload />
                转为任务正式成果
              </button>
            </div>
          </div>
        </div>
      )}
      </aside>
    </div>
  )
}

function NavRow({
  row,
  active,
  compact,
  onOpen,
  onPromote,
}: {
  row: FakeRow
  active?: boolean
  compact?: boolean
  onOpen: () => void
  /** 有值 = 会话产物行，hover 显示转正动作 */
  onPromote?: () => void
}) {
  return (
    <div className={cn('ap-row', compact && 'compact', active && 'active')} onClick={onOpen}>
      {row.kind === 'dir' ? (
        <span className="ft-ico ft-ico--dir">≡</span>
      ) : (
        <span className="ft-ico ft-ico--md">{row.kind === 'file' ? 'M' : <NotebookPen className="ap-pen" />}</span>
      )}
      <span className="ap-row-name truncate">{row.name}</span>
      {/* 状态标与转正动作同位叠放：hover 时标淡出、动作淡入（opacity 淡入约定，不 display 切换） */}
      <span className="ap-row-tail">
        <span className={cn('ap-status', row.status)}>{row.statusLabel}</span>
        {onPromote && (
          <button
            type="button"
            className="ap-row-action"
            title="复制到任务正式成果（原件保留，覆盖自动留恢复点）"
            onClick={(e) => {
              e.stopPropagation()
              onPromote()
            }}
          >
            <Upload />
            转正
          </button>
        )}
      </span>
    </div>
  )
}

/** 空态演示版：无产物任务的引导文案（对照 v2 走查问题 6）。 */
export function ArtifactPanelNextEmpty() {
  return (
    <div className="ap-slot">
      <aside className="ap-shell">
        <div className="ap-nav">
        <div className="ap-head">
          <span className="ap-head-title">产物 · 新任务</span>
        </div>
        <div className="ap-body">
          <div className="ap-group">
            <div className="ap-group-head">
              <span>任务正式成果</span>
            </div>
            <div className="ap-empty">
              还没有任务正式成果。
              <br />
              会话产物经你确认后，会成为任务共享成果。
            </div>
          </div>
          <div className="ap-group">
            <div className="ap-group-head">
              <span>本会话产物</span>
            </div>
            <div className="ap-empty">
              本会话还没有产物。
              <br />
              Agent 生成目录、矩阵或笔记后，会显示在这里。
            </div>
          </div>
          <div className="ap-group">
            <div className="ap-group-head">
              <span>任务工作台</span>
            </div>
            <div className="ap-empty">
              尚未生成内容。
              <br />
              解析、分析或目录流程运行后，过程文件会显示在这里。
            </div>
          </div>
        </div>
      </div>
      </aside>
    </div>
  )
}
