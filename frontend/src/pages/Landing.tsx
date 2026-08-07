import { useEffect, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { useTheme } from '../ThemeContext'
import { nextAfterAuth } from '../invite'
import { LANDING_BODY } from './landingBody'
import { DemoReel } from '../components/DemoReel'
import './Landing.css'

// The public marketing/landing page — the app's root ("/"). An authenticated
// visitor (including the SSO return, whose #token AuthContext captures on
// bootstrap) is bounced straight into the app.
export function Landing() {
  const { token } = useAuth()
  const { toggle } = useTheme()
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const rootEl = document.documentElement
    // Enable the scroll-reveal hidden state only with JS (never a blank page).
    rootEl.classList.add('js')
    const container = ref.current
    if (!container) return

    // Theme toggle: delegate to the shared ThemeProvider so the landing and the app
    // share one theme state (persisted, respects prefers-color-scheme).
    const themeBtn = container.querySelector<HTMLButtonElement>('#themeBtn')
    const onTheme = () => toggle()
    themeBtn?.addEventListener('click', onTheme)

    // Internal links (the "Log in" CTAs) navigate client-side; #hash links keep
    // their native in-page scroll.
    const onClick = (e: MouseEvent) => {
      const anchor = (e.target as HTMLElement).closest('a')
      const href = anchor?.getAttribute('href') ?? ''
      if (href.startsWith('/')) {
        e.preventDefault()
        navigate(href)
      }
    }
    container.addEventListener('click', onClick)

    // Scroll reveal + the hero confidence bar.
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    const fill = container.querySelector<HTMLElement>('#confFill')
    const fillBar = () => {
      if (fill) fill.style.width = fill.getAttribute('data-to') ?? ''
    }
    const items = container.querySelectorAll<HTMLElement>('.reveal')
    let io: IntersectionObserver | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    if (reduce || !('IntersectionObserver' in window)) {
      items.forEach((el) => el.classList.add('in'))
      fillBar()
    } else {
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((en) => {
            if (en.isIntersecting) {
              en.target.classList.add('in')
              io?.unobserve(en.target)
            }
          })
        },
        { threshold: 0.16 },
      )
      items.forEach((el) => io?.observe(el))
      timer = setTimeout(fillBar, 450)
    }

    return () => {
      themeBtn?.removeEventListener('click', onTheme)
      container.removeEventListener('click', onClick)
      io?.disconnect()
      if (timer) clearTimeout(timer)
    }
  }, [navigate, toggle])

  // The landing body is injected as an HTML string; mount the React <DemoReel> into its
  // #demo-mount node as its own root — decoupled from the innerHTML reconciliation (Plan 35).
  // The root is stashed on the node and created only once (guards StrictMode's double-invoke
  // and HMR against "createRoot() called twice on the same container"). The DemoReel pauses its
  // engine via IntersectionObserver when its host leaves the viewport, so there's no CPU leak
  // if the landing unmounts.
  useEffect(() => {
    const node = ref.current?.querySelector<HTMLElement>('#demo-mount') as
      | (HTMLElement & { _demoRoot?: Root })
      | null
    if (!node) return
    if (!node._demoRoot) {
      node._demoRoot = createRoot(node)
      node._demoRoot.render(<DemoReel />)
    }
  }, [])

  if (token) return <Navigate to={nextAfterAuth()} replace />
  return <div className="ts-root" ref={ref} dangerouslySetInnerHTML={{ __html: LANDING_BODY }} />
}
