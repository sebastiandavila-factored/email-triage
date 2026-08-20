import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { PENDING_INVITE_KEY, nextAfterAuth } from './invite'

beforeEach(() => sessionStorage.clear())
afterEach(() => sessionStorage.clear())

describe('nextAfterAuth', () => {
  it('routes to the dashboard when no invite is pending', () => {
    expect(nextAfterAuth()).toBe('/dashboard')
  })

  it('routes to accept-invite when an invite token is stashed', () => {
    sessionStorage.setItem(PENDING_INVITE_KEY, 'tok-123')
    expect(nextAfterAuth()).toBe('/accept-invite')
  })
})
