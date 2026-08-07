import { useEffect, useRef } from 'react'

// Live product demo for the landing hero (Plan 35). Self-contained animated screencast of the
// app in action (inbox auto-triage → one email + trace-debug via MCP → montage → CTA).
//
// Rendered in a Shadow DOM so its generic class names (.card/.chip/.nav) can never collide with
// the app or the landing. Design tokens (--teal, --paper, …) are CSS custom properties defined on
// :root by theme.css and inherit through the shadow boundary, so light/dark just works.
//
// The animation engine runs per-play with a cancellation token; IntersectionObserver plays it when
// it scrolls into view and pauses it when it leaves. Respects prefers-reduced-motion and, on small
// screens, shows a poster + "Play" instead of autoplaying a tiny window.

const DEMO_CSS = `
:host{display:block;font-family:var(--sans)}
*{box-sizing:border-box}
.app{position:relative;width:100%;border:1px solid var(--line);border-radius:16px;background:var(--paper);
  box-shadow:var(--shadow);overflow:hidden;color:var(--ink)}
.chrome{height:36px;display:flex;align-items:center;gap:8px;padding:0 14px;border-bottom:1px solid var(--line);
  background:color-mix(in srgb,var(--ink) 4%,var(--paper))}
.dot{width:10px;height:10px;border-radius:50%}
.dot.r{background:#e0625a}.dot.y{background:#e0b04a}.dot.g{background:#4fae72}
.url{margin-left:10px;font-family:var(--mono);font-size:12px;color:var(--faint);
  background:var(--ground);border:1px solid var(--line);border-radius:7px;padding:3px 12px}
.viewport{position:relative;height:min(58vh,560px);min-height:420px;overflow:hidden}
.page{position:absolute;inset:0;opacity:0;visibility:hidden;transition:opacity .5s ease,visibility .5s;display:flex;flex-direction:column}
.page.on{opacity:1;visibility:visible}
.nav{display:flex;align-items:center;justify-content:space-between;padding:11px 20px;border-bottom:1px solid var(--line);flex:0 0 auto}
.nav .brand{display:flex;align-items:center;gap:8px;font-weight:600;color:var(--ink);font-size:14px}
.nav .brand .glyph{font-family:var(--mono);color:var(--teal)}
.navlinks{display:flex;align-items:center;gap:16px;font-size:13px}
.navlink{color:var(--muted)}
.navlink.active{color:var(--ink);font-weight:600}
.ws{font-size:12px;color:var(--ink-soft);border:1px solid var(--line);border-radius:8px;padding:3px 9px;background:var(--paper)}
.body{flex:1;overflow:auto;padding:22px}
.col{max-width:640px;margin:0 auto;display:flex;flex-direction:column;gap:16px}
.col.wide{max-width:900px}
h1.hd{margin:0;font-size:1.5rem;font-weight:680;letter-spacing:-.01em}
.sub{margin:2px 0 0;font-size:13px;color:var(--muted)}
.kick{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--teal);font-weight:600}
.card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:18px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
label.f{display:block}
label.f span{display:block;font-size:12.5px;font-weight:500;color:var(--ink-soft);margin-bottom:5px}
.inp,.ta{width:100%;background:var(--paper);border:1px solid var(--line);border-radius:9px;padding:8px 11px;font-size:13px;color:var(--ink);font-family:var(--sans)}
.ta{resize:none;line-height:1.5}
.inp.focus,.ta.focus{outline:2px solid var(--teal);outline-offset:1px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border-radius:9px;padding:9px 15px;font-size:13px;font-weight:600;border:1px solid transparent}
.btn.primary{background:var(--teal);color:var(--paper)}
.btn.block{width:100%}
.chip{display:inline-flex;align-items:center;font-family:var(--mono);font-size:12px;font-weight:600;border:1px solid var(--line);border-radius:999px;padding:4px 12px;color:var(--ink-soft);background:var(--ground)}
.chip.cat{border-color:color-mix(in srgb,var(--c) 45%,var(--line));color:var(--c);background:color-mix(in srgb,var(--c) 12%,var(--paper))}
.draftbox{background:var(--ground);border:1px solid var(--line);border-radius:10px;padding:13px;font-size:13px;color:var(--ink-soft);line-height:1.6;min-height:44px}
.rowsb{display:flex;align-items:center;justify-content:space-between}
.muted{color:var(--muted)}.faint{color:var(--faint)}.small{font-size:12px}.mono{font-family:var(--mono)}
.traces{border-top:1px solid var(--line);margin-top:14px;padding-top:14px;display:none;flex-direction:column;gap:9px}
.traces.open{display:flex}
.thread{display:flex;flex-direction:column;gap:8px;min-height:20px}
.bubble{font-size:13px;line-height:1.5;border-radius:12px;padding:9px 12px;max-width:82%}
.bubble.user{align-self:flex-end;background:var(--teal-wash);color:var(--ink);border:1px solid color-mix(in srgb,var(--teal) 30%,var(--line))}
.bubble.bot{align-self:flex-start;background:var(--ground);color:var(--ink-soft);border:1px solid var(--line)}
.chatrow{display:flex;gap:8px}
.counter{font-family:var(--mono);font-weight:700;font-size:1rem;color:var(--crit);border:1px solid color-mix(in srgb,var(--crit) 35%,var(--line));border-radius:999px;padding:4px 12px;transition:color .4s,border-color .4s}
.counter.done{color:var(--teal);border-color:color-mix(in srgb,var(--teal) 40%,var(--line))}
.maillist{display:flex;flex-direction:column;gap:8px}
.mailrow{display:flex;align-items:center;gap:14px;padding:11px 14px;border:1px solid var(--line);border-radius:12px;background:var(--paper);transition:border-color .3s,background .3s}
.mailrow.done{border-color:color-mix(in srgb,var(--teal) 26%,var(--line));background:color-mix(in srgb,var(--teal) 5%,var(--paper))}
.mailrow .who{width:150px;font-size:12.5px;color:var(--ink);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 0 auto}
.mailrow .subj{flex:1;font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mailrow .slot{flex:0 0 auto;width:112px;text-align:right}
.mailrow .un{font-family:var(--mono);font-size:10px;color:var(--crit)}
.panels{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.panel{border:1px solid var(--line);border-radius:14px;padding:16px;background:var(--paper)}
.panel h3{margin:0;font-size:14px}
.clock{font-family:var(--mono);font-size:1.4rem;font-weight:600}
.clock.hl{color:var(--teal)}
.end{align-items:center;justify-content:center;text-align:center;gap:18px;padding:40px}
.end .eglyph{font-family:var(--mono);font-size:2.4rem;color:var(--teal);font-weight:700}
.end .ebig{margin:0;font-size:clamp(1.8rem,4.6vw,3rem);font-weight:720;letter-spacing:-.03em;max-width:16ch;line-height:1.05}
.end .ebig .accent{color:var(--teal)}
.end .esub{margin:0;color:var(--muted);font-size:14px}
.end .cta{background:var(--teal);color:var(--paper);border-radius:13px;padding:15px 30px;font-weight:700;font-size:16px;box-shadow:0 16px 42px -12px color-mix(in srgb,var(--teal) 80%,transparent)}
.end .emeta{font-family:var(--mono);font-size:11px;letter-spacing:.14em;color:var(--faint);text-transform:uppercase}
.appear{animation:appear .45s cubic-bezier(.2,.7,.2,1) both}
@keyframes appear{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes pulse{0%,100%{transform:none}50%{transform:translateY(-3px)}}
@keyframes endin{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:no-preference){
  .end.on .eglyph,.end.on .ebig,.end.on .esub,.end.on .emeta{animation:endin .6s cubic-bezier(.2,.7,.2,1) both}
  .end.on .eglyph{animation-delay:.05s}.end.on .ebig{animation-delay:.16s}.end.on .esub{animation-delay:.3s}.end.on .emeta{animation-delay:.62s}
  .end.on .cta{animation:endin .55s cubic-bezier(.2,.7,.2,1) both .42s,pulse 2s ease-in-out infinite 1.3s}
}
.cursor{position:absolute;left:0;top:0;width:22px;height:22px;z-index:40;pointer-events:none;transform:translate(60px,120px);transition:transform .62s cubic-bezier(.5,.05,.2,1),opacity .3s;filter:drop-shadow(0 3px 5px rgba(0,0,0,.3))}
.cursor.hide{opacity:0}
.cursor.down{transform:translate(var(--cx),var(--cy)) scale(.82)}
.ripple{position:absolute;z-index:39;width:26px;height:26px;border-radius:50%;border:2px solid var(--teal);opacity:0;pointer-events:none;transform:translate(-50%,-50%)}
.ripple.go{animation:rip .5s ease-out}
@keyframes rip{from{opacity:.7;width:8px;height:8px}to{opacity:0;width:52px;height:52px}}
.cap{position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:45;max-width:80%;text-align:center;
  background:var(--ink);color:var(--paper);font-size:13px;padding:8px 16px;border-radius:999px;box-shadow:0 8px 24px -10px rgba(0,0,0,.5);opacity:0;transition:opacity .35s ease}
.cap.show{opacity:1}
.cap b{color:var(--teal)}
.dctl{position:absolute;top:46px;z-index:46;width:30px;height:30px;border-radius:8px;border:1px solid var(--line);
  background:color-mix(in srgb,var(--paper) 80%,transparent);color:var(--ink);cursor:pointer;display:grid;place-items:center;font-size:11px;opacity:.55;transition:opacity .2s}
.dctl:hover{opacity:1}
.dctl.replay{right:14px}.dctl.pause{right:50px}
.poster{position:absolute;inset:0;z-index:50;display:none;align-items:center;justify-content:center;flex-direction:column;gap:12px;
  background:color-mix(in srgb,var(--ground) 70%,transparent);backdrop-filter:blur(2px)}
.poster.show{display:flex}
.poster .playbtn{background:var(--teal);color:var(--paper);border:none;border-radius:12px;padding:13px 24px;font-size:15px;font-weight:700;cursor:pointer;font-family:var(--sans);box-shadow:0 14px 34px -12px color-mix(in srgb,var(--teal) 75%,transparent)}
.poster .plabel{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
@media (prefers-reduced-motion:reduce){.appear,.end.on *{animation:none}.cursor{transition:none}}
`

