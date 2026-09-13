/**
 * workbenchTable 纯函数测试。金样例字符串与 sidecar
 * tests/test_workbench_table_contract.py 双侧同源——前端序列化格式 ⊆ Python
 * 解析能力的跨语言契约由两侧测试共同锁住，任一侧漂移会红。
 */

import { describe, expect, it } from 'vitest'
import type { EditDoc } from '@/components/processors/directoryTree'
import {
  GUIDE_TABLE,
  GUIDE_MODES,
  PROMISE_TABLE,
  blockPreviewText,
  guideRowFlags,
  guideRowMatches,
  iterLeaves,
  leafKey,
  leafGroups,
  multiVolume,
  normRefId,
  orderBodyRows,
  parseBlockRefs,
  parseGuideNote,
  parseModeTokens,
  parseRefIds,
  parseTableFile,
  sanitizeCell,
  sanitizeName,
  serializeTableFile,
  sortRefIds,
  writtenSections,
  writtenPathOf,
} from './workbenchTable'

/** 金样例：与 sidecar test_workbench_table_contract.py 的 GUIDE_GOLDEN 逐字节一致。 */
const GUIDE_GOLDEN = [
  '# 写作指引',
  '',
  '| 节 | 模式 | 依据 | 素材 | 缺口/备注 |',
  '|---|---|---|---|---|',
  '| 3.1 项目理解与需求分析 | 素材修订 | REQ-01、REQ-07 | blk_0123456789ab | — |',
  '| 3.2 总体设计方案 | 素材修订+推理撰写 | SCORE-02 | 【缺】 | 缺：总体方案素材 |',
  '| 3.3 项目团队配置 | 推理撰写 | — | 【缺】 | 缺：人员证书扫描件 |',
  '| 投标函 | — | MAND-03 | — | 格式件：拷原件+revise 填空 |',
  '',
].join('\n')

const PROMISE_GOLDEN = [
  '# 关键事实与承诺',
  '',
  '| 事项 | 值 | 说明 |',
  '|---|---|---|',
  '| 项目名称 | 测试项目 | 招标文件封面用 |',
  '| 免费维护期 | 3 年 | 招标要求 |',
  '',
].join('\n')

describe('parseTableFile', () => {
  it('金样例解析：行数/列投影', () => {
    const p = parseTableFile(GUIDE_GOLDEN, GUIDE_TABLE)
    expect(p).not.toBeNull()
    expect(p!.preamble).toEqual(['# 写作指引', ''])
    expect(p!.postamble).toEqual([''])
    expect(p!.rows.map((r) => r[0])).toEqual([
      '3.1 项目理解与需求分析',
      '3.2 总体设计方案',
      '3.3 项目团队配置',
      '投标函',
    ])
    expect(p!.rows[1][1]).toBe('素材修订+推理撰写')
    expect(p!.rows[0][3]).toBe('blk_0123456789ab')
  })

  it('宽容解析：表头列序变化仍按列名取值', () => {
    const variant = [
      '| 模式 | 节 | 素材 | 依据 | 缺口/备注 |',
      '|---|---|---|---|---|',
      '| 推理撰写 | 3.3 团队 | 【缺】 | REQ-01 | — |',
    ].join('\n')
    const p = parseTableFile(variant, GUIDE_TABLE)
    expect(p).not.toBeNull()
    expect(p!.rows[0]).toEqual(['3.3 团队', '推理撰写', 'REQ-01', '【缺】', '—'])
  })

  it('宽容解析：表头缺「缺口/备注」列名时按下标兜底（sidecar idx.get 同款）', () => {
    const variant = [
      '| 节 | 模式 | 依据 | 素材 | 备注 |',
      '|---|---|---|---|---|',
      '| 3.1 需求 | 素材修订 | REQ-01 | blk_0123456789ab | 备注X |',
    ].join('\n')
    const p = parseTableFile(variant, GUIDE_TABLE)
    expect(p!.rows[0][4]).toBe('备注X')
  })

  it('首列为空的行跳过；块内第二行不计数据', () => {
    const variant = [
      '| 节 | 模式 | 依据 | 素材 | 缺口/备注 |',
      '|---|---|---|---|---|',
      '|  | 推理撰写 | — | — | — |',
      '| 3.1 需求 | 推理撰写 | — | — | — |',
    ].join('\n')
    expect(parseTableFile(variant, GUIDE_TABLE)!.rows).toHaveLength(1)
  })

  it('无表 / 表头缺必需列 / 多张合格表 → null（落回源码模式的判据）', () => {
    expect(parseTableFile('没有表格的纯文本。', GUIDE_TABLE)).toBeNull()
    expect(
      parseTableFile('| 其他 | 表头 |\n|---|---|\n| a | b |', GUIDE_TABLE),
    ).toBeNull()
    const two = GUIDE_GOLDEN + '\n| 节 | 模式 |\n|---|---|\n| x | y |\n'
    expect(parseTableFile(two, GUIDE_TABLE)).toBeNull()
  })

  it('修订注释行（服务端盖的「修订=用户」）在 preamble 原样保留', () => {
    const stamped = `<!-- 工作文件 | 修订=用户 2026-09-08T12:00:00Z -->\n${GUIDE_GOLDEN}`
    const p = parseTableFile(stamped, GUIDE_TABLE)
    expect(p!.preamble[0]).toContain('修订=用户')
  })

  it('表后还有正文时 postamble 保留', () => {
    const withTail = GUIDE_GOLDEN + '补充说明：以上按评分项逐节响应。\n'
    const p = parseTableFile(withTail, GUIDE_TABLE)
    expect(p!.postamble).toEqual(['补充说明：以上按评分项逐节响应。', ''])
  })
})

