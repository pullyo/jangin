#!/usr/bin/env node
// Jangin(장인) 화면 — Hermes Agent 위에서 도는 1인 사업 비서의 터미널 화면.
//
// Hermes 의 런처가 HERMES_TUI_DIR 를 보고 이 파일을 `node dist/entry.js` 로 띄운다 (oh-my-hermes 와 같은 방식).
// 모델 호출, 도구 실행, 승인 판단은 전부 Hermes 게이트웨이가 한다. 이 파일은 화면만 맡는다.
//
//   접속: Hermes 의 파이썬 도우미(ui-tui/scripts/gateway_bootstrap.py)가 접속 티켓을 주면 WebSocket 으로 붙는다
//   규약: JSON-RPC 2.0. runtime.describe → session.create(source=tui) → prompt.submit, 이벤트는 method=event 프레임
//   의존성: 없음 (Node 22+ 의 내장 WebSocket). 한국어 화면.
import { execFile } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { appendFileSync, existsSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, resolve } from 'node:path'

// ─────────────────────────────────────────────── 색과 그림
const C = {
  cream: '#F3E6CF', title: '#F0D9B5', amber: '#E0A458', spark: '#FFB74D', wood: '#C8945A', brown: '#8B5A2B',
  dark: '#6B4226', dim: '#9C7B5B', text: '#E8DCC8', ok: '#8BC34A', err: '#E57373', warn: '#FFB74D', tool: '#B8A58A',
  user: '#D9B98C'
}
const TRUECOLOR = !process.env.NO_COLOR
// JANGIN_DEBUG=1 이면 주고받는 프레임을 <HERMES_HOME>/logs/jangin-tui.log 에 남긴다 (값은 그대로 쓰므로 공유하지 말 것)
const DEBUG_LOG = process.env.JANGIN_DEBUG ? resolve(process.env.HERMES_HOME || resolve(homedir(), '.hermes'), 'logs', 'jangin-tui.log') : null
function debug(line) {
  if (!DEBUG_LOG) return
  try { mkdirSync(resolve(DEBUG_LOG, '..'), { recursive: true }); appendFileSync(DEBUG_LOG, `${new Date().toISOString()} ${line}\n`) } catch {}
}
const fg = (hex, s) => {
  if (!TRUECOLOR) return s
  const n = parseInt(hex.slice(1), 16)
  return `\x1b[38;2;${(n >> 16) & 255};${(n >> 8) & 255};${n & 255}m${s}\x1b[39m`
}
const bold = s => `\x1b[1m${s}\x1b[22m`
const dim = s => `\x1b[2m${s}\x1b[22m`

const LOGO = [
  [C.cream, '     ██╗ █████╗ ███╗   ██╗ ██████╗ ██╗███╗   ██╗'],
  ['#EBD3AE', '     ██║██╔══██╗████╗  ██║██╔════╝ ██║████╗  ██║'],
  ['#E3C08F', '     ██║███████║██╔██╗ ██║██║  ███╗██║██╔██╗ ██║'],
  ['#DDAA6E', '██   ██║██╔══██║██║╚██╗██║██║   ██║██║██║╚██╗██║'],
  ['#D0924F', '╚█████╔╝██║  ██║██║ ╚████║╚██████╔╝██║██║ ╚████║'],
  ['#B87A3E', ' ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝']
]
const HERO = [
  [C.spark, '                       ✦  ✦  '],
  [C.cream, '       ▄████████▄    ✦  ·    '],
  [C.cream, '       ██████████   ·        '],
  [C.cream, '       ▀████████▀            '],
  [C.wood, '           ██                '],
  [C.wood, '           ██                '],
  ['#9C6B3F', '   ▄▄▄▄▄▄▄▄██▄▄▄▄▄▄▄▄▄▄▄▄    '],
  [C.brown, '   ▀████████████████████▀▀▀  '],
  [C.brown, '       ▀████████████▀        '],
  [C.dark, '         ▐████████▌          '],
  [C.dark, '       ▄████████████▄        '],
  ['#5E4630', '      ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀       '],
  [C.cream, '                             '],
  [C.title, '        장   인  JANGIN      '],
  [C.dim, '     idea · build · ship     ']
]
const VERBS = ['망치질하는 중', '담금질하는 중', '다듬는 중', '두 번 재는 중', '불을 보는 중', '모양을 잡는 중', '날을 세우는 중', '광을 내는 중']
const FACES = ['⚒', '✦', '▲', '·']

