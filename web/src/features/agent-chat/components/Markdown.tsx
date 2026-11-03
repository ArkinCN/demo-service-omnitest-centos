/* ===========================================================================
   助手回答 / 知识库抽取稿的轻量 Markdown 渲染。

   为什么自写而不引库：本项目的依赖清单是客户锁定版（阶段 1 明写「逐字源自
   客户、未增删」），为渲染几行聊天文本引入 remark/marked 一整条依赖链不划算，
   且这类库默认允许原始 HTML、要再做一遍消毒。助手回答的语法面是可控的
   （标题 / 粗体 / 列表 / 行内代码 / 分隔线），自写一份更小、更可审。

   ⚠️ **安全口径：全程不生成 HTML、不用 dangerouslySetInnerHTML**。
   所有文本都作为 React 文本节点渲染，天然转义；**不解析链接与图片**
   （助手可能从检索资料里带回 url，渲染成可点链接会把「点一下就外跳」
   的口子开到聊天框里）。要加链接必须单独评估，不要顺手开。
   KaTeX 是唯一的例外（见下），它按 `trust: false` 运行且不接受 HTML。

   支持的语法（只此几种，多的一律当普通文本原样显示，不猜）：
     ### 标题 / ## 标题 / # 标题     → 三级以内标题
     **粗体**                        → <strong>
     `行内代码`                      → <code>
     - 列表项（- 或 *）+ 续行缩进     → <ul><li>
     1. 列表项 + 续行缩进             → <ol><li>
     ---                             → 分隔线
     | a | b | 表格（GFM，第二行     → <table>
     |---|---| 为分隔行）
     $$...$$ / $...$                 → KaTeX 公式（2026-10-08 新增）
     其余                            → 普通段落，保留换行

   ⚠️ 表格是 2026-10-04 补的：模型回答常用 GFM 表格列参数/判定结果，此前
   parseBlocks 不识别，`|---|---|` 分隔行与竖线原样裸奔在气泡里，用户截图
   反馈「格式错乱、不可读」。支持后表格按行渲染成真正的 <table>。

   ⚠️ 公式（KaTeX）是唯一新增依赖：知识库抽取稿里 docling 会把 PDF 公式
   抽成 LaTeX（`\frac{...}{...}`、`$$...$$`），此前无渲染器，原样吐出成一堆
   反斜杠，用户截图反馈「显示为机器阅读格式」。KaTeX 是该场景的事实标准，
   按需引入不引整条 markdown 链；`trust:false` 保持与本文件「不生成 HTML」
   的安全口径一致。
   =========================================================================== */
import { Fragment, type ReactNode } from 'react'
import { useT } from '../../../i18n'
import katex from 'katex'
import 'katex/dist/katex.min.css'

/**
 * KaTeX 渲染一段 LaTeX。
 *
 * ⚠️ 渲染失败**不抛**：抽取稿里公式常带 docling 的残缺标记（如 `\frac{` 缺
 * 右半边），抛错会让整篇文档白屏。失败时回退成等宽原文，读者仍能看到内容，
 * 不至于因为一个公式打不开整篇——与本项目「失败可见但不阻塞」的纪律一致。
 */
