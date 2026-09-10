/**
 * 目录树编辑纯函数库（2026-09-04 批次 4）：跨层级移动 / 升降级 / 结构签名。
 * 全部操作直接改写传入的 draft（调用方 mutate 负责 structuredClone 副本），
 * 返回 boolean 表示操作是否成立（非法移动如拖入自身后代返回 false）。
 * 层级封顶 5 级（投标目录超过 5 层无写作意义）。
 */

export interface EditNode {
  目录名称: string
  level: number
  children?: EditNode[]
  来源?: string[]
  来源位置?: string[]
  交付形态?: string
  归位理由?: string
  理由来源?: string[]
  节点概述?: string
  _id?: string
}

export interface EditDoc {
  name?: string
  scope?: string
  directory?: EditNode[]
}

/** tender.directory 编辑态数据形状（查看/编辑共用节点类型；registry/meta 等
 *  非树字段原样保留）。契约模型见 sidecar contracts/tender_directory.py。 */
export interface DirectoryData {
  response_documents?: EditDoc[]
  registry?: Record<string, { type?: string; text?: string; 出处?: string }>
  meta?: Record<string, string>
  lineage_check?: { unused_ids?: string[]; dangling_ids?: string[] }
  warning?: string
  /** 章节编号格式（合册按目录树序自动编号时读取；缺省 chapter=第X章+1.1） */
  numbering?: 'chapter' | 'decimal' | 'gov' | 'none'
}

export const MAX_LEVEL = 5

export interface NodeAddr {
  list: EditNode[]
  index: number
}

export function findInList(list: EditNode[], id: string): NodeAddr | null {
  for (let i = 0; i < list.length; i++) {
    if (list[i]._id === id) return { list, index: i }
    if (list[i].children?.length) {
      const r = findInList(list[i].children!, id)
      if (r) return r
    }
  }
  return null
}

export function findInDocs(docs: EditDoc[], id: string): NodeAddr | null {
  for (const doc of docs) {
    const r = findInList(doc.directory ?? [], id)
    if (r) return r
  }
  return null
}

/** 父节点（根级 parent=null 含分册索引）；节点不存在返回 null。 */
export function findParent(docs: EditDoc[], id: string): { parent: EditNode | null; docIndex: number } | null {
  // 返回 undefined=子树未命中；null=命中且是根级；其他=命中且的直接父节点
  const direct = (list: EditNode[], parent: EditNode | null): EditNode | null | undefined => {
    for (const n of list) {
      if (n._id === id) return parent
      if (n.children?.length) {
        const r = direct(n.children!, n)
        if (r !== undefined) return r
      }
    }
    return undefined
  }
  for (let i = 0; i < docs.length; i++) {
    const r = direct(docs[i].directory ?? [], null)
    if (r !== undefined) return { parent: r, docIndex: i }
  }
  return null
}

/** node 是否 ancestor 的严格后代（不含自身）。 */
export function isDescendant(docs: EditDoc[], ancestorId: string, nodeId: string): boolean {
  if (ancestorId === nodeId) return false
  const a = findInDocs(docs, ancestorId)
  if (!a) return false
  return findInList(a.list[a.index].children ?? [], nodeId) !== null
}

/** 整子树 level 重算（移动/升降级后调用）。 */
export function relevel(node: EditNode, level: number): void {
  node.level = level
  for (const c of node.children ?? []) relevel(c, level + 1)
}

export type DropPos = 'above' | 'below' | 'inside'

/**
 * 跨层级移动（拖拽三落点）：above/below=插到目标同级的前/后（level 对齐目标）；
 * inside=成为目标的最后一个子节点。非法（拖入自身后代 / inside 超层级封顶）返回 false。
 */
export function moveTo(docs: EditDoc[], dragId: string, targetId: string, pos: DropPos): boolean {
  if (dragId === targetId) return false
  if (isDescendant(docs, dragId, targetId)) return false
  const from = findInDocs(docs, dragId)
  const to = findInDocs(docs, targetId)
  if (!from || !to) return false
  const target = to.list[to.index]
  if (pos === 'inside') {
    if (target.level >= MAX_LEVEL) return false
    const [node] = from.list.splice(from.index, 1)
    target.children = target.children ?? []
    target.children.push(node)
    relevel(node, target.level + 1)
    return true
  }
  const [node] = from.list.splice(from.index, 1)
  // splice 后目标索引可能位移；按 _id 重新定位
  const to2 = findInDocs(docs, targetId)
  if (!to2) return false
  to2.list.splice(to2.index + (pos === 'below' ? 1 : 0), 0, node)
  relevel(node, target.level)
  return true
}

/** 升级：上移一层，插到父节点在祖父列表中的位置之后。根级不可升级。 */
export function promote(docs: EditDoc[], id: string): boolean {
  const addr = findInDocs(docs, id)
  if (!addr) return false
  const node = addr.list[addr.index]
  if (node.level <= 1) return false
  const fp = findParent(docs, id)
  if (!fp || !fp.parent) return false
  const parentAddr = findInDocs(docs, fp.parent._id!)
  if (!parentAddr) return false
  const [n] = addr.list.splice(addr.index, 1)
  parentAddr.list.splice(parentAddr.index + 1, 0, n)
  relevel(n, n.level - 1)
  return true
}

/** 降级：成为前一个同级的最后一个子节点。无前同级 / 超封顶不可。 */
export function demote(docs: EditDoc[], id: string): boolean {
  const addr = findInDocs(docs, id)
  if (!addr) return false
  if (addr.index === 0) return false
  const prev = addr.list[addr.index - 1]
  if (prev.level >= MAX_LEVEL) return false
  const [n] = addr.list.splice(addr.index, 1)
  prev.children = prev.children ?? []
  prev.children.push(n)
  relevel(n, prev.level + 1)
  return true
}

/**
 * 结构签名（结构性变更检测用）：每个节点的分册内索引路径集合。
 * 增删/移动 → 集合变化；纯改名/概述编辑 → 不变（确认条不误报）。
 */
export function structureSignature(docs: EditDoc[]): string {
  const paths: string[] = []
  const walk = (list: EditNode[], prefix: string) => {
    list.forEach((n, i) => {
      const p = `${prefix}/${i}`
      paths.push(p)
      if (n.children?.length) walk(n.children, p)
    })
  }
  docs.forEach((d, di) => walk(d.directory ?? [], `d${di}`))
  return paths.join('|')
}