// ─────────────────────────────────────────────── 문자 폭 (한글·한자·이모지는 2칸)
function isWide(cp) {
  return (cp >= 0x1100 && cp <= 0x115F) || (cp >= 0x2E80 && cp <= 0xA4CF && cp !== 0x303F) || (cp >= 0xAC00 && cp <= 0xD7A3) ||
    (cp >= 0xF900 && cp <= 0xFAFF) || (cp >= 0xFE30 && cp <= 0xFE4F) || (cp >= 0xFF00 && cp <= 0xFF60) || (cp >= 0xFFE0 && cp <= 0xFFE6) ||
    (cp >= 0x1F300 && cp <= 0x1FAFF) || (cp >= 0x20000 && cp <= 0x3FFFD)
}
const ANSI = /\x1b\[[0-9;]*[A-Za-z]/g
function width(s) {
  let w = 0
  for (const ch of s.replace(ANSI, '')) {
    const cp = ch.codePointAt(0)
    if (cp < 32 || (cp >= 0x7f && cp < 0xa0) || cp === 0x200d || (cp >= 0xfe00 && cp <= 0xfe0f)) continue
    w += isWide(cp) ? 2 : 1
  }
  return w
}
/** 한 줄을 화면 폭에 맞게 자른다 (ANSI 색은 잘린 조각마다 유지하지 않는다: 색은 줄 단위로만 쓴다). */
function wrap(line, cols) {
  const out = []
  let cur = '', w = 0
  const plain = line.includes('\x1b')
  if (plain) {   // 색이 든 줄은 통째로 (배너·도구 줄처럼 폭이 짧은 것만 색을 쓴다)
    return [line]
  }
  for (const ch of line) {
    const cw = isWide(ch.codePointAt(0)) ? 2 : 1
    if (w + cw > cols) { out.push(cur); cur = ''; w = 0 }
    cur += ch; w += cw
  }
  out.push(cur)
  return out
}

// ─────────────────────────────────────────────── 화면 (스크롤백 + 아래쪽 실시간 영역)
class Screen {
  constructor() {
    this.liveRows = 0
    this.partial = ''        // 아직 줄이 끝나지 않은 답변 조각
    this.status = ''         // 상태 한 줄 (진행 중 문구 등)
    this.composer = null     // () => string[] (입력 줄들)
    this.caret = null        // () => [row, col] 커서 위치 (composer 줄 기준)
    this.out = process.stdout
  }
  get cols() { return Math.max(20, (this.out.columns || 80) - 1) }
  write(s) { this.out.write(s) }
  /** 스크롤백에 확정 출력. 실시간 영역을 지우고 쓴 뒤 다시 그린다. */
  print(text = '') {
    const lines = String(text).split('\n')
    const rows = lines.flatMap(l => wrap(l, this.cols))
    this.write('\x1b[?2026h' + this.eraseLive() + rows.join('\n') + '\n' + this.renderLive() + '\x1b[?2026l')
  }
  eraseLive() {
    const up = this.liveRows > 1 ? `\x1b[${this.liveRows - 1}A` : ''
    this.liveRows = 0
    return up + '\r\x1b[J'
  }
  renderLive() {
    const rows = []
    for (const l of this.partial.split('\n')) rows.push(...wrap(l, this.cols))
    if (this.partial === '') rows.length = 0
    if (this.status) rows.push(...wrap(this.status, this.cols))
    let caret = null
    if (this.composer) {
      const start = rows.length
      const crow = this.composer()
      rows.push(...crow)
      if (this.caret) { const [r, c] = this.caret(); caret = [start + r, c] }
    }
    if (!rows.length) { this.liveRows = 0; return '' }
    this.liveRows = rows.length
    let s = rows.join('\n')
    if (caret) {
      const upBy = rows.length - 1 - caret[0]
      if (upBy > 0) s += `\x1b[${upBy}A`
      s += `\x1b[${caret[1] + 1}G`
    }
    return s
  }
  redraw() { this.write('\x1b[?2026h' + this.eraseLive() + this.renderLive() + '\x1b[?2026l') }
  /** 스트리밍 조각: 끝난 줄은 스크롤백으로, 나머지는 실시간 영역에 둔다. */
  stream(text) {
    const all = this.partial + text
    const i = all.lastIndexOf('\n')
    if (i >= 0) {
      this.partial = all.slice(i + 1)
      this.print(all.slice(0, i))
    } else {
      this.partial = all
      this.redraw()
    }
  }
  flush() {
    if (this.partial) { const p = this.partial; this.partial = ''; this.print(p) }
  }
}

// ─────────────────────────────────────────────── 게이트웨이 접속
class Gateway {
  constructor(onEvent, onLog) {
    this.onEvent = onEvent; this.onLog = onLog
    this.ws = null; this.nextId = 1; this.pending = new Map(); this.ready = false
  }
  python() { return (process.env.HERMES_PYTHON || '').trim() || (process.platform === 'win32' ? 'python' : 'python3') }
  root() {
    const r = (process.env.HERMES_PYTHON_SRC_ROOT || '').trim()
    return r || resolve(homedir(), '.hermes', 'hermes-agent')
  }
  bootstrap(start) {
    const root = this.root()
    const helper = resolve(root, 'ui-tui', 'scripts', 'gateway_bootstrap.py')
    if (!existsSync(helper)) throw new Error(`Hermes 접속 도우미를 찾지 못했다: ${helper}`)
    return new Promise((ok, no) => {
      execFile(this.python(), [helper, ...(start ? ['--start'] : [])],
        { cwd: root, env: { ...process.env, PYTHONPATH: root, HERMES_PYTHON_SRC_ROOT: root }, timeout: 40_000, maxBuffer: 1 << 20 },
        (err, stdout, stderr) => {
          if (err) return no(new Error((stderr || err.message).trim().split('\n').slice(-3).join(' ')))
          try { ok(JSON.parse(stdout)) } catch { no(new Error('접속 티켓을 읽지 못했다: ' + stdout.slice(0, 200))) }
        })
    })
  }
  async connect(start = true) {
    const grant = await this.bootstrap(start)
    await new Promise((ok, no) => {
      const ws = new WebSocket(grant.url, grant.protocols)
      let settled = false
      ws.addEventListener('open', () => { this.ws = ws })
      ws.addEventListener('message', ev => {
        let frame
        try { frame = JSON.parse(typeof ev.data === 'string' ? ev.data : String(ev.data)) } catch { return }
        debug('<< ' + String(ev.data).slice(0, 1500))
        if (frame.method === 'event') {
          const p = frame.params || {}
          if (p.type === 'gateway.ready' && !settled) { settled = true; this.ready = true; ok() }
          this.onEvent(p)
          return
        }
        if (frame.id !== undefined && this.pending.has(frame.id)) {
          const { res, rej, timer } = this.pending.get(frame.id)
          clearTimeout(timer); this.pending.delete(frame.id)
          if (frame.error) {
            const e = new Error(frame.error.message || JSON.stringify(frame.error)); e.code = frame.error.code; e.data = frame.error.data; rej(e)
          } else res(frame.result)
        }
      })
      ws.addEventListener('error', () => { if (!settled) { settled = true; no(new Error('게이트웨이에 접속하지 못했다')) } })
      ws.addEventListener('close', () => {
        this.ready = false; this.ws = null
        for (const { rej, timer } of this.pending.values()) { clearTimeout(timer); rej(new Error('연결이 끊겼다')) }
        this.pending.clear()
        if (!settled) { settled = true; no(new Error('연결이 닫혔다')) }
        this.onEvent({ type: 'jangin.closed' })
      })
      setTimeout(() => { if (!settled) { settled = true; no(new Error('게이트웨이 응답 없음 (gateway.ready 대기)')) } }, 30_000)
    })
    this.heartbeat = setInterval(() => { this.request('gateway.ping', {}, 10_000).catch(() => {}) }, 20_000)
    return grant
  }
  request(method, params = {}, timeoutMs = 120_000) {
    return new Promise((res, rej) => {
      if (!this.ws || this.ws.readyState !== 1) return rej(new Error(`연결이 없다: ${method}`))
      const id = this.nextId++
      const timer = setTimeout(() => { this.pending.delete(id); rej(new Error(`응답 시간 초과: ${method}`)) }, timeoutMs)
      this.pending.set(id, { res, rej, timer })
      debug(`>> ${method} ${JSON.stringify(params).slice(0, 600)}`)
      this.ws.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }))
    })
  }
  close() { clearInterval(this.heartbeat); try { this.ws?.close() } catch {} }
}

