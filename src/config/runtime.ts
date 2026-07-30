export const runtimeConfig = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/+$/, ''),
  requestTimeoutMs: Number(import.meta.env.VITE_API_TIMEOUT_MS || 20_000),
}
