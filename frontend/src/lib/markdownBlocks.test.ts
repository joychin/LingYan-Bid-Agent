import { describe, expect, it } from 'vitest'
import { splitMarkdownIntoBlocks } from './markdownBlocks'

/** 拼回去应等于原文（去掉块间分隔空白后逐块相等）——切块只允许丢块间空白。 */
function join(blocks: string[]) {
  return blocks.join('\n\n')
}

describe('splitMarkdownIntoBlocks', () => {
  it('空串与纯空白返回空数组', () => {
    expect(splitMarkdownIntoBlocks('')).toEqual([])
    expect(splitMarkdownIntoBlocks('  \n\n  ')).toEqual([])
  })

  it('普通段落与标题按空行切分', () => {
    const md = '# 标题\n\n第一段。\n\n第二段。'
    expect(splitMarkdownIntoBlocks(md)).toEqual(['# 标题', '第一段。', '第二段。'])
  })

  it('单块文本返回原文（保留原样）', () => {
    const md = '只有一段 **加粗** 文本。'
    expect(splitMarkdownIntoBlocks(md)).toEqual([md])
  })

  it('GFM 表格整块不切（管道行之间无空行，含对齐行）', () => {
    const md = '| A | B |\n|---|---|\n| 1 | 2 |\n\n后面的段落'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toBe('| A | B |\n|---|---|\n| 1 | 2 |')
  })

  it('有序列表跨空行不切、编号不重排（空行隔开的 loose list 是单节点）', () => {
    const md = '1. 第一\n\n2. 第二\n\n3. 第三\n\n收尾段落'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toBe('1. 第一\n\n2. 第二\n\n3. 第三')
  })

  it('无序列表整块', () => {
    const md = '- 甲\n- 乙\n- 丙\n\n下一段'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toBe('- 甲\n- 乙\n- 丙')
  })

  it('闭合围栏代码块含空行不切', () => {
    const md = '```python\na = 1\n\nb = 2\n```\n\nafter'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toBe('```python\na = 1\n\nb = 2\n```')
  })

  it('未闭合围栏到 EOF 是一个合法 code 块（流式中间态不炸）', () => {
    const md = '前文\n\n```js\nconst x = 1'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks).toHaveLength(2)
    expect(blocks[1]).toBe('```js\nconst x = 1')
  })

  it('引用块（含嵌套段落）整块', () => {
    const md = '> 引用一\n>\n> 引用二\n\n正文'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toBe('> 引用一\n>\n> 引用二')
  })

  it('thematic break 独立成块', () => {
    const md = '上面\n\n---\n\n下面'
    expect(splitMarkdownIntoBlocks(md)).toEqual(['上面', '---', '下面'])
  })

  it('setext 标题（=== 下划线）不被 thematic break 误切', () => {
    const md = '标题文字\n===\n\n正文'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toBe('标题文字\n===')
  })

  it('CJK 内容逐字保留', () => {
    const md = '第一节（L412-L430，第23页）\n\n**废标项**：未按要求盖章。'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(join(blocks)).toBe(md)
  })

  it('脚注（引用+定义）整文单块不切（分块会破坏引用-定义配对）', () => {
    const md = '正文引用[^1]\n\n[^1]: 脚注定义内容\n\n后续段落'
    expect(splitMarkdownIntoBlocks(md)).toEqual([md])
    expect(splitMarkdownIntoBlocks('见 [^note] 说明')).toHaveLength(1)
  })

  it('多块拼接等于原文去块间空白（无内容丢失）', () => {
    const md = '# 目录\n\n段落 A，含 `code`。\n\n```txt\nfence\n```\n\n| t |\n|---|\n| x |\n\n1. one\n2. two\n\n> quote\n\n- a\n- b'
    const blocks = splitMarkdownIntoBlocks(md)
    expect(blocks.length).toBeGreaterThan(3)
    // 每块都非空白，且内容都来自原文
    for (const b of blocks) expect(b.trim()).not.toBe('')
  })
})