// ─────────────────────────────────────────────── 입력 줄 (composer)
class Composer {
  constructor() { this.text = ''; this.pos = 0; this.history = []; this.hi = -1; this.draft = '' }
  insert(s) { this.text = this.text.slice(0, this.pos) + s + this.text.slice(this.pos); this.pos += s.length }
  backspace() { if (this.pos > 0) { const n = this.prevLen(); this.text = this.text.slice(0, this.pos - n) + this.text.slice(this.pos); this.pos -= n } }
  del() { if (this.pos < this.text.length) { const n = this.nextLen(); this.text = this.text.slice(0, this.pos) + this.text.slice(this.pos + n) } }
  prevLen() { const cp = this.text.codePointAt(this.pos - 1); return (cp >= 0xDC00 && cp <= 0xDFFF) ? 2 : 1 }
  nextLen() { const cp = this.text.codePointAt(this.pos); return cp > 0xFFFF ? 2 : 1 }
  left() { if (this.pos > 0) this.pos -= this.prevLen() }
  right() { if (this.pos < this.text.length) this.pos += this.nextLen() }
  home() { this.pos = 0 }
  end() { this.pos = this.text.length }
  killLine() { this.text = this.text.slice(0, this.pos) }
  killWord() {
    const before = this.text.slice(0, this.pos).replace(/\S+\s*$/, '')
    this.text = before + this.text.slice(this.pos); this.pos = before.length
  }
  take() { const t = this.text; if (t.trim()) { this.history.push(t); if (this.history.length > 200) this.history.shift() } this.text = ''; this.pos = 0; this.hi = -1; return t }
  up() {
    if (!this.history.length) return
    if (this.hi === -1) { this.draft = this.text; this.hi = this.history.length }
    if (this.hi > 0) { this.hi--; this.text = this.history[this.hi]; this.pos = this.text.length }
  }
  down() {
    if (this.hi === -1) return
    this.hi++
    if (this.hi >= this.history.length) { this.hi = -1; this.text = this.draft } else this.text = this.history[this.hi]
    this.pos = this.text.length
  }
}

