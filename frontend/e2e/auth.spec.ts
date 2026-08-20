import { type Page, expect, test } from '@playwright/test'

/**
 * Mock the auth handshake the app performs on login:
 *   POST /auth/login  → issue a token
 *   GET  /auth/me     → resolve the current user (called by login() and by the
 *                       AuthProvider effect when the token changes)
 *   GET  /workspaces  → best-effort list (empty is fine)
 * No backend is involved.
 */
async function mockAuth(page: Page) {
  await page.route('**/auth/login', (route) =>
    route.fulfill({
      json: {
        access_token: 'e2e-token',
        token_type: 'bearer',
        email: 'user@e2e.test',
        display_name: 'E2E User',
        tenant_id: 't-1',
        tenant_name: 'E2E Workspace',
        tenant_type: 'personal',
        plan: 'free',
        role: 'owner',
        message: 'ok',
      },
    }),
  )
  await page.route('**/auth/me', (route) =>
    route.fulfill({
      json: {
        user_id: 'u-1',
        email: 'user@e2e.test',
        display_name: 'E2E User',
        email_verified: true,
        tenant_id: 't-1',
        tenant_name: 'E2E Workspace',
        tenant_type: 'personal',
        plan: 'free',
        role: 'owner',
      },
    }),
  )
  await page.route('**/workspaces', (route) => route.fulfill({ json: [] }))
}

test.describe('auth', () => {
  test('an unauthenticated visit to a protected route redirects to /login', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByPlaceholder('you@company.com')).toBeVisible()
  })

  test('logging in with valid credentials lands on the dashboard', async ({ page }) => {
    await mockAuth(page)

    await page.goto('/login')
    await page.getByPlaceholder('you@company.com').fill('user@e2e.test')
    await page.getByPlaceholder('••••••••').fill('correct-horse')
    await page.getByRole('button', { name: /sign in/i }).click()

    await expect(page).toHaveURL(/\/dashboard$/)
    await expect(page.getByRole('heading', { name: /hello, e2e user/i })).toBeVisible()
  })
})
