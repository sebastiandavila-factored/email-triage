import { expect, test } from '@playwright/test'

test.describe('landing', () => {
  test('renders and exposes a Log in CTA', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('link', { name: /log in/i }).first()).toBeVisible()
  })

  test('a Log in CTA navigates client-side to /login', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /log in/i }).first().click()
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByPlaceholder('you@company.com')).toBeVisible()
  })
})