// ─────────────────────────────────────────────── 앱
class App {
  constructor() {
    this.screen = new Screen()
    this.composer = new Composer()
    this.gw = new Gateway(ev => this.onEvent(ev), l => this.log(l))
    this.session = null; this.generation = 0; this.busy = false; this.replying = false
    this.prompt = null       // {kind:'approval'|'clarify', ...}
    this.lastCtrlC = 0; this.spinner = null; this.spinI = 0; this.logs = []
    this.info = {}
    this.screen.composer = () => this.renderComposer()
    this.screen.caret = () => this.caretPos()
  }
  log(line) { this.logs.push(line); if (this.logs.length > 200) this.logs.shift() }

  // ── 화면 조각
  renderComposer() {
    const cols = this.screen.cols
    const rule = fg(C.brown, '─'.repeat(cols))
    if (this.prompt?.kind === 'approval') {
      const p = this.prompt
      const labels = { once: '한 번 허용', deny: '거절', session: '이 세션에서 허용', always: '항상 허용' }
      const keys = (p.choices || ['once', 'deny']).map((c, i) => `${fg(C.amber, `[${i + 1}]`)} ${labels[c] || c}`).join('   ')
      return [rule, `${fg(C.spark, '⚠ 승인 필요')}  ${keys}`, rule]
    }
    const head = this.prompt?.kind === 'clarify' ? fg(C.spark, '? ') : fg(C.amber, '⚒ ')
    const body = this.composer.text || ''
    const lines = (body || (this.prompt ? '답을 입력하고 엔터' : '')).split('\n')
    const rows = []
    lines.forEach((l, i) => {
      const prefix = i === 0 ? head : '  '
      const chunks = wrap(l, cols - 2)
      chunks.forEach((c, j) => rows.push((j === 0 ? prefix : '  ') + (body ? c : dim(c))))
    })
    const hint = this.busy ? dim('Ctrl+C 중단 · 입력하면 다음 차례로 보냄') : dim('/idea 새 아이디어 · /inbox 승인 대기 · /help 명령 · /quit 나가기')
    return [rule, ...rows, rule, hint]
  }
  caretPos() {
    if (this.prompt?.kind === 'approval') return [1, 0]
    const cols = this.screen.cols
    const before = this.composer.text.slice(0, this.composer.pos)
    const lines = before.split('\n')
    let row = 1   // rule 다음
    for (let i = 0; i < lines.length - 1; i++) row += Math.max(1, wrap(lines[i], cols - 2).length)
    const last = lines[lines.length - 1]
    const chunks = wrap(last, cols - 2)
    row += chunks.length - 1
    return [row, 2 + width(chunks[chunks.length - 1] || '')]
  }
  setStatus(s) { this.screen.status = s ? fg(C.dim, s) : ''; this.screen.redraw() }
  startSpinner() {
    if (this.spinner) return
    this.spinI = 0
    this.spinner = setInterval(() => {
      this.spinI++
      const verb = VERBS[Math.floor(this.spinI / 8) % VERBS.length]
      this.screen.status = fg(C.amber, FACES[this.spinI % FACES.length]) + ' ' + fg(C.dim, verb + '…')
      this.screen.redraw()
    }, 250)
  }
  stopSpinner(final = '') { clearInterval(this.spinner); this.spinner = null; this.screen.status = final; this.screen.redraw() }
  note(s) { this.screen.print(fg(C.dim, s)) }
  error(s) { this.screen.print(fg(C.err, '✗ ' + s)) }