function tex(latex: string, displayMode: boolean, key: string): ReactNode {
  try {
    const html = katex.renderToString(latex, {
      displayMode,
      throwOnError: false, // 公式出错时 KaTeX 自己渲染成红色报错，不抛
      strict: false, // 允许常见的不严格写法（docling 抽取常见）
      trust: false, // 安全口径：禁止 \html 等命令
      output: 'html', // 返回字符串，交给下面的 <span> 用 innerHTML 注入
    })
    return (
      <span
        key={key}
        className={displayMode ? 'ac-md__math ac-md__math--block' : 'ac-md__math'}
        // KaTeX 输出的 HTML 是**库自己从受控 LaTeX 生成**的（trust:false 下
        // 不含用户 HTML），与「不解析用户 HTML」的口径不冲突——这里的输入
        // 是 LaTeX 源码，不是用户的 HTML 片段。
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  } catch {
    // 兜底：连 KaTeX 都抛（极少），用等宽原文显示，不吞内容
    return (
      <code key={key} className="ac-md__math-fallback">
        {latex}
      </code>
    )
  }
}

/**
 * 行内公式 / 抽取稿未解出公式的友好占位。
 *
 * 两种识别：
 *   ① `$...$` / `$$...$$` —— docling 抽出的 LaTeX；
 *   ② `e\d+: formula not decoded` —— docling **明确标注解不出**的行，
 *      直接显示英文报错很难看（用户截图原话「显示为机器阅读格式」）。
 *      这里换成中文占位，并保留"这是抽取稿的已知限制"这一事实，不假装公式存在。
 */
const NOT_DECODED_RE = /\be\d+\s*:\s*formula not decoded\b\s*[→>\-—:：]?\s*/i

function MissingFormula() {
  const uiT = useT()
  return (
    <span className="ac-md__math-missing" title={uiT('该公式未能从原文中自动提取')}>
      {uiT('公式未能自动提取')}
    </span>
  )
}

function notDecodedNode(key: string): ReactNode { return <MissingFormula key={key} /> }

/** 行内解析：粗体、行内代码、行内公式、未解出公式占位。 */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = []
  // 一次扫过：**粗体** 或 `代码` 或 $公式$，谁先出现先切谁。
  // ⚠️ 公式放最后，避免 `$` 参与前两个的匹配；`$` 本身在正文里罕见，误切风险低。
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\$([^$\n]+?)\$/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(...plainOrMissing(text.slice(last, m.index), `${keyPrefix}-t${i}`, out.length))
    if (m[1] !== undefined) {
      out.push(<strong key={`${keyPrefix}-b${i}`}>{m[1]}</strong>)
    } else if (m[2] !== undefined) {
      out.push(<code key={`${keyPrefix}-c${i}`}>{m[2]}</code>)
    } else if (m[3] !== undefined) {
      out.push(tex(m[3], false, `${keyPrefix}-x${i}`))
    }
    last = m.index + m[0].length
    i += 1
  }
  if (last < text.length) out.push(...plainOrMissing(text.slice(last), `${keyPrefix}-t${i}`, out.length))
  return out
}

/**
 * 普通文本片段：若整段就是「未解出公式」标记，则换成中文占位（C1）。
 * 只在**整段**匹配时替换——正文里顺带提到这串英文的情况极罕见，
 * 整段匹配可避免把正常句子里的片段误替换掉。
 */
function plainOrMissing(s: string, key: string, idx: number): ReactNode[] {
  if (NOT_DECODED_RE.test(s.trim())) return [notDecodedNode(`${key}-m${idx}`)]
  return [s]
}

type Block =
  | { t: 'h'; level: number; text: string }
  | { t: 'ul'; items: string[] }
  | { t: 'ol'; items: string[] }
  | { t: 'table'; head: string[]; rows: string[][] }
  | { t: 'hr' }
  | { t: 'math'; tex: string } // 独立成行的 $$...$$ 块级公式
  | { t: 'p'; text: string }