describe('serializeTableFile（金样例往返字节稳定）', () => {
  it('解析→序列化 === 原文（指引/承诺）', () => {
    expect(serializeTableFile(parseTableFile(GUIDE_GOLDEN, GUIDE_TABLE)!, GUIDE_TABLE)).toBe(GUIDE_GOLDEN)
    expect(serializeTableFile(parseTableFile(PROMISE_GOLDEN, PROMISE_TABLE)!, PROMISE_TABLE)).toBe(PROMISE_GOLDEN)
  })

  it('空单元格写「—」；换行剥除、半角竖线替全角（防拆表）', () => {
    const md = serializeTableFile(
      { preamble: [], postamble: [], rows: [['3.1 需求', '', 'REQ-01', '', 'a|b\nc']] },
      GUIDE_TABLE,
    )
    expect(md).toContain('| 3.1 需求 | — | REQ-01 | — | a｜b c |')
    // 序列化产物必须能被自己重新解析（编辑循环闭环）
    expect(parseTableFile(md, GUIDE_TABLE)!.rows[0]).toEqual(['3.1 需求', '—', 'REQ-01', '—', 'a｜b c'])
  })
})

describe('单元格工具', () => {
  it('模式 token：+ 组合 / — / 未知原样', () => {
    expect(parseModeTokens('素材修订+推理撰写')).toEqual(['素材修订', '推理撰写'])
    expect(parseModeTokens('—')).toEqual(['—'])
    expect(parseModeTokens('')).toEqual([])
    expect(parseModeTokens('自创模式')).toEqual(['自创模式'])
    expect(GUIDE_MODES).toEqual(['素材修订', '格式跟随', '推理撰写'])
  })

  it('依据 id：顿号/逗号/分号/空白切分 + 补零归一化 + 杂质分离', () => {
    expect(parseRefIds('REQ-01、REQ-07')).toEqual({ ids: ['REQ-01', 'REQ-07'], rest: '' })
    expect(parseRefIds('mand-3,SCORE-2')).toEqual({ ids: ['MAND-03', 'SCORE-02'], rest: '' })
    const mixed = parseRefIds('REQ-1 按评分项 req-2')
    expect(mixed.ids).toEqual(['REQ-01', 'REQ-02'])
    expect(mixed.rest).toBe('按评分项')
  })

  it('素材列：blk 提取（行内去重）+【缺】+ 其余文本', () => {
    expect(parseBlockRefs('blk_0123456789ab、blk_0123456789ab')).toEqual({
      blockIds: ['blk_0123456789ab'],
      missing: false,
      rest: '',
    })
    expect(parseBlockRefs('【缺】')).toEqual({ blockIds: [], missing: true, rest: '' })
    expect(parseBlockRefs('blk_0123456789ab 与 blk_ffffffffffff')).toEqual({
      blockIds: ['blk_0123456789ab', 'blk_ffffffffffff'],
      missing: false,
      rest: '与',
    })
    // 大写 hex 不是合法块 id（与 sidecar 正则一致）
    expect(parseBlockRefs('blk_ABCDEFABCDEF').blockIds).toEqual([])
  })

  it('normRefId 数字补零两位', () => {
    expect(normRefId('req-1')).toBe('REQ-01')
    expect(normRefId('REQ-12')).toBe('REQ-12')
  })

  it('sanitizeCell 空值统一「—」', () => {
    expect(sanitizeCell('')).toBe('—')
    expect(sanitizeCell(undefined)).toBe('—')
    expect(sanitizeCell(' 值 ')).toBe('值')
  })
})

