import { describe, expect, it } from 'vitest'
import {
  TOOL_DISPLAY,
  skillFileInfo,
  skillStepTitle,
  stepArgLabel,
  subagentStepTitle,
  toolDisplayName,
  toolIcon,
} from './toolDisplay'

describe('skillFileInfo（技能读取判据）', () => {
  it('实测五种路径拼写都能识别（带/不带前导斜杠、带/不带任务前缀）', () => {
    const paths = [
      'skills/tender-analysis/SKILL.md',
      '/skills/tender-analysis/SKILL.md',
      't_754abc/skills/tender-analysis/SKILL.md',
      '/workspace/t_754abc/skills/tender-analysis/SKILL.md',
      '/workspace/skills/tender-body/references/section-writing.md',
    ]
    for (const p of paths) {
      expect(skillFileInfo(p)?.skill, `未识别：${p}`).toBeTruthy()
    }
  })

  it('技能名与文件名分别提取，_shared 也认（shared-rules 历史残留同样命中）', () => {
    expect(skillFileInfo('skills/tender-body/references/section-writing.md')).toEqual({
      skill: 'tender-body',
      label: '正文写作',
      file: 'references/section-writing.md',
    })
    expect(skillFileInfo('skills/_shared/response-guidelines.md')?.label).toBe('共享规范')
  })

  it('未收录技能回退目录名（新增技能不丢信息）', () => {
    expect(skillFileInfo('skills/brand-new-skill/SKILL.md')).toEqual({
      skill: 'brand-new-skill',
      label: 'brand-new-skill',
      file: 'SKILL.md',
    })
  })

  it('非技能路径与坏入参返回 null', () => {
    expect(skillFileInfo('t_x/work/parse/a.docx.md')).toBeNull()
    expect(skillFileInfo('/workspace/t_x/work/body/封面.docx')).toBeNull()
    expect(skillFileInfo(undefined)).toBeNull()
    expect(skillFileInfo(42)).toBeNull()
    // 目录名恰好含 skill 但不在 skills/ 段下，不算技能读取
    expect(skillFileInfo('t_x/work/my-skills.md')).toBeNull()
  })
})

describe('skillStepTitle', () => {
  it('SKILL.md 只报技能名，参考文件附文件名主干（不裸露 references/ 路径）', () => {
    expect(skillStepTitle({ label: '投标分析', file: 'SKILL.md' })).toBe('投标分析')
    expect(skillStepTitle({ label: '正文写作', file: 'references/section-writing.md' })).toBe(
      '正文写作 · section-writing',
    )
  })
})

describe('技能读取的显示名/图标/参数（toolDisplayName·toolIcon·stepArgLabel）', () => {
  it('read_file 指向技能目录 → 语义化为「加载技能」+ BookOpen', () => {
    const args = { file_path: 'skills/tender-analysis/SKILL.md' }
    expect(toolDisplayName('read_file', args)).toBe('加载技能：投标分析')
    expect(toolIcon('read_file', args)).toBe(toolIcon('read_file', args)) // 引用稳定
    expect(toolIcon('read_file', args)).not.toBe(toolIcon('read_file', { file_path: 't_x/a.md' }))
  })

  it('普通文件读取维持原显示，不误判', () => {
    expect(toolDisplayName('read_file', { file_path: 't_x/work/parse/a.docx.md' })).toBe('读取文件')
    expect(toolDisplayName('read_file')).toBe('读取文件')
    expect(toolDisplayName('write_file', { file_path: 'skills/x/SKILL.md' })).toBe('写入文件')
  })

  it('参数行报技能名+文件主干，不裸露内部路径', () => {
    expect(stepArgLabel('read_file', { file_path: 'skills/tender-body/SKILL.md' })).toBe('正文写作')
    expect(
      stepArgLabel('read_file', { file_path: 'skills/tender-body/references/guide-format.md' }),
    ).toBe('正文写作 · guide-format')
    // 非技能路径维持原样（关键参数行本就是路径）
    expect(stepArgLabel('read_file', { file_path: 't_x/work/parse/a.docx.md' })).toBe(
      't_x/work/parse/a.docx.md',
    )
  })
})

describe('subagentStepTitle', () => {
  it('提示词纪律：首行 ≤24 字短名直接用作标题', () => {
    expect(
      subagentStepTitle({ description: '检索中石化 dify 相关招标\n在网上查找类似的招标公告，重点收集……' }),
    ).toBe('检索中石化 dify 相关招标')
  })

  it('无短名约定的首行按句读截第一句', () => {
    expect(subagentStepTitle({ description: '分析评分办法并提取废标条款。评分细节见第二行' })).toBe(
      '分析评分办法并提取废标条款。',
    )
  })

  it('第一句仍超 16 字硬截加省略号', () => {
    expect(subagentStepTitle({ description: '这是一段非常长的描述没有句读超过二十四个字符的测试文本继续写' })).toBe(
      '这是一段非常长的描述没有句读超过…',
    )
  })

  it('恰 16 字不截断（短名在第一行，详细任务从第二行起）', () => {
    const name = '一二三四五六七八九十一二三四五六'
    expect(name).toHaveLength(16)
    expect(subagentStepTitle({ description: `${name}\n第二行起是详细任务说明` })).toBe(name)
  })

  it('句读出现在行首 2 字内（「1.」编号）不按句读截', () => {
    expect(subagentStepTitle({ description: '1. 先检索中石化相关招标' })).toBe('1. 先检索中石化相关招标')
  })

  it('缺 description 回退 subagent_type，都缺返回空串', () => {
    expect(subagentStepTitle({ subagent_type: 'tender-outline-writer' })).toBe('tender-outline-writer')
    expect(subagentStepTitle({ description: '   ', subagent_type: 'tender-outline-writer' })).toBe(
      'tender-outline-writer',
    )
    expect(subagentStepTitle({ description: 42 })).toBe('')
    expect(subagentStepTitle()).toBe('')
  })

  it('空短名时调用方回退通用显示名', () => {
    expect(subagentStepTitle() || toolDisplayName('task')).toBe('派发子代理')
  })
})

describe('TOOL_DISPLAY 覆盖率', () => {
  // 冻结镜像：sidecar/app/tools/__init__.py 的 TOOLS 注册表（新增工具须双侧同步，
  // 漏配中文名=过程区直接显示英文原码，此测试即红）
  const SIDECAR_TOOLS = [
    'parse_document',
    'assemble_tender',
    'ask_human',
    'publish_artifact',
    'read_artifact',
    'search_company_assets',
    'search_references',
    'check_name_residue',
    'check_pipeline_state',
    'list_templates',
    'validate_analysis',
    'validate_body',
    'update_task_progress',
    'fetch_url',
    'docx_section_create',
    'docx_section_read',
    'docx_material_inject',
    'docx_source_inject',
    'docx_image_insert',
    'docx_comment_add',
    'docx_section_revise',
    'docx_assemble_volume',
  ]

  it('sidecar 全部注册工具有中文显示名（过程区不漏英文原码）', () => {
    for (const tool of SIDECAR_TOOLS) {
      expect(TOOL_DISPLAY[tool], `工具 ${tool} 缺中文名映射`).toBeTruthy()
    }
  })
})