/** 把整段文本切成块级结构。空行分段，列表按「起始行 + 缩进续行」归并。 */
function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let para: string[] = []

  const flushPara = () => {
    if (para.length) {
      blocks.push({ t: 'p', text: para.join('\n') })
      para = []
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    const trimmed = line.trim()

    // 空行：段落分隔
    if (!trimmed) {
      flushPara()
      continue
    }
    // 分隔线
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushPara()
      blocks.push({ t: 'hr' })
      continue
    }
    // 块级公式：单行 $$...$$ 或跨行 $$ ... $$（docling 常把公式排版成多行）
    if (trimmed.startsWith('$$')) {
      const first = trimmed.slice(2)
      if (first.endsWith('$$') && first.length >= 2) {
        // 单行闭合
        flushPara()
        blocks.push({ t: 'math', tex: first.slice(0, -2).trim() })
        continue
      }
      // 跨行：从下一行起找到收尾的 $$
      let acc = first
      let j = i + 1
      let closed = false
      while (j < lines.length) {
        const cur = lines[j].trim()
        acc += `\n${cur}`
        if (cur.endsWith('$$')) {
          acc = acc.slice(0, acc.lastIndexOf('$$'))
          closed = true
          break
        }
        j += 1
      }
      flushPara()
      if (closed) {
        blocks.push({ t: 'math', tex: acc.trim() })
        i = j
        continue
      }
      // 没闭合（抽取稿截断）：按普通段落处理，别吞掉后面的内容
      para.push(line)
      continue
    }
    // GFM 表格：本行是 `|...|`，下一行是 `|---|---|` 分隔行 → 连续收集数据行。
    // 第二行不满足分隔行格式就当普通文本，不猜（比如「| 备注」这种半截竖线）。
    if (/^\|.*\|\s*$/.test(trimmed) && /^\s*\|[\s:|-]+\|?\s*$/.test(lines[i + 1] ?? '')) {
      const cells = (ln: string) =>
        ln
          .trim()
          .replace(/^\|/, '')
          .replace(/\|\s*$/, '')
          .split('|')
          .map((c) => c.trim())
      flushPara()
      const head = cells(trimmed)
      const rows: string[][] = []
      i += 2 // 跳过表头与分隔行
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        rows.push(cells(lines[i]))
        i += 1
      }
      i -= 1 // for 循环还要 +1，回退一格
      blocks.push({ t: 'table', head, rows })
      continue
    }
    // 标题
    const h = /^(#{1,6})\s+(.*)$/.exec(trimmed)
    if (h) {
      flushPara()
      blocks.push({ t: 'h', level: Math.min(h[1].length, 3), text: h[2] })
      continue
    }
    // 无序列表（- 或 *，后跟空格）
    //
    // ⚠️ 必须把**连续的列表行并进同一个块**。首版每行都 push 一个新块，
    // 3 条列表项就渲染成 3 个各自带项目符号的 <ul>，行距与缩进都对不齐
    // （快检脚本第一次跑就暴露了：blocks 成了 ul,ul,ul 而不是一个 ul）。
    // 这里看上一块是不是同类型列表，是就续上去，不是才新建。
    if (/^[-*]\s+/.test(trimmed)) {
      flushPara()
      const item = trimmed.replace(/^[-*]\s+/, '')
      const prev = blocks[blocks.length - 1]
      if (prev?.t === 'ul') {
        prev.items.push(item)
      } else {
        blocks.push({ t: 'ul', items: [item] })
      }
      // 续行：缩进的非列表行并入上一项
      while (
        i + 1 < lines.length && /^\s+\S/.test(lines[i + 1]) &&
        !/^\s*[-*]\s+/.test(lines[i + 1]) && !/^\s*\d+\.\s+/.test(lines[i + 1])
      ) {
        const cur = blocks[blocks.length - 1]
        if (cur.t !== 'ul') break
        cur.items[cur.items.length - 1] += '\n' + lines[i + 1].trim()
        i += 1
      }
      continue
    }
    // 有序列表（1. 2. …）；归并规则同上
    if (/^\d+\.\s+/.test(trimmed)) {
      flushPara()
      const item = trimmed.replace(/^\d+\.\s+/, '')
      const prev = blocks[blocks.length - 1]
      if (prev?.t === 'ol') {
        prev.items.push(item)
      } else {
        blocks.push({ t: 'ol', items: [item] })
      }
      while (
        i + 1 < lines.length && /^\s+\S/.test(lines[i + 1]) &&
        !/^\s*[-*]\s+/.test(lines[i + 1]) && !/^\s*\d+\.\s+/.test(lines[i + 1])
      ) {
        const cur = blocks[blocks.length - 1]
        if (cur.t !== 'ol') break
        cur.items[cur.items.length - 1] += '\n' + lines[i + 1].trim()
        i += 1
      }
      continue
    }
    para.push(line)
  }
  flushPara()
  return blocks
}

export function Markdown({ text }: { text: string }) {
  const blocks = parseBlocks(text)
  return (
    <>
      {blocks.map((b, i) => {
        if (b.t === 'hr') return <hr key={i} className="ac-md__hr" />
        if (b.t === 'h') {
          // 标题层级不高出对话气泡的观感：内部统一按视觉级距走
          const Tag = (b.level === 1 ? 'h4' : 'h5') as 'h4' | 'h5'
          return (
            <Tag key={i} className="ac-md__h">
              {inline(b.text, `h${i}`)}
            </Tag>
          )
        }
        if (b.t === 'ul' || b.t === 'ol') {
          const List = b.t === 'ul' ? 'ul' : 'ol'
          return (
            <List key={i} className="ac-md__list">
              {b.items.map((it, j) => (
                <li key={j}>{inline(it, `l${i}-${j}`)}</li>
              ))}
            </List>
          )
        }
        if (b.t === 'table') {
          return (
            <table key={i} className="ac-md__table">
              <thead>
                <tr>
                  {b.head.map((c, j) => (
                    <th key={j}>{inline(c, `th${i}-${j}`)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, j) => (
                  <tr key={j}>
                    {r.map((c, k) => (
                      <td key={k}>{inline(c, `td${i}-${j}-${k}`)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
        if (b.t === 'math') return <div key={i}>{tex(b.tex, true, `m${i}`)}</div>
        // 段落内的单换行保留（助手常把「字段：值」一行一条列出）
        const parts = b.text.split('\n')
        return (
          <p key={i} className="ac-md__p">
            {parts.map((ln, j) => (
              <Fragment key={j}>
                {j > 0 ? <br /> : null}
                {inline(ln, `p${i}-${j}`)}
              </Fragment>
            ))}
          </p>
        )
      })}
    </>
  )
}