describe('parseGuideNote（缺口/备注列读者分离，2026-09-13）', () => {
  it('真实身份证明行：工具名+行号落 rest，【缺】单独成条', () => {
    const p = parseGuideNote(
      '格式件：docx_source_inject 拷第五章格式（L988-L1005）+revise 填应征人名称、单位性质、地址、成立时间、'
        + '经营期限、法定代表人姓名/性别/年龄/职务，并粘贴身份证正反面复印件【缺：上述公司信息与法定代表人身份证复印件】',
    )
    expect(p.gaps).toEqual(['上述公司信息与法定代表人身份证复印件'])
    expect(p.knowledge).toEqual([])
    expect(p.clarifies).toEqual([])
    expect(p.rest).toBe(
      '格式件：docx_source_inject 拷第五章格式（L988-L1005）+revise 填应征人名称、单位性质、地址、成立时间、'
        + '经营期限、法定代表人姓名/性别/年龄/职务，并粘贴身份证正反面复印件',
    )
  })

  it('真实公司介绍行：知识库命中 / 工具句 / 缺口 三者分离且不吞字', () => {
    const p = parseGuideNote(
      '【知识库】ISO9001 质量管理体系认证证书：注册号 0350324Q30696R1M，有效期最长可至 2027 年'
        + '（含图 1 张，贴图路径 knowledge/parse/1、ISO9001中文证书(存档)/images/img_001.png）；'
        + '拷素材后必用 check_name_residue 扫旧名残留；【缺：营业执照信息、注册地址/成立时间、近三年财务概况】',
    )
    expect(p.knowledge).toEqual([
      'ISO9001 质量管理体系认证证书：注册号 0350324Q30696R1M，有效期最长可至 2027 年'
        + '（含图 1 张，贴图路径 knowledge/parse/1、ISO9001中文证书(存档)/images/img_001.png）',
    ])
    expect(p.gaps).toEqual(['营业执照信息、注册地址/成立时间、近三年财务概况'])
    // 工具句留在 rest（不丢内容），边界分隔符清理干净
    expect(p.rest).toBe('拷素材后必用 check_name_residue 扫旧名残留')
  })

  it('待澄清段独立成条（剥 ⚠ 与 CLAR 编号保留）；rest 里的中间分号保留', () => {
    const p = parseGuideNote(
      '格式件：docx_source_inject 拷第五章进度计划格式（L1221-L1244）+revise 填工程进度与时间安排；'
        + '总工期以项目签署后 6 个月内完成全功能开发上线为准；'
        + '⚠待澄清 CLAR-04：合同格式附件一「项目清单」为空、交付里程碑不可获得【缺：进度节点与时间安排（取承诺清单）】',
    )
    expect(p.clarifies).toEqual(['待澄清 CLAR-04：合同格式附件一「项目清单」为空、交付里程碑不可获得'])
    expect(p.gaps).toEqual(['进度节点与时间安排（取承诺清单）'])
    expect(p.rest).toBe(
      '格式件：docx_source_inject 拷第五章进度计划格式（L1221-L1244）+revise 填工程进度与时间安排；'
        + '总工期以项目签署后 6 个月内完成全功能开发上线为准',
    )
  })

  it('【缺：X】——解释 归入同一条（缺项与其原因的常见写法）', () => {
    const p = parseGuideNote(
      '以《航天科工案例》素材块为业绩叙述底稿；【缺：券商相关行业项目合同扫描件】'
        + '——评审实施案例 3 分仅券商行业案例得分，需用户提供案例清单',
    )
    expect(p.gaps).toEqual([
      '券商相关行业项目合同扫描件——评审实施案例 3 分仅券商行业案例得分，需用户提供案例清单',
    ])
    expect(p.rest).toBe('以《航天科工案例》素材块为业绩叙述底稿')
  })

  it('旧格式裸「缺：xxx」不强行摘、落 rest（存量指引兼容）', () => {
    const p = parseGuideNote('缺：总体方案素材')
    expect(p.gaps).toEqual([])
    expect(p.rest).toBe('缺：总体方案素材')
  })

  it('防御：裸【缺】给泛化缺项，不静默消失', () => {
    expect(parseGuideNote('【缺】')).toEqual({
      gaps: ['（指引未列出具体缺项）'],
      knowledge: [],
      clarifies: [],
      rest: '',
      anaphora: false,
    })
  })

  it('代词回指标记：anaphora=true（渲染层据此默认展开执行说明）', () => {
    const hit = parseGuideNote(
      '格式件：docx_source_inject 拷第五章格式（L988-L1005）【缺：上述公司信息与法定代表人身份证复印件】',
    )
    expect(hit.anaphora).toBe(true)
    const miss = parseGuideNote('【缺：公司全称、注册地址、成立时间】')
    expect(miss.anaphora).toBe(false)
    // 正常措辞「本项目/本文」不误判
    expect(parseGuideNote('【缺：本项目业绩合同扫描件】').anaphora).toBe(false)
  })

  it('空 / — / 纯文本备注：不产生条目', () => {
    expect(parseGuideNote('')).toEqual({ gaps: [], knowledge: [], clarifies: [], rest: '', anaphora: false })
    expect(parseGuideNote('—')).toEqual({ gaps: [], knowledge: [], clarifies: [], rest: '', anaphora: false })
    const plain = parseGuideNote('索引表（自行编制，招标无样例）：按第三章详细评审 5 个评审因素逐项列示')
    expect(plain.gaps).toEqual([])
    expect(plain.rest).toBe('索引表（自行编制，招标无样例）：按第三章详细评审 5 个评审因素逐项列示')
  })

  it('多条缺口各成一项；纯缺口行的 rest 为空白串', () => {
    const p = parseGuideNote('【缺：应征人全称】【缺：法定代表人姓名】')
    expect(p.gaps).toEqual(['应征人全称', '法定代表人姓名'])
    expect(p.rest).toBe('')
  })
})