  banner() {
    const cols = this.screen.cols
    const wide = cols >= 100
    const out = []
    for (const [col, l] of LOGO) out.push(fg(col, l))
    out.push(fg(C.dim, 'Hermes Agent 위에서 도는 1인 사업 비서 · Nous Research 의 Hermes Agent 를 엔진으로 씁니다'))
    out.push('')
    const info = [
      bold(fg(C.title, `Jangin ${this.info.version ? 'v' + this.info.version : ''}`)) + (this.info.release_date ? fg(C.dim, ` (${this.info.release_date})`) : ''),
      '',
      fg(C.dim, '모델      ') + fg(C.text, `${this.info.model || '?'}${this.info.provider ? ' · ' + this.info.provider : ''}`),
      fg(C.dim, '프로필    ') + fg(C.text, this.info.profile_name || basename(process.env.HERMES_HOME || '') || 'jangin'),
      fg(C.dim, '폴더      ') + fg(C.text, this.info.cwd || process.env.HERMES_CWD || process.cwd()),
      fg(C.dim, '도구·스킬 ') + fg(C.text, `${this.info.tool_count ?? '?'}개 도구 · ${this.info.skill_count ?? '?'}개 스킬`),
      '',
      fg(C.amber, '/idea <한 줄 아이디어>') + fg(C.dim, '  새 프로젝트를 만들고 발견 단계 시작'),
      fg(C.amber, '/stage · /advance') + fg(C.dim, '        지금 단계 · 다음 단계로 (사람만)'),
      fg(C.amber, '/inbox · /ok <번호>') + fg(C.dim, '      승인 대기 · 승인 (승인하면 바로 보냄)'),
      fg(C.amber, '/project · /help') + fg(C.dim, '         상태 · 모든 명령')
    ]
    if (wide) {
      const left = HERO.map(([col, l]) => fg(col, l))
      const n = Math.max(left.length, info.length)
      for (let i = 0; i < n; i++) out.push((left[i] || ' '.repeat(29)) + '   ' + (info[i] || ''))
    } else {
      out.push(...info)
    }
    out.push('')
    this.screen.print(out.join('\n'))
  }

  // ── 시작
  async start() {
    const so = process.stdout
    so.write('\x1b[2J\x1b[H\x1b[?2004h')   // 화면 지우기, 붙여넣기 묶음 켜기
    process.on('exit', () => { so.write('\x1b[?2004l\x1b[?2026l\n') })
    this.banner()
    this.setStatus('Hermes 게이트웨이에 접속하는 중…')
    let grant
    try { grant = await this.gw.connect(true) }
    catch (e) { this.stopSpinner(); this.error(`접속 실패: ${e.message}`); this.note('hermes gateway status 로 상태를 확인하거나 jangin --classic 으로 예전 화면을 쓸 수 있습니다.'); process.exit(1) }
    try {
      const desc = await this.gw.request('runtime.describe')
      const contract = desc?.session_create || {}
      if (!(contract.sources || []).includes('tui')) throw new Error('이 Hermes 는 TUI 세션 생성을 지원하지 않는다 (hermes update 필요)')
      const resume = (process.env.HERMES_TUI_RESUME || '').trim()
      let snap
      if (resume) {
        snap = await this.gw.request('session.resume', { session_id: resume, display_projection: true })
        this.renderHistory(snap)
      } else {
        const params = { request_id: randomUUID(), source: 'tui' }
        const cwd = (process.env.HERMES_CWD || '').trim()
        if (cwd && (contract.parameters || []).includes('cwd')) params.cwd = cwd
        snap = await this.gw.request('session.create', params)
      }
      this.session = snap.session_id || snap.ref?.session_id || snap.session?.session_id
      if (!this.session) throw new Error('세션 번호를 받지 못했다')
      if (snap.execution_generation !== undefined) this.generation = snap.execution_generation
      for (const p of snap.pending_prompts || snap.pending || []) this.showPrompt(p)
      try {
        const info = await this.gw.request('session.info', { session_id: this.session })
        this.info = { ...info, tool_count: info.tool_count ?? countLeaves(info.tools), skill_count: countLeaves(info.skills) }
      } catch (e) { this.log('session.info: ' + e.message) }
      so.write('\x1b[2J\x1b[H'); this.screen.liveRows = 0
      this.banner()
      this.setStatus('')
      this.note(`세션 ${this.session.slice(0, 8)} · ${resume ? '이어서' : '새로'} 시작. 아이디어가 있으면 /idea, 그냥 이야기해도 됩니다.`)
      this.screen.print('')
    } catch (e) { this.stopSpinner(); this.error(e.message); process.exit(1) }
    this.listen()
    const q = (process.env.HERMES_TUI_QUERY || '').trim()
    if (q) this.submit(q)
  }
  renderHistory(snap) {
    const rows = snap.messages || []
    const shown = rows.slice(-40)
    if (rows.length > shown.length) this.note(`⋯ 이전 메시지 ${rows.length - shown.length}개`)
    for (const r of shown) {
      const text = typeof r.text === 'string' ? r.text : rowText(r.content)
      if (!text) continue
      if (r.role === 'user') this.screen.print(fg(C.user, '↳ 나: ') + text)
      else if (r.role === 'assistant') this.screen.print(text)
    }
  }

