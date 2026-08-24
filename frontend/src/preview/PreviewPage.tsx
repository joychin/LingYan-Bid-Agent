import { useState } from 'react'
import type { ReactNode } from 'react'
import { BookOpen, ChevronDown, ChevronRight, FolderOpen, Plus, Settings } from 'lucide-react'
import { Sidebar } from '@/components/workspace/Sidebar'
import type { QuickNavItem, SidebarSection } from '@/components/workspace/Sidebar'
import { ChatItem } from '@/components/workspace/ChatItem'
import { NavRow } from '@/components/workspace/NavRow'
import { NavSection } from '@/components/workspace/NavSection'
import { NavItem } from '@/components/workspace/NavItem'
import { SpaceCard } from '@/components/workspace/SpaceCard'
import { UserBar } from '@/components/workspace/UserBar'
import { ModelSelect } from '@/components/workspace/ModelSelect'
import { IconButton } from '@/components/workspace/IconButton'
import { Avatar } from '@/components/workspace/Avatar'
import { Message } from '@/components/workspace/Message'
import { ProcessArtifact, TodoList, Spinner, ArtPulse } from '@/components/workspace/ProcessArtifact'
import { Composer } from '@/components/workspace/Composer'
import { ProductPanel } from '@/components/workspace/ProductPanel'
import type { ArtifactRow } from '@/components/workspace/ProductPanel'

const QUICK_NAV: QuickNavItem[] = [
  { id: 'new', icon: <Plus />, label: '新建任务' },
  { id: 'workbench', icon: <FolderOpen />, label: '投标工作台' },
  { id: 'kb', icon: <BookOpen />, label: '知识库' },
]

const SECTIONS: SidebarSection[] = [
  {
    id: 'tasks',
    title: '任务',
    count: 6,
    folders: [
      {
        id: 'bid-xxx',
        name: 'XXX 标书',
        items: [
          { id: 'c1', title: '讨论客户端 APP 重写…', meta: '3 天前' },
          { id: 'c2', title: 'Design page using …', meta: '14 天前' },
          { id: 'c3', title: 'Redesign design sy…', meta: '14 天前' },
          { id: 'c4', title: 'Redesign tender re…', meta: '14 天前' },
          { id: 'c5', title: 'Build complete desi…', meta: '14 天前' },
        ],
        moreLabel: '查看更多（11）',
      },
    ],
  },
]

const PRODUCT_ARTIFACTS: ArtifactRow[] = [
  { name: '机—健康度PRD.md', mark: 'M' },
  { name: '机—健康度需求分析.md', mark: 'M' },
]