describe('叶子匹配（body_contract 移植）', () => {
  const docs: EditDoc[] = [
    {
      name: '技术部分',
      directory: [
        {
          目录名称: '第三章',
          level: 1,
          children: [
            { 目录名称: '3.1 项目理解与需求分析', level: 2, children: [], 交付形态: '正文编写' },
            { 目录名称: '3.2:总体*方案?', level: 2, children: [], 交付形态: '混合' },
          ],
        },
      ],
    },
    {
      name: '商务部分',
      directory: [{ 目录名称: '投标函', level: 1, children: [], 交付形态: '模板或附件填充' }],
    },
  ]

  it('iterLeaves：叶子+册名缺省主册；multiVolume 判定；leafKey 复合', () => {
    const single = [{ name: '', directory: docs[0].directory }]
    expect(multiVolume(single)).toBe(false)
    const ls = iterLeaves(single)
    // 「第三章」容器不下沉为叶子，叶子 = 3.1/3.2
    expect(ls).toHaveLength(2)
    expect(ls[0]).toEqual({
      vol: '主册',
      title: '3.1 项目理解与需求分析',
      delivery: '正文编写',
      overview: '',
      reason: '',
    })
    expect(leafKey(ls[0].vol, ls[0].title, false)).toBe('3.1 项目理解与需求分析')

    expect(multiVolume(docs)).toBe(true)
    expect(leafKey('商务部分', '投标函', true)).toBe('商务部分/投标函')
  })

  it('iterLeaves：带出节点概述/归位理由（行内内容行数据源）；空白 trim、缺省空串', () => {
    const withMeta: EditDoc[] = [
      {
        name: '',
        directory: [
          {
            目录名称: '第三章 落实方案',
            level: 1,
            children: [
              {
                目录名称: '3.1 项目理解',
                level: 2,
                children: [],
                节点概述: ' 阐述总体技术路线与架构 ',
                归位理由: '招标方要求说明对需求的理解',
              },
              { 目录名称: '3.2 总体设计', level: 2, children: [] },
            ],
          },
        ],
      },
    ]
    const ls = iterLeaves(withMeta)
    expect(ls[0]).toEqual({
      vol: '主册',
      title: '3.1 项目理解',
      delivery: '',
      overview: '阐述总体技术路线与架构',
      reason: '招标方要求说明对需求的理解',
    })
    expect(ls[1]).toEqual({ vol: '主册', title: '3.2 总体设计', delivery: '', overview: '', reason: '' })
  })

  it('blockPreviewText：空输入 → 空串；只取首个 section', () => {
    expect(blockPreviewText(undefined, 120)).toBe('')
    expect(blockPreviewText([], 120)).toBe('')
    expect(blockPreviewText([{ text: '   \n  ' }], 120)).toBe('')
    expect(blockPreviewText([{ text: '第一段' }, { text: '第二段' }], 120)).toBe('第一段')
  })

  it('blockPreviewText：表格线替空格、折叠空白、图片占位转人话', () => {
    expect(blockPreviewText([{ text: '我公司提供\n\n7×24 小时\t维保服务' }], 120)).toBe('我公司提供 7×24 小时 维保服务')
    expect(blockPreviewText([{ text: '| 项 | 值 |\n|---|---|\n| 工期 | 一年 |' }], 120)).toBe('项 值 --- --- 工期 一年')
    expect(blockPreviewText([{ text: '![](图片)\n证书扫描件' }], 120)).toBe('（含图） 证书扫描件')
    expect(blockPreviewText([{ text: '## 1 服务内容及SLA\n**产品支持**：知识中心' }], 120)).toBe(
      '1 服务内容及SLA 产品支持：知识中心',
    )
  })

  it('blockPreviewText：超长截断加省略号', () => {
    const out = blockPreviewText([{ text: '字'.repeat(200) }], 120)
    expect(out).toHaveLength(121)
    expect(out.endsWith('…')).toBe(true)
    expect(blockPreviewText([{ text: '字'.repeat(120) }], 120)).toHaveLength(120)
  })

  it('容器节点不下沉为叶子；空标题跳过', () => {
    const ls = iterLeaves([{ name: 'X', directory: [{ 目录名称: '', level: 1, children: [] }] }])
    expect(ls).toEqual([])
  })

  it('sanitizeName：非法字符替空格、折叠空白、截 60（中文样例与 sidecar 同规则）', () => {
    expect(sanitizeName('3.2:总体*方案?')).toBe('3.2 总体 方案')
    expect(sanitizeName('  多  个   空白\t折叠 ')).toBe('多 个 空白 折叠')
    expect(sanitizeName('')).toBe('未命名')
    expect(sanitizeName('a'.repeat(80))).toHaveLength(60)
  })

  it('writtenSections：排除指引/承诺/整本；docx 优先；多册键对账；writtenPathOf 回查', () => {
    const paths = [
      'body/写作指引.md',
      'body/关键事实与承诺.md',
      'body/整本-技术部分.docx',
      'body/3.1 项目理解与需求分析.docx',
      'body/3.1 项目理解与需求分析.md', // 旧稿残留：docx 为准
      'body/技术部分/3.1 项目理解与需求分析.docx', // 多册子目录
    ]
    const multi = true
    const written = writtenSections(paths, multi)
    expect(written.size).toBe(2)
    // 多册下根级文件册键为空串、裸标题行也是空串册键——永不与册内文件互配（Python 同款）
    expect(writtenPathOf('3.1 项目理解与需求分析', written, multi)).toBeUndefined()
    expect(writtenPathOf('技术部分/3.1 项目理解与需求分析', written, multi)).toBe(
      'body/技术部分/3.1 项目理解与需求分析.docx',
    )
    expect(writtenPathOf('3.2 总体设计方案', written, multi)).toBeUndefined()
    // 单册：册名段被忽略（check_pipeline 单册册键为空串）
    const single = writtenSections(['body/3.1 项目理解与需求分析.docx'], false)
    expect(writtenPathOf('3.1 项目理解与需求分析', single, false)).toBe('body/3.1 项目理解与需求分析.docx')
  })
})

