import { afterEach, describe, expect, it, vi } from 'vitest'

import { API_BASE, ApiError, api, setUnauthorizedHandler } from './api'

/** Stub the global fetch with a single canned Response-like object. */
function stubFetch(res: { ok: boolean; status: number; jsonData?: unknown }) {
  const mock = vi.fn().mockResolvedValue({
    ok: res.ok,
    status: res.status,
    statusText: 'Stubbed',
    json: async () => res.jsonData,
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

afterEach(() => {
  vi.unstubAllGlobals()
  setUnauthorizedHandler(null)
})

describe('API_BASE', () => {
  it('is empty when VITE_API_URL is unset (relative → Vite proxy)', () => {
    expect(API_BASE).toBe('')
  })
})

describe('request success', () => {
  it('POSTs JSON and returns the parsed body', async () => {
    const mock = stubFetch({ ok: true, status: 200, jsonData: { access_token: 'jwt-abc' } })

    const out = await api.login('a@b.com', 'pw')

    expect(out.access_token).toBe('jwt-abc')
    const [url, init] = mock.mock.calls[0]
    expect(url).toBe('/auth/login')
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ email: 'a@b.com', password: 'pw' })
  })

  it('returns undefined on 204 No Content', async () => {
    stubFetch({ ok: true, status: 204 })
    await expect(api.deleteWorkspace('tok', 'tid-1')).resolves.toBeUndefined()
  })
})

describe('request errors', () => {
  it('throws ApiError with status and string detail', async () => {
    stubFetch({ ok: false, status: 403, jsonData: { detail: 'Not allowed' } })

    const err = await api.me('tok').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(403)
    expect(err.detail).toBe('Not allowed')
  })

  it('flattens a 422 validation detail array into one message', async () => {
    stubFetch({
      ok: false,
      status: 422,
      jsonData: { detail: [{ msg: 'invalid email' }, { msg: 'too short' }] },
    })

    const err = await api.signup('bad', 'x', 'Name').catch((e) => e)
    expect(err.detail).toBe('invalid email; too short')
  })
})

describe('401 handling', () => {
  it('on an authenticated 401: fires the handler and throws the session-expired message', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    stubFetch({ ok: false, status: 401, jsonData: { detail: 'Invalid token' } })

    const err = await api.me('stale-token').catch((e) => e)
    expect(onUnauthorized).toHaveBeenCalledOnce()
    expect(err).toBeInstanceOf(ApiError)
    expect(err.detail).toBe('Your session expired. Please log in again.')
  })

  it('on an unauthenticated 401 (no token): does NOT fire the handler', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    stubFetch({ ok: false, status: 401, jsonData: { detail: 'Bad credentials' } })

    const err = await api.login('a@b.com', 'wrong').catch((e) => e)
    expect(onUnauthorized).not.toHaveBeenCalled()
    expect(err.detail).toBe('Bad credentials')
  })
})