export function PreviewPage() {
  const [sideCollapsed, setSideCollapsed] = useState(false)

  return (
    <div className="preview-page">
      <div>
        <div className="preview-title">Workspace Shell · 组件预览</div>
        <div className="preview-sub">
          来源 workspace-dna-prototype.html · paper #fff / panel #f6f7f9 / accent #2563eb / ink #1a1d21
        </div>
      </div>

      {/* ---- 完整壳 ---- */}
      <div className="shell">
        <div className="app">
          <Sidebar
            quickNav={QUICK_NAV}
            sections={SECTIONS}
            selectedId="c1"
            userName="陈卓"
            collapsed={sideCollapsed}
            onCollapse={() => setSideCollapsed((v) => !v)}
            onNew={() => {}}
          />
          <main className="main">
            <button
              type="button"
              className="side-toggle"
              title="展开侧栏"
              onClick={() => setSideCollapsed(false)}
            >
              <ChevronRight />
            </button>
            <div className="chat-scroll">
              <div className="chat">{shellChat}</div>
            </div>
            <Composer />
          </main>
          <ProductPanel artifacts={PRODUCT_ARTIFACTS} />
        </div>
      </div>

      {/* ---- 原语画廊 ---- */}
      <div className="gallery">
        <GallerySection title="基础原语">
          <GalleryCell label="IconButton">
            <IconButton title="设置">
              <Settings />
            </IconButton>
          </GalleryCell>
          <GalleryCell label="Avatar sm / md / lg">
            <div className="flex" style={{ gap: 8, alignItems: 'center' }}>
              <Avatar name="陈卓" size="sm" />
              <Avatar name="陈卓" size="md" />
              <Avatar name="陈卓" size="lg" />
            </div>
          </GalleryCell>
          <GalleryCell label="ModelSelect">
            <ModelSelect label="Hy3" />
          </GalleryCell>
        </GallerySection>

        <GallerySection title="侧栏原语">
          <div className="gallery-card">
            <NavRow icon={<BookOpen />} label="知识库" hint="12" />
            <NavRow icon={<Plus />} label="新建任务" active />
            <div className="nav-section" style={{ marginTop: 10 }}>
              <div className="nav-section-title">
                <span>
                  任务（<span className="count">6</span>）
                </span>
                <ChevronDown className="chev" />
              </div>
            </div>
            <NavItem title="Redesign tender re…" meta="14 天前" />
            <NavItem title="Build complete desi…" meta="14 天前" active />
          </div>
          <GalleryCell label="NavSection（默认开）">
            <div className="gallery-card">
              <NavSection title="任务" count={6}>
                <NavItem title="讨论客户端 APP 重写…" meta="3 天前" active />
                <NavItem title="Design page using …" meta="14 天前" />
              </NavSection>
            </div>
          </GalleryCell>
          <GalleryCell label="NavSection（折叠）">
            <div className="gallery-card">
              <NavSection title="任务" count={6} defaultOpen={false}>
                <NavItem title="讨论客户端 APP 重写…" meta="3 天前" />
              </NavSection>
            </div>
          </GalleryCell>
          <GalleryCell label="ChatItem">
            <div className="gallery-card">
              <ChatItem title="讨论客户端 APP 重写方案" meta="3 天前" active />
              <ChatItem title="Design page using Hallmark" meta="14 天前" />
            </div>
          </GalleryCell>
          <GalleryCell label="SpaceCard">
            <div className="gallery-card" style={{ padding: 0, background: 'transparent', border: 'none' }}>
              <SpaceCard title="XXX 标书" meta={<span className="nav-tag">6 个任务</span>}>
                <NavItem title="讨论客户端 APP 重写…" meta="3 天前" active />
                <NavItem title="Design page using …" meta="14 天前" />
              </SpaceCard>
            </div>
          </GalleryCell>
          <GalleryCell label="UserBar">
            <div className="gallery-card" style={{ padding: 0, background: 'var(--panel)', border: '1px solid var(--line)' }}>
              <UserBar
                name="陈卓"
                actions={
                  <IconButton title="设置">
                    <Settings />
                  </IconButton>
                }
              />
            </div>
          </GalleryCell>
        </GallerySection>

        <GallerySection title="过程产物（ProcessArtifact）">
          <GalleryCell label="thinking · 已完成">
            <ProcessArtifact variant="thinking" meta={<>已完成</>}>
              <p>先锁定选型维度，结论倾向 NestJS —— 团队已掌握 TypeScript。</p>
            </ProcessArtifact>
          </GalleryCell>
          <GalleryCell label="thinking · 思考中">
            <ProcessArtifact variant="thinking" meta={<><ArtPulse /> 思考中</>}>
              <p>正在分析…</p>
            </ProcessArtifact>
          </GalleryCell>
          <GalleryCell label="tool · 执行中">
            <ProcessArtifact variant="tool" label="read_table" meta={<Spinner />}>
              <div className="kv">
                <span className="k">source</span>
                <span className="v">知识库 / 框架对比 2026.xlsx</span>
              </div>
            </ProcessArtifact>
          </GalleryCell>
          <GalleryCell label="tool · 成功">
            <ProcessArtifact variant="tool" label="web_search" meta="成功 · 12 条结果">
              <div className="kv">
                <span className="k">query</span>
                <span className="v">投标 技术选型 后端框架 2026 对比</span>
              </div>
              <div className="art-result">已筛选 3 条高相关来源。</div>
            </ProcessArtifact>
          </GalleryCell>
          <GalleryCell label="todo">
            <ProcessArtifact variant="todo" meta="2 / 4 完成">
              <TodoList
                items={[
                  { status: 'done', content: '梳理业务需求与约束' },
                  { status: 'doing', content: '编写对比表' },
                  { status: 'pending', content: '输出结论与建议' },
                ]}
              />
            </ProcessArtifact>
          </GalleryCell>
          <GalleryCell label="search">
            <ProcessArtifact variant="search" meta="3 个匹配">
              <div className="hit">知识库 / 标书模板 / 技术选型.md</div>
            </ProcessArtifact>
          </GalleryCell>
          <GalleryCell label="edit">
            <ProcessArtifact
              variant="edit"
              label="编辑 workspace-dna-prototype.html"
              meta={
                <span className="diff">
                  <span className="plus">+1</span>
                  <span className="minus">-1</span>
                </span>
              }
            >
              <div className="kv">
                <span className="k">path</span>
                <span className="v">/Users/chenzhuo/Documents/WorkBuddy/2026-08-23-17-50-12/workspace-dna-prototype.html</span>
              </div>
              <div className="art-result">已替换 sidebar 文件夹名称为 “XXX 标书”。</div>
            </ProcessArtifact>
          </GalleryCell>
        </GallerySection>

        <GallerySection title="消息">
          <GalleryCell label="user">
            <div className="gallery-card" style={{ width: 420 }}>
              <Message role="user">把候选框架的对比表补进正文。</Message>
            </div>
          </GalleryCell>
          <GalleryCell label="assistant · 已完成">
            <div className="gallery-card" style={{ width: 420 }}>
              <Message role="assistant" name="Hy3" status={<>已完成 · 3 个步骤</>}>
                <div className="bubble">
                  基于以上调研，建议后端采用 <strong>NestJS</strong>：团队已掌握 TypeScript。
                </div>
              </Message>
            </div>
          </GalleryCell>
          <GalleryCell label="assistant · 执行中">
            <div className="gallery-card" style={{ width: 420 }}>
              <Message role="assistant" name="Hy3" status={<>执行中</>}>
                <ProcessArtifact variant="tool" label="read_table" meta={<Spinner />}>
                  <div className="kv">
                    <span className="k">source</span>
                    <span className="v">知识库 / 框架对比 2026.xlsx</span>
                  </div>
                </ProcessArtifact>
                <div className="bubble">正在读取对比表…</div>
              </Message>
            </div>
          </GalleryCell>
        </GallerySection>

        <GallerySection title="输入区">
          <GalleryCell label="Composer">
            <div style={{ border: '1px solid var(--line)', borderRadius: 14, width: '100%' }}>
              <Composer />
            </div>
          </GalleryCell>
        </GallerySection>
      </div>
    </div>
  )
}