describe('orderBodyRows（正文组面板显示序）', () => {
  const docs: EditDoc[] = [
    {
      name: '技术部分',
      directory: [
        {
          目录名称: '第三章',
          level: 1,
          children: [
            { 目录名称: '3.1 项目理解与需求分析', level: 2, children: [], 交付形态: '正文编写' },
            { 目录名称: '3.2:总体*方案?', level: 2, children: [], 交付形态: '混合' },
          ],
        },
      ],
    },
    {
      name: '商务部分',
      directory: [{ 目录名称: '投标函', level: 1, children: [], 交付形态: '模板或附件填充' }],
    },
  ]

  it('整本按册序、指引/承诺前置、节文件按树序对账（清洗后匹配），未匹配尾置', () => {
    const paths = [
      'body/写作指引.md',
      'body/关键事实与承诺.md',
      'body/商务部分/投标函.docx', // 字母序原本在前
      'body/技术部分/3.2 总体 方案.docx', // 文件名=叶子标题清洗产物
      'body/技术部分/3.1 项目理解与需求分析.docx',
      'body/技术部分/孤儿节.docx', // 目录里没有的旧稿 → 尾置
      'body/整本-商务部分.docx',
      'body/整本-技术部分.docx',
    ]
    const r = orderBodyRows(paths, { response_documents: docs })
    expect(r.finals).toEqual(['body/整本-技术部分.docx', 'body/整本-商务部分.docx'])
    expect(r.guide).toBe('body/写作指引.md')
    expect(r.promise).toBe('body/关键事实与承诺.md')
    expect(r.sections).toEqual([
      'body/技术部分/3.1 项目理解与需求分析.docx',
      'body/技术部分/3.2 总体 方案.docx',
      'body/商务部分/投标函.docx',
      'body/技术部分/孤儿节.docx',
    ])
  })

  it('单册：根级平铺文件按树序对账', () => {
    const single = [{ name: '', directory: docs[0].directory }]
    const r = orderBodyRows(
      ['body/3.2 总体 方案.docx', 'body/3.1 项目理解与需求分析.docx'],
      { response_documents: single },
    )
    expect(r.sections).toEqual([
      'body/3.1 项目理解与需求分析.docx',
      'body/3.2 总体 方案.docx',
    ])
  })

  it('无目录数据回退：整本仍前置、其余保持传入原序（不排序）', () => {
    const paths = ['body/b节.docx', 'body/整本-主册.docx', 'body/a节.docx', 'body/写作指引.md']
    const r = orderBodyRows(paths, null)
    expect(r.finals).toEqual(['body/整本-主册.docx'])
    expect(r.guide).toBe('body/写作指引.md')
    expect(r.promise).toBeNull()
    expect(r.sections).toEqual(['body/b节.docx', 'body/a节.docx'])
  })

  it('整本册名未命中目录时排匹配者之后（稳定序兜底）', () => {
    const r = orderBodyRows(
      ['body/整本-未知册.docx', 'body/整本-商务部分.docx'],
      { response_documents: docs },
    )
    expect(r.finals).toEqual(['body/整本-商务部分.docx', 'body/整本-未知册.docx'])
  })
})

