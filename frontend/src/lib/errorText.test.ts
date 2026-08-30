import { describe, expect, it } from 'vitest'
import { humanizeError } from './errorText'

describe('humanizeError', () => {
  it('已知错误族映射为用户语言', () => {
    expect(humanizeError("Error: Path '/t_efafcdb0d5e2': path_not_found")).toBe('找不到该文件或目录')
    expect(humanizeError('Cannot list /x: not_a_directory')).toBe('目标不是文件夹')
    expect(humanizeError('peer closed connection without sending complete message body (incomplete chunked read)')).toBe(
      '模型连接中断（已自动重试）',
    )
    expect(humanizeError('Error code: 401 - {"message":"invalid api key"}')).toBe('模型凭证无效或未配置')
    expect(humanizeError('Error code: 429 - {"message":"rate limit exceeded"}')).toBe('服务繁忙，请稍后重试')
    expect(humanizeError('Request timed out.')).toBe('请求超时，请重试')
    expect(humanizeError('[写入被拒绝] formal/x：该路径属于产物包保护区')).toBe(
      '该位置受产物保护，请写入工作台或草稿目录',
    )
  })

  it('fetch_url 的 HTTP 401/429（目标网站鉴权/限流）不误映射为模型凭证问题', () => {
    expect(humanizeError('[抓取失败] HTTP 401（example.com）（https://example.com/api）')).toBe(
      '[抓取失败] HTTP 401（example.com）（https://example.com/api）',
    )
    expect(humanizeError('[抓取失败] HTTP 429（example.com）')).toBe('[抓取失败] HTTP 429（example.com）')
  })

  it('未知错误截断原文，空错误回退默认文案', () => {
    expect(humanizeError('某种全新错误')).toBe('某种全新错误')
    expect(humanizeError('a'.repeat(100))).toBe(`${'a'.repeat(80)}…`)
    expect(humanizeError(null, '执行未完成')).toBe('执行未完成')
    expect(humanizeError('   ')).toBe('执行未完成')
  })
})
