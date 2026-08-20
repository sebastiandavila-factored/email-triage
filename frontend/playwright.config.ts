import { defineConfig, devices } from '@playwright/test'

// e2e runs against the *built* app served by `vite preview` (production bundle,
// no dev server / no Vite proxy). The backend is never started: each spec mocks
// the API at the network layer with page.route(), so the suite is deterministic
// and needs no Postgres/Groq.
const PORT = 4173

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['html', { open: 'never' }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // Serves ./dist — the CI job (and local run) builds first.
    command: `npm run preview -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