describe('guideRowFlags / guideRowMatches（查看态过滤，2026-09-09 设计稿 D）', () => {
  const valid = new Set(['blk_0123456789ab'])
  const base = { validBlockIds: valid, leafKeys: null as Set<string> | null, written: false }

  it('缺素材/块失效/不在目录/已写四标记', () => {
    expect(guideRowFlags('3.1 节', '【缺】', base)).toEqual({ missing: true, stale: false, offtree: false, written: false })
    expect(guideRowFlags('3.1 节', 'blk_ffffffffffff 素材', base)).toEqual({
      missing: false,
      stale: true,
      offtree: false,
      written: false,
    })
    const leaves = new Set(['3.1 节', '3.2 节'])
    expect(guideRowFlags('3.9 节', '—', { ...base, leafKeys: leaves }).offtree).toBe(true)
    expect(guideRowFlags('3.1 节', '—', { ...base, leafKeys: leaves }).offtree).toBe(false)
    // 无目录产物（leafKeys=null）不判越界
    expect(guideRowFlags('3.9 节', '—', base).offtree).toBe(false)
    expect(guideRowFlags('3.1 节', '—', { ...base, written: true }).written).toBe(true)
  })

  it('过滤谓词：待写=!written（缺素材行同时命中待写属预期——单选胶囊语义）', () => {
    const f = guideRowFlags('3.1 节', '【缺】 blk_ffffffffffff', { ...base, leafKeys: new Set(['3.2 节']) })
    expect(f.missing && f.stale && f.offtree).toBe(true) // 一行可同时带多个问题
    expect(guideRowMatches(f, 'missing')).toBe(true)
    expect(guideRowMatches(f, 'stale')).toBe(true)
    expect(guideRowMatches(f, 'offtree')).toBe(true)
    expect(guideRowMatches(f, 'todo')).toBe(true)
    expect(guideRowMatches(f, 'written')).toBe(false)
    expect(guideRowMatches(f, 'all')).toBe(true)
  })
})