function GallerySection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="gallery-section">
      <div className="gallery-title">{title}</div>
      <div className="gallery-row">{children}</div>
    </div>
  )
}

function GalleryCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="gallery-cell">
      <span className="gallery-label">{label}</span>
      {children}
    </div>
  )
}

const shellChat = (
  <>
    <Message role="user">帮我做一份投标技术方案里的技术选型建议，重点对比后端框架。</Message>

    <Message role="assistant" name="Hy3" status={<>已完成 · 3 个步骤</>}>
      <ProcessArtifact variant="thinking" meta={<>已完成</>}>
        <p>先锁定选型维度：团队熟悉度、生态成熟度、性能、长期维护成本。后端方案集中在 NestJS 与 FastAPI 两条线。</p>
        <p>权衡：NestJS 与前端 Vue 同源，协作成本最低；FastAPI 在算法服务上更轻。先把对比框架搭好，再补数据。</p>
        <p>结论倾向 NestJS —— 满足多子系统拆分需求，且团队已掌握 TypeScript。</p>
      </ProcessArtifact>

      <ProcessArtifact variant="todo" meta="2 / 4 完成">
        <TodoList
          items={[
            { status: 'done', content: '梳理业务需求与约束' },
            { status: 'done', content: '列出候选技术栈' },
            { status: 'doing', content: '编写对比表' },
            { status: 'pending', content: '输出结论与建议' },
          ]}
        />
      </ProcessArtifact>

      <ProcessArtifact variant="tool" label="web_search" meta="成功 · 12 条结果">
        <div className="kv">
          <span className="k">query</span>
          <span className="v">投标 技术选型 后端框架 2026 对比</span>
        </div>
        <div className="art-result">已筛选 3 条高相关来源，覆盖 NestJS / FastAPI / Spring Boot 的落地案例与基准测试。</div>
      </ProcessArtifact>

      <div className="bubble">
        基于以上调研，建议后端采用 <strong>NestJS</strong>：团队已掌握 TypeScript，模块化结构适配标书里多子系统的拆分需求，且与前端 Vue 技术栈同源，协作成本最低。
      </div>
    </Message>

    <Message role="user">把候选框架的对比表补进正文。</Message>

    <Message role="assistant" name="Hy3" status={<>执行中</>}>
      <ProcessArtifact variant="tool" label="read_table" meta={<Spinner />}>
        <div className="kv">
          <span className="k">source</span>
          <span className="v">知识库 / 框架对比 2026.xlsx</span>
        </div>
        <div className="art-result">正在读取 3 行 × 5 列，并转换为对比表…</div>
      </ProcessArtifact>

      <ProcessArtifact variant="search" meta="3 个匹配">
        <div className="hit">...-50-12/workspace-dna-prototype.html/ folder|folder-name</div>
        <div className="hit">知识库 / 标书模板 / 技术选型.md</div>
        <div className="hit">产物面板 / 对比表.csv</div>
      </ProcessArtifact>

      <ProcessArtifact
        variant="edit"
        label="编辑 workspace-dna-prototype.html"
        meta={
          <span className="diff">
            <span className="plus">+1</span>
            <span className="minus">-1</span>
          </span>
        }
      >
        <div className="kv">
          <span className="k">path</span>
          <span className="v">/Users/chenzhuo/Documents/WorkBuddy/2026-08-23-17-50-12/workspace-dna-prototype.html</span>
        </div>
        <div className="art-result">已替换 sidebar 文件夹名称为 “XXX 标书”。</div>
      </ProcessArtifact>

      <div className="bubble">已补充对比表：</div>
      <div className="cmp">
        <table>
          <thead>
            <tr>
              <th>维度</th>
              <th>NestJS</th>
              <th>FastAPI</th>
              <th>Spring Boot</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>语言</td>
              <td>TypeScript</td>
              <td>Python</td>
              <td>Java</td>
            </tr>
            <tr>
              <td>学习曲线</td>
              <td>平缓</td>
              <td>平缓</td>
              <td>较陡</td>
            </tr>
            <tr>
              <td>生态</td>
              <td>丰富</td>
              <td>中等</td>
              <td>极丰富</td>
            </tr>
            <tr>
              <td>适配本项目</td>
              <td>优</td>
              <td>良</td>
              <td>中</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Message>
  </>
)
