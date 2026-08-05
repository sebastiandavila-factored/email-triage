import { useEffect, useRef } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { nextAfterAuth } from '../invite'
import { LANDING_BODY } from './landingBody'
import './Landing.css'

// The public marketing/landing page — the app's root ("/"). An authenticated
// visitor (including the SSO return, whose #token AuthContext captures on
// bootstrap) is bounced straight into the app.
export function Landing() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const rootEl = document.documentElement
    // Enable the scroll-reveal hidden state only with JS (never a blank page).
    rootEl.classList.add('js')
    const container = ref.current
    if (!container) return

    // Theme toggle: flip data-theme on <html>, overriding prefers-color-scheme.
    const themeBtn = container.querySelector<HTMLButtonElement>('#themeBtn')
    const onTheme = () => {
      const cur =
        rootEl.getAttribute('data-theme') ??
        (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      rootEl.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark')
    }
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
  }, [navigate])

  if (token) return <Navigate to={nextAfterAuth()} replace />
  return <div className="ts-root" ref={ref} dangerouslySetInnerHTML={{ __html: LANDING_BODY }} />
}
