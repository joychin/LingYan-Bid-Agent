import { memo, useEffect, useState } from 'react'

/**
 * 知识库图片：img 标签带不了 Authorization，经鉴权 fetch blob 后展示。
 * 加载失败（缺失/解码不支持）渲染占位态而不是裸 alt 文字。
 */
export const KbImage = memo(function KbImage({
  itemId,
  imagePath,
  alt,
  className,
}: {
  itemId: string
  imagePath: string
  alt: string
  className?: string
}) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    let objectUrl: string | null = null
    setUrl(null)
    setFailed(false)
    void (async () => {
      try {
        const { getSidecarInfo } = await import('@/api/client')
        const { baseURL, token } = await getSidecarInfo()
        const resp = await fetch(`${baseURL}/api/kb/items/${itemId}/images/${imagePath}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (!resp.ok) {
          if (alive) setFailed(true)
          return
        }
        const blob = await resp.blob()
        // 卸载发生在 blob 到达前时不再创建 objectURL：cleanup 已执行过，之后再创建
        // 的 URL 无人 revoke（快速滚动图片清单时的泄漏窗口）
        if (!alive) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      } catch {
        if (alive) setFailed(true)
      }
    })()
    return () => {
      alive = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [itemId, imagePath])

  if (failed)
    return (
      <div className={className ? `${className} kb-img-failed` : 'kb-img-failed'}>
        图片无法加载{imagePath ? `（.${imagePath.split('.').pop()}）` : ''}
      </div>
    )
  if (!url) return <div className={className ? `${className} kb-img-loading` : 'kb-img-loading'} />
  return <img src={url} alt={alt} className={className} onError={() => setFailed(true)} />
})
