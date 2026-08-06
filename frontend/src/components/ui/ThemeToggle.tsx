import { useTheme } from '../../ThemeContext'

// Light/dark toggle (Plan 34). Sun/moon glyph reflecting the *current* theme.
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme()
  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      title="Toggle theme"
      className={
        'inline-flex items-center justify-center h-8 w-8 rounded-lg border border-line ' +
        'text-muted hover:text-ink hover:border-line-strong transition ' +
        (className ?? '')
      }
    >
      {theme === 'dark' ? '☾' : '☀'}
    </button>
  )
}