const DEMO_HTML = `
<div class="app">
  <div class="chrome"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
    <span class="url">app.triagestudio.ai/inbox</span></div>
  <button class="dctl pause" data-pause title="Pause">&#10074;&#10074;</button>
  <button class="dctl replay" data-replay title="Restart">&#8635;</button>
  <div class="viewport">

    <section class="page" data-page="inbox">
      <div class="nav"><span class="brand"><span class="glyph">&lt;/&gt;</span> Triage Studio</span>
        <span class="navlinks"><span class="ws">Acme &middot; owner</span><span data-counter class="counter">47 unanswered</span></span></div>
      <div class="body"><div class="col wide">
        <div><h1 class="hd">Support inbox</h1><p class="sub">Every email sorted the moment it lands &mdash; no rules to maintain.</p></div>
        <div class="maillist" data-rows>
          <div class="mailrow"><span class="who">maria@shopper.com</span><span class="subj">Where's my refund?</span><span class="slot"><span class="un">unread</span></span></div>
          <div class="mailrow"><span class="who">devon@buyer.io</span><span class="subj">Order 4471 still not shipped</span><span class="slot"><span class="un">unread</span></span></div>
          <div class="mailrow"><span class="who">lin@customer.co</span><span class="subj">Is the navy hoodie back in stock?</span><span class="slot"><span class="un">unread</span></span></div>
          <div class="mailrow"><span class="who">sam@client.com</span><span class="subj">Do you price-match the sale?</span><span class="slot"><span class="un">unread</span></span></div>
          <div class="mailrow"><span class="who">priya@shop.net</span><span class="subj">Refund still not on my card</span><span class="slot"><span class="un">unread</span></span></div>
          <div class="mailrow"><span class="who">theo@mail.com</span><span class="subj">Where is my package?</span><span class="slot"><span class="un">unread</span></span></div>
        </div>
      </div></div>
    </section>

    <section class="page" data-page="dashboard">
      <div class="nav"><span class="brand"><span class="glyph">&lt;/&gt;</span> Triage Studio</span>
        <span class="navlinks"><span class="ws">Acme &middot; owner</span>
          <span class="navlink" data-link="compare">Compare</span><span class="navlink" data-link="studio">Studio</span><span class="navlink active">Dashboard</span></span></div>
      <div class="body"><div class="col">
        <div><h1 class="hd">One email, up close</h1><p class="sub">Workspace: <b>Acme</b> &middot; role: <b>owner</b></p></div>
        <div class="card">
          <div class="kick" style="margin-bottom:12px">Classify + draft</div>
          <div class="grid2">
            <label class="f"><span>Subject</span><input class="inp" data-sub readonly placeholder="Order status inquiry"></label>
            <label class="f"><span>From</span><input class="inp" data-from readonly placeholder="customer@example.com"></label>
          </div>
          <label class="f" style="margin-top:12px"><span>Body</span><textarea class="ta" data-body rows="3" readonly placeholder="Paste the email body here…"></textarea></label>
          <button class="btn primary block" data-run style="margin-top:14px">Triage email &rarr;</button>
        </div>
        <div class="card" data-result style="display:none">
          <div class="rowsb" style="margin-bottom:12px"><span class="chip cat" style="--c:var(--cat-refunds)">refunds</span>
            <span class="small muted">Confidence: <b data-conf>&mdash;</b></span></div>
          <div class="kick" style="margin-bottom:7px">Draft reply</div>
          <div class="draftbox" data-draft></div>
          <button class="btn" style="border:1px solid var(--line);color:var(--muted);margin-top:12px;padding:6px 12px;font-size:12px" data-tracebtn>&#9656; Ver traces</button>
          <div class="traces" data-traces>
            <div class="rowsb"><span class="kick">Debug this trace</span><span class="mono small faint">trace cbd31ddd…</span></div>
            <div class="thread" data-thread></div>
            <div class="chatrow"><input class="inp" data-chatin readonly placeholder="e.g. Why was this slow?"><button class="btn primary" data-ask>Ask</button></div>
          </div>
        </div>
      </div></div>
    </section>

    <section class="page" data-page="compare">
      <div class="nav"><span class="brand"><span class="glyph">&lt;/&gt;</span> Triage Studio</span>
        <span class="navlinks"><span class="ws">Acme &middot; owner</span>
          <span class="navlink active">Compare</span><span class="navlink" data-link="studio">Studio</span><span class="navlink" data-link="dashboard">Dashboard</span></span></div>
      <div class="body"><div class="col wide">
        <div><h1 class="hd">Sync vs. Streaming</h1><p class="sub">Same request, two ways &mdash; watch the time-to-first-token.</p></div>
        <div class="panels">
          <div class="panel"><div class="rowsb"><h3>Sync <span class="mono small faint">/triage</span></h3><span class="clock" data-sync>0.0s</span></div>
            <div class="draftbox" data-syncbox style="margin-top:12px"><span class="faint small">waiting…</span></div></div>
          <div class="panel"><div class="rowsb"><h3>Streaming <span class="mono small faint">/triage/stream</span></h3><span class="clock hl" data-ttft>TTFT —</span></div>
            <div class="draftbox" data-streambox style="margin-top:12px"><span class="faint small">waiting…</span></div></div>
        </div>
      </div></div>
    </section>

    <section class="page" data-page="studio">
      <div class="nav"><span class="brand"><span class="glyph">&lt;/&gt;</span> Triage Studio</span>
        <span class="navlinks"><span class="ws">Acme &middot; owner</span>
          <span class="navlink" data-link="compare">Compare</span><span class="navlink active">Studio</span><span class="navlink" data-link="dashboard">Dashboard</span></span></div>
      <div class="body"><div class="col">
        <div><h1 class="hd">Triage Studio</h1><p class="sub">The taxonomy is yours &mdash; no engineer required.</p></div>
        <div class="card">
          <div class="kick" style="margin-bottom:12px">Your categories</div>
          <div style="display:flex;flex-wrap:wrap;gap:8px" data-cats>
            <span class="chip cat" style="--c:var(--cat-status)">status</span>
            <span class="chip cat" style="--c:var(--cat-refunds)">refunds</span>
            <span class="chip cat" style="--c:var(--cat-availability)">availability</span>
            <span class="chip cat" style="--c:var(--cat-shipments)">shipments</span>
            <span class="chip cat" style="--c:var(--cat-prices)">prices</span>
          </div>
          <div class="grid2" style="margin-top:16px;grid-template-columns:1fr 1fr auto;align-items:end">
            <label class="f"><span>Slug</span><input class="inp" data-slug readonly placeholder="warranty"></label>
            <label class="f"><span>Name</span><input class="inp" data-name readonly placeholder="Warranty"></label>
            <button class="btn primary" data-add>Add category</button>
          </div>
        </div>
      </div></div>
    </section>

    <section class="page end" data-page="end">
      <div class="eglyph">&lt;/&gt;</div>
      <h1 class="ebig">Your inbox, on <span class="accent">autopilot</span>.</h1>
      <p class="esub">Classify &middot; draft &middot; publish &middot; debug &mdash; the whole triage, your way.</p>
      <div class="btn cta">Start free &rarr;</div>
      <p class="emeta">Triage Studio</p>
    </section>

    <svg class="cursor hide" data-cursor viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <path d="M4 2 L20 12 L13 13 L17 21 L14 22 L10 14 L4 18 Z" fill="#fff" stroke="#0c1719" stroke-width="1.3" stroke-linejoin="round"/>
    </svg>
    <div class="ripple" data-ripple></div>
    <div class="cap" data-cap></div>
    <div class="poster" data-poster><button class="playbtn" data-play>&#9654; Watch the demo</button><span class="plabel">30-second product tour</span></div>
  </div>
</div>
`

