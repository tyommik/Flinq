/**
 * API client with cookie-based session + CSRF (ADR-0008).
 *
 * The backend issues `flinq_session` (HttpOnly) and `flinq_csrf` (readable JS)
 * cookies. For mutating requests we read the CSRF cookie and echo it in the
 * `X-CSRF-Token` header (double-submit pattern).
 */

export interface HealthResponse {
  status: string
  version: string
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function getCookie(name: string): string | null {
  const match = document.cookie.match(
    new RegExp('(?:^|; )' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '=([^;]*)'),
  )
  return match ? decodeURIComponent(match[1]!) : null
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const method = (init.method ?? 'GET').toUpperCase()

  if (MUTATING_METHODS.has(method)) {
    const csrf = getCookie('flinq_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }

  const response = await fetch(path, { ...init, headers, credentials: 'include' })

  if (!response.ok) {
    const text = await response.text()
    let detail = response.statusText
    try {
      const body = JSON.parse(text) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // body wasn't JSON; keep statusText
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function fetchHealth(): Promise<HealthResponse> {
  return api<HealthResponse>('/health')
}
