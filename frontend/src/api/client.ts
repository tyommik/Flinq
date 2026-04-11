/**
 * Minimal API client.
 *
 * For the skeleton this is a handful of fetch wrappers. As the API surface
 * grows, generated OpenAPI types will live next to this file and the wrappers
 * will shift to consume them.
 */

export interface HealthResponse {
  status: string
  version: string
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`Request failed: ${String(response.status)} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health')
}