export function DemoReel() {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const shadow = host.shadowRoot ?? host.attachShadow({ mode: 'open' })
    shadow.innerHTML = `<style>${DEMO_CSS}</style>${DEMO_HTML}`
    const $ = (s: string) => shadow.querySelector(s) as HTMLElement | null

    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    const small = matchMedia('(max-width: 640px)').matches
    let canAutoplay = !reduce && !small

    const vp = $('.viewport')!
    const cursor = $('[data-cursor]')!
    const ripple = $('[data-ripple]')!
    const cap = $('[data-cap]')!
    const poster = $('[data-poster]')!

    type Token = { cancelled: boolean; paused: boolean; park: (() => void) | null; timers: Set<number> }
    let token: Token | null = null
    let started = false
    let userPaused = false
    const CANCEL = Symbol('cancel')

    function setPauseUI(paused: boolean) {
      const b = $('[data-pause]')
      if (b) b.innerHTML = paused ? '&#9654;' : '&#10074;&#10074;'
    }

    const wait = (tk: Token, ms: number) =>
      new Promise<void>((resolve, reject) => {
        let rem = reduce ? Math.min(ms, 120) : ms
        const tick = () => {
          if (tk.cancelled) return reject(CANCEL)
          if (tk.paused) {
            tk.park = tick
            return
          }
          const chunk = Math.min(60, rem)
          rem -= chunk
          if (rem <= 0) return resolve()
          const t = window.setTimeout(tick, chunk)
          tk.timers.add(t)
        }
        const t0 = window.setTimeout(tick, Math.min(60, rem))
        tk.timers.add(t0)
      })

    function stop() {
      if (!token) return
      token.cancelled = true
      token.timers.forEach((t) => clearTimeout(t))
      token.timers.clear()
      const p = token.park
      token.park = null
      if (p) p() // unblock a parked wait so it can reject
      token = null
    }
    function pause() {
      if (token && !token.paused) token.paused = true
      setPauseUI(true)
    }
    function resume() {
      if (token && token.paused) {
        token.paused = false
        const p = token.park
        token.park = null
        if (p) p()
      }
      setPauseUI(false)
    }

    // ── engine helpers (bound to a run token via closures in run()) ────────────
    function center(el: HTMLElement) {
      const a = vp.getBoundingClientRect()
      const r = el.getBoundingClientRect()
      return { x: r.left - a.left + r.width * 0.5, y: r.top - a.top + r.height * 0.5 }
    }

    async function run(tk: Token) {
      const w = (ms: number) => wait(tk, ms)
      const moveTo = (el: HTMLElement, dur = 600) => {
        const p = center(el)
        cursor.style.transitionDuration = (reduce ? 0 : dur) + 'ms'
        cursor.style.transform = `translate(${p.x - 3}px,${p.y - 2}px)`
        return w(reduce ? 60 : dur)
      }
      const click = async (el: HTMLElement) => {
        const p = center(el)
        cursor.style.setProperty('--cx', p.x - 3 + 'px')
        cursor.style.setProperty('--cy', p.y - 2 + 'px')
        cursor.classList.add('down')
        ripple.style.left = p.x + 'px'
        ripple.style.top = p.y + 'px'
        ripple.classList.remove('go')
        void ripple.offsetWidth
        ripple.classList.add('go')
        await w(140)
        cursor.classList.remove('down')
        await w(110)
      }
      const caption = (html: string) => {
        cap.innerHTML = html
        cap.classList.add('show')
      }
      const showCursor = (on: boolean) => cursor.classList.toggle('hide', !on)
      const typeIn = async (el: HTMLInputElement | HTMLTextAreaElement, text: string, cps = 40) => {
        el.classList.add('focus')
        const d = 1000 / cps
        for (let i = 0; i < text.length; i++) {
          el.value = text.slice(0, i + 1)
          await w(reduce ? 0 : d)
        }
        if (reduce) el.value = text
        await w(110)
        el.classList.remove('focus')
      }
      const typeText = async (el: HTMLElement, text: string, cps = 62) => {
        const d = 1000 / cps
        el.textContent = ''
        for (let i = 0; i < text.length; i++) {
          el.textContent = text.slice(0, i + 1)
          await w(reduce ? 0 : d)
        }
        if (reduce) el.textContent = text
      }
      const show = (page: string) => {
        shadow.querySelectorAll('.page').forEach((p) => p.classList.toggle('on', (p as HTMLElement).dataset.page === page))
        const u = $('.url')
        if (u) u.textContent = 'app.triagestudio.ai/' + page
      }
      const nav = async (el: HTMLElement, page: string) => {
        await moveTo(el)
        await click(el)
        show(page)
        await w(600)
      }
      const scrollBottom = (page: string) => {
        const b = shadow.querySelector(`.page[data-page="${page}"] .body`) as HTMLElement | null
        if (b) b.scrollTo({ top: b.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
        return w(reduce ? 60 : 540)
      }
      const bubble = (cls: string, text: string) => {
        const d = document.createElement('div')
        d.className = 'bubble ' + cls
        d.textContent = text
        ;($('[data-thread]') as HTMLElement).appendChild(d)
        return d
      }
      const tickClock = (el: HTMLElement, to: number, ms: number) =>
        new Promise<void>((res) => {
          const start = performance.now()
          const f = (t: number) => {
            if (tk.cancelled) return res()
            const k = Math.min(1, (t - start) / ms)
            el.textContent = (to * k).toFixed(1) + 's'
            if (k < 1 && !reduce && !tk.paused) requestAnimationFrame(f)
            else {
              el.textContent = to.toFixed(1) + 's'
              res()
            }
          }
          requestAnimationFrame(f)
        })

      const iv = (s: string) => $(s) as HTMLInputElement

      function resetState() {
        ;['[data-sub]', '[data-from]', '[data-body]', '[data-chatin]', '[data-slug]', '[data-name]'].forEach((s) => {
          const e = $(s) as HTMLInputElement | null
          if (e) e.value = ''
        })
        const r = $('[data-result]')!
        r.style.display = 'none'
        ;($('[data-draft]') as HTMLElement).textContent = ''
        ;($('[data-conf]') as HTMLElement).innerHTML = '&mdash;'
        ;($('[data-tracebtn]') as HTMLElement).innerHTML = '&#9656; Ver traces'
        $('[data-traces]')!.classList.remove('open')
        ;($('[data-thread]') as HTMLElement).innerHTML = ''
        ;($('[data-sync]') as HTMLElement).textContent = '0.0s'
        ;($('[data-ttft]') as HTMLElement).textContent = 'TTFT —'
        ;($('[data-syncbox]') as HTMLElement).innerHTML = '<span class="faint small">waiting…</span>'
        ;($('[data-streambox]') as HTMLElement).innerHTML = '<span class="faint small">waiting…</span>'
        const warr = shadow.querySelector('[data-cats] [data-added]')
        if (warr) warr.remove()
        shadow.querySelectorAll('[data-rows] .mailrow').forEach((row) => {
          row.classList.remove('done')
          ;(row.querySelector('.slot') as HTMLElement).innerHTML = '<span class="un">unread</span>'
        })
        const cnt = $('[data-counter]')!
        cnt.textContent = '47 unanswered'
        cnt.classList.remove('done')
        shadow.querySelectorAll('.body').forEach((b) => ((b as HTMLElement).scrollTop = 0))
        showCursor(false)
        cursor.style.transform = 'translate(60px,120px)'
        show('inbox')
      }

      // ── the tour ─────────────────────────────────────────────────────────
      while (!tk.cancelled) {
        resetState()
        await w(500)

        // COLD OPEN — the pain + the wow
        showCursor(false)
        caption('A support inbox never stops filling up.')
        await w(1100)
        const rows = shadow.querySelectorAll('[data-rows] .mailrow')
        const cats = ['refunds', 'shipments', 'availability', 'prices', 'refunds', 'shipments']
        const cnt = $('[data-counter]')!
        let n = 47
        caption('Triage Studio sorts every one — the moment it lands.')
        for (let i = 0; i < rows.length; i++) {
          const slot = rows[i].querySelector('.slot') as HTMLElement
          const c = cats[i]
          slot.innerHTML = `<span class="chip cat appear" style="--c:var(--cat-${c})">${c}</span>`
          rows[i].classList.add('done')
          n = Math.max(0, n - Math.ceil(47 / rows.length))
          cnt.textContent = n > 0 ? n + ' unanswered' : '0 · all sorted'
          await w(300)
        }
        cnt.textContent = '0 · all sorted'
        cnt.classList.add('done')
        caption('47 emails. <b>Sorted &amp; drafted</b> before your coffee.')
        await w(1700)

        // HERO — one email + trace debug
        show('dashboard')
        await w(680)
        showCursor(true)
        cursor.style.transform = 'translate(120px,120px)'
        await w(320)
        caption('Open any one — classified and answered, with a draft you can send.')
        await moveTo(iv('[data-sub]'))
        await typeIn(iv('[data-sub]'), "Where's my refund?", 30)
        await moveTo(iv('[data-from]'))
        await typeIn(iv('[data-from]'), 'maria@shopper.com', 34)
        await moveTo(iv('[data-body]'))
        await typeIn(
          $('[data-body]') as HTMLTextAreaElement,
          "I returned the blender two weeks ago and still haven't seen my refund.",
          52,
        )
        await moveTo($('[data-run]')!)
        await click($('[data-run]')!)
        ;($('[data-run]') as HTMLElement).textContent = 'Analyzing…'
        await w(850)
        ;($('[data-run]') as HTMLElement).innerHTML = 'Triage email &rarr;'
        const res = $('[data-result]')!
        res.style.display = 'block'
        res.classList.add('appear')
        ;($('[data-conf]') as HTMLElement).textContent = '95%'
        await scrollBottom('dashboard')
        await w(150)
        await typeText(
          $('[data-draft]') as HTMLElement,
          "Hi Maria — thanks for your patience. Your return was received; refunds post to the original card within 5–7 business days. I've flagged this to expedite.",
          78,
        )
        await scrollBottom('dashboard')
        await w(900)

        caption("Not sure it got it right? <b>Ask the trace</b> — an agent over the Logfire MCP.")
        await w(700)
        await moveTo($('[data-tracebtn]')!)
        await click($('[data-tracebtn]')!)
        ;($('[data-tracebtn]') as HTMLElement).innerHTML = '&#9662; Hide traces'
        $('[data-traces]')!.classList.add('open')
        await scrollBottom('dashboard')
        await w(450)
        await moveTo(iv('[data-chatin]'))
        await typeIn(iv('[data-chatin]'), 'Why did it pick refunds, and was it slow?', 38)
        await moveTo($('[data-ask]')!)
        await click($('[data-ask]')!)
        iv('[data-chatin]').value = ''
        const thinking = bubble('bot', 'Reading traces…')
        await scrollBottom('dashboard')
        await w(1300)
        thinking.remove()
        const b = bubble('bot', '')
        await typeText(
          b,
          'It matched “refunds” at 0.95 — the email is about a return not yet credited. Took 1.2 s, all in the model call, no errors. Scoped to your org only.',
          56,
        )
        await scrollBottom('dashboard')
        await w(600)
        caption('No other triage tool lets you <b>audit the decision</b>.')
        await w(3100)

        // MONTAGE
        await nav(shadow.querySelector('.page[data-page="dashboard"] [data-link="compare"]') as HTMLElement, 'compare')
        caption('Streaming shows the reply <b>~6× sooner</b>.')
        const syncP = tickClock($('[data-sync]') as HTMLElement, 1.8, 1150)
        await w(220)
        ;($('[data-ttft]') as HTMLElement).textContent = 'TTFT 0.3s'
        ;($('[data-streambox]') as HTMLElement).innerHTML =
          '<span class="chip cat" style="--c:var(--cat-refunds)">refunds</span> <span class="small">Hi Maria — your refund is on its way…</span>'
        await syncP
        ;($('[data-syncbox]') as HTMLElement).innerHTML =
          '<span class="chip cat" style="--c:var(--cat-refunds)">refunds</span> <span class="small">Hi Maria — your refund is on its way…</span>'
        await w(650)

        await nav(shadow.querySelector('.page[data-page="compare"] [data-link="studio"]') as HTMLElement, 'studio')
        caption('And the taxonomy is yours to shape.')
        await moveTo(iv('[data-slug]'))
        await typeIn(iv('[data-slug]'), 'warranty', 56)
        await moveTo(iv('[data-name]'))
        await typeIn(iv('[data-name]'), 'Warranty', 56)
        await moveTo($('[data-add]')!)
        await click($('[data-add]')!)
        const chip = document.createElement('span')
        chip.className = 'chip cat appear'
        chip.setAttribute('data-added', '')
        chip.style.setProperty('--c', 'var(--cat-warranty)')
        chip.textContent = 'warranty'
        ;($('[data-cats]') as HTMLElement).appendChild(chip)
        iv('[data-slug]').value = ''
        iv('[data-name]').value = ''
        await w(850)

        // CLOSE
        showCursor(false)
        cap.classList.remove('show')
        await w(250)
        show('end')
        const u = $('.url')
        if (u) u.textContent = 'triagestudio.ai'
        await w(3800)
      }
    }

    function start() {
      stop()
      const tk: Token = { cancelled: false, paused: false, park: null, timers: new Set() }
      token = tk
      started = true
      userPaused = false
      setPauseUI(false)
      run(tk).catch(() => {}) // CANCEL rejections are expected on stop
    }

    // controls
    $('[data-replay]')?.addEventListener('click', () => {
      poster.classList.remove('show')
      canAutoplay = true
      start()
    })
    $('[data-pause]')?.addEventListener('click', () => {
      if (!started) {
        poster.classList.remove('show')
        canAutoplay = true
        start()
        return
      }
      if (token?.paused) {
        userPaused = false
        resume()
      } else {
        userPaused = true
        pause()
      }
    })
    $('[data-play]')?.addEventListener('click', () => {
      poster.classList.remove('show')
      canAutoplay = true
      start()
    })

    if (!canAutoplay) poster.classList.add('show')

    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          if (!canAutoplay) return
          if (!started) start()
          else if (!userPaused) resume()
        } else if (started) {
          pause()
        }
      },
      { threshold: 0.4 },
    )
    io.observe(host)

    return () => {
      io.disconnect()
      stop()
    }
  }, [])

  return <div ref={hostRef} className="demo-reel-host" style={{ display: 'block', width: '100%' }} />
}