describe('leafGroups（两级章节分组，2026-09-09 设计稿 D/层级区分）', () => {
  const docs: EditDoc[] = [
    {
      name: '技术部分',
      directory: [
        {
          目录名称: '第三章 落实方案',
          level: 1,
          children: [
            { 目录名称: '3.1 项目理解与需求分析', level: 2, children: [], 交付形态: '正文编写' },
            {
              目录名称: '3.2 总体方案',
              level: 2,
              children: [{ 目录名称: '3.2.1 架构', level: 3, children: [{ 目录名称: '3.2.1.1 深层', level: 4, children: [] }] }],
            },
          ],
        },
        { 目录名称: '第三章附表', level: 1, children: [], 交付形态: '模板或附件填充' },
      ],
    },
    {
      name: '商务部分',
      directory: [{ 目录名称: '3.1 项目理解与需求分析', level: 1, children: [] }],
    },
  ]

  it('top=最顶层祖先（深层仍归顶层）；second=顶层之下的那层容器，顶层直挂叶子为 null', () => {
    const m = leafGroups(docs, true)
    expect(m?.get('技术部分/3.1 项目理解与需求分析')).toEqual({ top: '第三章 落实方案', second: null })
    // 「3.2.1 架构」带子节点是容器不进 Map；最深叶子 3.2.1.1 的 second 仍是第二层容器（不随深度下沉）
    expect(m?.has('技术部分/3.2.1 架构')).toBe(false)
    expect(m?.get('技术部分/3.2.1.1 深层')).toEqual({ top: '第三章 落实方案', second: '3.2 总体方案' })
    expect(m?.get('技术部分/第三章附表')).toEqual({ top: '第三章附表', second: null }) // 顶层叶子=自身
    expect(m?.get('商务部分/3.1 项目理解与需求分析')).toEqual({ top: '3.1 项目理解与需求分析', second: null })
  })

  it('单册键为裸标题；无树/空树返回 null（不分组）', () => {
    const single = [{ name: '', directory: docs[0].directory }]
    expect(leafGroups(single, false)?.get('3.2.1.1 深层')).toEqual({ top: '第三章 落实方案', second: '3.2 总体方案' })
    expect(leafGroups([], false)).toBeNull()
    expect(leafGroups([{ name: 'X', directory: [] }], false)).toBeNull()
  })
})

describe('sortRefIds（依据选择器显示序）', () => {
  it('MAND→TPL→REQ→SCORE 分组、组内编号升序', () => {
    expect(sortRefIds(['SCORE-2', 'req-10', 'MAND-1', 'REQ-2', 'TPL-01'])).toEqual([
      'MAND-1',
      'TPL-01',
      'REQ-2',
      'req-10',
      'SCORE-2',
    ])
  })
})