  // ── 이벤트
  onEvent(p) {
    try { this.handleEvent(p) } catch (e) { debug(`ERR ${p?.type}: ${e?.stack || e}`); this.log(`event ${p?.type}: ${e?.message || e}`) }
  }
  handleEvent(p) {
    if (p.execution_generation !== undefined) this.generation = p.execution_generation
    if (p.session_id && this.session && p.session_id !== this.session) { debug(`EV ${p.type} skip sid=${p.session_id} mine=${this.session}`); return }
    debug(`EV ${p.type}`)
    const pl = p.payload || {}
    switch (p.type) {
      case 'gateway.ready': return
      case 'message.start': this.busy = true; this.replying = true; this.startSpinner(); return
      case 'message.delta':
        if (pl.text == null) { this.screen.flush(); return }
        this.screen.stream(pl.text); return
      case 'message.interim': if (pl.text) { this.screen.flush(); this.screen.print(pl.text) } return
      case 'tool.start': {
        this.screen.flush()
        const arg = (pl.preview || pl.args_text || summarizeArgs(pl.args) || '').replace(/\s+/g, ' ').slice(0, this.screen.cols - 12)
        this.screen.print(fg(C.tool, `┊ ⚒ ${pl.name}`) + (arg ? fg(C.dim, '  ' + arg) : ''))
        return
      }
      case 'tool.complete': {
        const sec = pl.duration_s != null ? ` ${pl.duration_s.toFixed(1)}s` : ''
        const sum = (pl.summary || '').replace(/\s+/g, ' ').slice(0, this.screen.cols - 14)
        this.screen.print(fg(C.tool, `┊ ✓ ${pl.name}${sec}`) + (sum ? fg(C.dim, '  ' + sum) : ''))
        return
      }
      case 'tool.output_risk': this.note(`주의: 도구 출력에 위험 신호 (${pl.kind || pl.reason || ''})`); return
      case 'status.update': if (pl.text && !this.spinner) this.setStatus(pl.text); return
      case 'notice': if (pl.text) this.note(pl.text); return
      case 'notification.show': if (pl.text || pl.message) this.note(pl.text || pl.message); return
      case 'error': this.error(pl.message || pl.error || JSON.stringify(pl)); return
      case 'turn.error': this.screen.flush(); this.error(pl.message || pl.error || '차례가 실패했다'); this.busy = false; this.stopSpinner(); return
      case 'message.complete': {
        this.screen.flush()
        if (pl.error) this.error(pl.error)
        if (pl.warning) this.note(pl.warning)
        const u = pl.usage || {}
        const total = u.total ?? u.total_tokens ?? ((u.prompt ?? u.prompt_tokens ?? 0) + (u.completion ?? u.completion_tokens ?? 0))
        const ctx = u.context_percent != null ? ` · 문맥 ${u.context_percent}%` : ''
        const tok = total ? dim(`${total.toLocaleString('ko-KR')} 토큰${ctx}`) : ''
        this.busy = false; this.replying = false
        this.stopSpinner('')
        this.screen.print(fg(C.brown, '─'.repeat(Math.min(24, this.screen.cols))) + (tok ? ' ' + tok : ''))
        return
      }
      case 'approval.request': this.showPrompt({ kind: 'approval', ...pl }); return
      case 'clarify.request': this.showPrompt({ kind: 'clarify', ...pl }); return
      case 'approval.settled': case 'clarify.settled':
        if (this.prompt && this.prompt.prompt_id === pl.prompt_id) { this.prompt = null; this.screen.redraw() }
        return
      case 'approval.cancelled': if (this.prompt?.kind === 'approval') { this.prompt = null; this.screen.redraw() } return
      case 'session.title': if (pl.title) this.note(`제목: ${pl.title}`); return
      case 'session.reclaimed': this.error('다른 화면이 이 세션을 가져갔다. /quit 로 나가서 다시 여세요.'); return
      case 'jangin.closed': this.busy = false; this.stopSpinner(); this.error('게이트웨이 연결이 끊겼다. /quit 로 나가서 다시 여세요.'); return
      default: return
    }
  }
  showPrompt(p) {
    this.prompt = p
    if (p.execution_generation !== undefined) this.generation = p.execution_generation
    this.screen.flush()
    if (p.kind === 'approval') {
      const lines = [fg(C.spark, '⚠ 승인이 필요합니다')]
      if (p.description) lines.push('  ' + p.description)
      if (p.command) lines.push('  ' + fg(C.text, p.command))
      if (p.edit) lines.push('  ' + fg(C.dim, '파일 편집 승인'))
      this.screen.print(lines.join('\n'))
    } else {
      const lines = [fg(C.spark, '? ' + (p.question || '질문'))]
      ;(p.choices || []).forEach((c, i) => lines.push(`  ${fg(C.amber, `[${i + 1}]`)} ${c}`))
      if (p.choices?.length) lines.push(fg(C.dim, '  번호나 답을 입력하고 엔터. 빈 엔터 = 건너뛰기'))
      this.screen.print(lines.join('\n'))
    }
    this.screen.redraw()
  }

