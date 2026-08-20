import { describe, expect, it } from 'vitest'

import { can } from './rbac'

describe('can', () => {
  it('owner has the owner-only scopes', () => {
    expect(can('owner', 'workspace:delete')).toBe(true)
    expect(can('owner', 'prompt:publish')).toBe(true)
  })

  it('admin has manage but not delete/publish', () => {
    expect(can('admin', 'workspace:manage')).toBe(true)
    expect(can('admin', 'workspace:delete')).toBe(false)
    expect(can('admin', 'prompt:publish')).toBe(false)
  })

  it('member is limited to triage:write', () => {
    expect(can('member', 'triage:write')).toBe(true)
    expect(can('member', 'triage:configure')).toBe(false)
    expect(can('member', 'traces:read')).toBe(false)
  })

  it('returns false for an undefined or unknown role', () => {
    expect(can(undefined, 'triage:write')).toBe(false)
    expect(can('ghost', 'triage:write')).toBe(false)
  })

  it('returns false for an unknown scope', () => {
    expect(can('owner', 'nonexistent:scope')).toBe(false)
  })
})
