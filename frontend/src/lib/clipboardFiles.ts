/**
 * 剪贴板粘贴文件的改名（InputComposer 粘贴上传路径专用）。
 *
 * 浏览器粘贴截图/图片时自动命名的通用名（image.png 等）没有区分度，而任务文件
 * API 是「任务内同名覆盖」语义（重传新版覆盖旧版，有意设计）——不改名的连贴会
 * 互相覆盖（两张不同截图只剩最后一张）。粘贴路径在前端改名保共存；Finder 复制
 * 粘贴的真实文件名保持原名（与拖拽/文件选择器同语义，重传覆盖仍可用）。
 */

/** 各浏览器粘贴图片的自动命名（大小写不敏感匹配；unknown=个别环境无名的兜底名） */
const GENERIC_CLIPBOARD_NAMES = new Set([
  'image.png',
  'image.jpg',
  'image.jpeg',
  'image.gif',
  'image.webp',
  'image.bmp',
  'image.tiff',
  'unknown',
])

/** 批内重名加序号（素材库 unique_file_path 同款「name (2)」形态） */
function dedupe(name: string, used: Set<string>): string {
  if (!used.has(name)) return name
  const dot = name.lastIndexOf('.')
  const stem = dot >= 0 ? name.slice(0, dot) : name
  const ext = dot >= 0 ? name.slice(dot) : ''
  let i = 2
  while (used.has(`${stem} (${i})${ext}`)) i++
  return `${stem} (${i})${ext}`
}

const pad = (n: number) => String(n).padStart(2, '0')

/**
 * 纯函数改名：通用剪贴板名 → 「截图 YYYY-MM-DD HH.mm.ss.ext」（时间用点分隔，
 * 冒号在 Windows 文件名非法）；真名/非通用名原样返回；批内重名加序号。
 * now 由调用方注入（可测）。
 */
export function renameClipboardNames(names: string[], now: Date): string[] {
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}.${pad(now.getMinutes())}.${pad(now.getSeconds())}`
  const used = new Set<string>()
  return names.map((raw) => {
    let name = raw || 'image.png'
    if (GENERIC_CLIPBOARD_NAMES.has(name.toLowerCase())) {
      const dot = name.lastIndexOf('.')
      const ext = dot >= 0 ? name.slice(dot) : ''
      name = `截图 ${stamp}${ext}`
    }
    name = dedupe(name, used)
    used.add(name)
    return name
  })
}

/** 粘贴路径入口：File.name 只读，经 File 构造器按新名重包（blob 引用不变）。 */
export function renameClipboardFiles(files: File[], now: Date = new Date()): File[] {
  const names = renameClipboardNames(
    files.map((f) => f.name),
    now,
  )
  return files.map(
    (f, i) =>
      new File([f], names[i], {
        type: f.type,
        lastModified: f.lastModified,
      }),
  )
}