  // ── 입력
  listen() {
    const si = process.stdin
    si.setRawMode(true); si.resume(); si.setEncoding('utf8')
    let paste = null
    si.on('data', chunk => {
      let s = chunk
      while (s.length) {
        if (paste !== null) {
          const end = s.indexOf('\x1b[201~')
          if (end < 0) { paste += s; return }
          paste += s.slice(0, end); this.composer.insert(paste.replace(/\r\n?/g, '\n')); paste = null
          s = s.slice(end + 6); this.screen.redraw(); continue
        }
        if (s.startsWith('\x1b[200~')) { paste = ''; s = s.slice(6); continue }
        const m = s.match(/^\x1b\[(\d*)(?:;(\d*))?([A-Za-z~])/) || s.match(/^\x1b(O[A-Z]|[\s\S])/)
        if (m) { this.key(m[0]); s = s.slice(m[0].length); continue }
        const ch = s[0] < '\x20' || s[0] === '\x7f' ? s[0] : null
        if (ch !== null) { this.key(ch); s = s.slice(1); continue }
        const i = [...s].findIndex(c => c < '\x20' || c === '\x7f')
        const text = i < 0 ? s : s.slice(0, i)
        if (this.prompt?.kind === 'approval') this.approvalKey(text)
        else this.composer.insert(text)
        s = s.slice(text.length)
        this.screen.redraw()
      }
    })
    process.stdout.on('resize', () => this.screen.redraw())
  }
  key(k) {
    const c = this.composer
    switch (k) {
      case '\r': case '\n': return this.enter()
      case '\x03': return this.ctrlC()
      case '\x04': if (!c.text) return this.quit(); c.del(); break
      case '\x7f': case '\b': c.backspace(); break
      case '\x1b[A': case '\x1bOA': c.up(); break
      case '\x1b[B': case '\x1bOB': c.down(); break
      case '\x1b[C': case '\x1bOC': c.right(); break
      case '\x1b[D': case '\x1bOD': c.left(); break
      case '\x1b[H': case '\x1bOH': case '\x01': c.home(); break
      case '\x1b[F': case '\x1bOF': case '\x05': c.end(); break
      case '\x1b[3~': c.del(); break
      case '\x0b': c.killLine(); break
      case '\x17': c.killWord(); break
      case '\x15': c.text = ''; c.pos = 0; break
      case '\x0c': process.stdout.write('\x1b[2J\x1b[H'); this.screen.liveRows = 0; this.banner(); break
      case '\x1b\r': case '\x1b\n': c.insert('\n'); break   // Alt+Enter: 줄 바꿈
      default: return
    }
    this.screen.redraw()
  }
  approvalKey(text) {
    const p = this.prompt
    const choices = p.choices || ['once', 'deny']
    const map = { y: 'once', n: 'deny', s: 'session', a: 'always' }
    let choice = null
    const ch = text.trim().toLowerCase()
    if (/^\d$/.test(ch) && choices[+ch - 1]) choice = choices[+ch - 1]
    else if (map[ch] && choices.includes(map[ch])) choice = map[ch]
    if (!choice) return
    this.prompt = null; this.screen.redraw()
    this.gw.request('approval.respond', { session_id: this.session, execution_generation: p.execution_generation ?? this.generation, prompt_id: p.prompt_id, choice })
      .then(() => this.note(`승인 응답: ${choice}`)).catch(e => this.error(`승인 응답 실패: ${e.message}`))
  }
  ctrlC() {
    if (this.prompt?.kind === 'approval') {
      const p = this.prompt; this.prompt = null; this.screen.redraw()
      this.gw.request('approval.respond', { session_id: this.session, execution_generation: p.execution_generation ?? this.generation, prompt_id: p.prompt_id, choice: 'deny' }).catch(() => {})
      return
    }
    if (this.composer.text) { this.composer.text = ''; this.composer.pos = 0; this.screen.redraw(); return }
    if (this.busy) {
      this.note('중단 요청…')
      this.gw.request('session.interrupt', { session_id: this.session, execution_generation: this.generation })
        .catch(e => this.error(`중단 실패: ${e.message}`))
      return
    }
    const now = Date.now()
    if (now - this.lastCtrlC < 2000) return this.quit()
    this.lastCtrlC = now
    this.note('나가려면 Ctrl+C 를 한 번 더, 또는 /quit')
  }
  async enter() {
    if (this.prompt?.kind === 'clarify') {
      const p = this.prompt
      let answer = this.composer.take().trim()
      if (/^\d+$/.test(answer) && p.choices?.[+answer - 1]) answer = p.choices[+answer - 1]
      this.prompt = null; this.screen.redraw()
      try { await this.gw.request('clarify.respond', { session_id: this.session, execution_generation: p.execution_generation ?? this.generation, prompt_id: p.prompt_id, answer }) }
      catch (e) { this.error(`답 전송 실패: ${e.message}`) }
      return
    }
    const text = this.composer.take()
    if (!text.trim()) { this.screen.redraw(); return }
    this.screen.redraw()
    if (text.trim().startsWith('/')) return this.slash(text.trim())
    return this.submit(text)
  }
  async submit(text) {
    this.screen.print(fg(C.user, '↳ 나: ') + text)
    this.busy = true; this.startSpinner()
    try {
      const r = await this.gw.request('prompt.submit', { session_id: this.session, text, input_id: randomUUID(), ...(this.busy && this.replying ? { queued: true } : {}) })
      if (r?.execution_generation != null) this.generation = r.execution_generation
      if (r?.status === 'queued' && this.replying) this.note('지금 차례가 끝나면 이어서 처리합니다.')
    } catch (e) { this.busy = false; this.stopSpinner(); this.error(`보내지 못했다: ${e.message}`) }
  }
  async slash(line) {
    const [cmd, ...rest] = line.slice(1).split(/\s+/)
    const name = cmd.toLowerCase()
    if (['quit', 'exit', 'q', '나가기'].includes(name)) return this.quit()
    if (name === 'clear') { process.stdout.write('\x1b[2J\x1b[H'); this.screen.liveRows = 0; this.banner(); return }
    if (name === 'logs') { this.screen.print(this.logs.slice(-20).join('\n') || '(기록 없음)'); return }
    this.screen.print(fg(C.user, '↳ ') + fg(C.amber, line))
    try {
      const r = await this.gw.request('slash.exec', { session_id: this.session, command: line })
      if (r?.type === 'send' || r?.type === 'skill') return this.submit(r.target || r.output || rest.join(' '))
      if (r?.type === 'alias' && r.target) return this.slash(r.target)
      if (r?.type === 'prefill') { this.composer.text = r.target || r.output || ''; this.composer.pos = this.composer.text.length; this.screen.redraw(); return }
      const text = [r?.output, r?.message, r?.notice, r?.warning].filter(Boolean).join('\n')
      if (text) this.screen.print(text)
      else if (r?.status) this.note(r.status)
    } catch (e) {
      if (/unknown|not found|4000|4001/i.test(e.message)) this.error(`모르는 명령: ${line}  (/help 로 목록)`)
      else this.error(`명령 실패: ${e.message}`)
    }
  }
  quit() {
    this.stopSpinner('')
    this.screen.print(fg(C.dim, '다음 작업에서 뵙겠습니다. ⚒'))
    this.gw.close()
    process.stdout.write('\x1b[?2004l')
    process.exit(0)
  }
}

function rowText(content) {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) return content.map(c => (typeof c === 'string' ? c : c?.text || '')).join('')
  return ''
}
function countLeaves(obj) {
  if (!obj || typeof obj !== 'object') return undefined
  return Object.values(obj).reduce((n, v) => n + (Array.isArray(v) ? v.length : 0), 0)
}
function summarizeArgs(args) {
  if (!args || typeof args !== 'object') return ''
  for (const k of ['command', 'path', 'query', 'url', 'name', 'pattern']) if (typeof args[k] === 'string') return args[k]
  return Object.entries(args).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(' ')
}

if (!process.stdin.isTTY || !process.stdout.isTTY) {
  console.log('Jangin 화면은 터미널에서만 열린다. 터미널 없이 쓰려면: jangin chat -q "..."')
  process.exit(0)
}
process.on('uncaughtException', e => { try { process.stdout.write(`\n\x1b[31mjangin: ${e.stack || e}\x1b[39m\n`) } catch {} })
new App().start()
