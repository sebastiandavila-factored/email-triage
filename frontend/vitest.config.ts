import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    // jsdom gives the pure-logic tests a DOM: sessionStorage (invite.ts),
    // fetch/TextDecoder (api.ts). Component rendering lives in the Playwright
    // e2e suite, not here.
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    clearMocks: true,
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      // `all` counts every source file, not only the ones a test imported — so
      // the number reflects the whole SPA. NOTE: this is UNIT coverage only;
      // the React pages/components are exercised by the Playwright e2e suite,
      // which this metric does not see. Read the two together.
      all: true,
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.ts',
        'src/main.tsx', // app bootstrap
        'src/vite-env.d.ts',
      ],
    },
  },
})
