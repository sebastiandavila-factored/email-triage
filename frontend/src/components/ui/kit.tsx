import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

// Shared UI primitives in the Triage Studio "control-room" language (Plan 34). All colors
// are semantic tokens (bridged from theme.css) so everything is light/dark-aware.

function cx(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

// ── Button ──────────────────────────────────────────────────────────────────

type Variant = 'primary' | 'ghost' | 'danger'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-paper hover:bg-brand-bright',
  ghost: 'border border-line text-ink hover:border-line-strong hover:bg-brand-wash',
  danger: 'border border-line text-crit hover:bg-brand-wash hover:border-crit',
}

export function Button({
  variant = 'primary',
  className,
  children,
  ...props
}: { variant?: Variant } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium',
        'transition disabled:opacity-50 disabled:cursor-not-allowed',
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

// ── Card ────────────────────────────────────────────────────────────────────

export function Card({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <div
      className={cx(
        'bg-paper border border-line rounded-2xl shadow-[var(--shadow)]',
        className,
      )}
    >
      {children}
    </div>
  )
}

// ── SectionHead (mono kicker + title + optional sub) ──────────────────────────

export function SectionHead({
  kicker,
  title,
  sub,
  className,
  actions,
}: {
  kicker?: string
  title: ReactNode
  sub?: ReactNode
  className?: string
  actions?: ReactNode
}) {
  return (
    <div className={cx('flex items-start justify-between gap-4', className)}>
      <div>
        {kicker && (
          <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand font-semibold mb-2">
            {kicker}
          </div>
        )}
        <h2 className="text-xl font-semibold text-ink tracking-tight">{title}</h2>
        {sub && <p className="text-sm text-muted mt-1">{sub}</p>}
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </div>
  )
}

// ── Tag / Badge (mono) ────────────────────────────────────────────────────────

export function Tag({
  children,
  tone = 'brand',
  className,
}: {
  children: ReactNode
  tone?: 'brand' | 'amber' | 'muted'
  className?: string
}) {
  const tones = {
    brand: 'bg-brand-wash text-brand',
    amber: 'bg-amber-wash text-amber',
    muted: 'bg-ground text-muted border border-line',
  } as const
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-full px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-wide',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

// ── Field (labelled input) ────────────────────────────────────────────────────

export function Field({
  label,
  className,
  ...props
}: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-ink-soft mb-1">{label}</span>
      <input
        className={cx(
          'w-full bg-paper border border-line rounded-lg px-3 py-2 text-sm text-ink',
          'placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand',
          className,
        )}
        {...props}
      />
    </label>
  )
}
