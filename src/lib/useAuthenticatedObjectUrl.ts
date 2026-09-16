import { useEffect, useRef, useState } from 'react'
import { apiRequest } from '../services/httpClient'
import { runtimeConfig } from '../config/runtime'

interface AuthenticatedObjectUrlState {
  src: string | null
  loading: boolean
  failed: boolean
}

/** Splits a `PublicationService`-built absolute URL into the relative path
 * `apiRequest` expects and the client-side fragment (e.g. "#page=3"), which
 * is never sent to the server. */
function toRequestPath(absoluteUrl: string): [path: string, fragment: string | undefined] {
  const [requestUrl, fragment] = absoluteUrl.split('#', 2)
  const path = requestUrl.startsWith(runtimeConfig.apiBaseUrl)
    ? requestUrl.slice(runtimeConfig.apiBaseUrl.length)
    : requestUrl
  return [path, fragment]
}

/** For a one-off "open in a new tab" action (the source PDF link) rather
 * than a persisted `<img>` — same auth problem, same blob-URL fix, but
 * fetched only on click and opened immediately rather than tracked in
 * component state. The object URL is deliberately never revoked: the new
 * tab owns it for as long as it stays open. */
export async function openAuthenticatedDocument(absoluteUrl: string): Promise<void> {
  const [path, fragment] = toRequestPath(absoluteUrl)
  const blob = await apiRequest<Blob>(path, { responseType: 'blob' })
  const objectUrl = URL.createObjectURL(blob)
  window.open(fragment ? `${objectUrl}#${fragment}` : objectUrl, '_blank', 'noreferrer')
}

/** These endpoints require a Supabase bearer token per-request (so the
 * backend can enforce document ownership) — a plain `<img src>`/`<a href>`
 * can never carry that header, so every evidence-crop and source-PDF link
 * built from `PublicationService` (a full absolute URL, for historical
 * reasons — it used to point at public, unauthenticated endpoints) has to
 * be re-fetched here with the same auth as `apiRequest`, then swapped for
 * a local blob URL the browser can actually load. */
export function useAuthenticatedObjectUrl(
  absoluteUrl: string | undefined,
): AuthenticatedObjectUrlState {
  const [state, setState] = useState<AuthenticatedObjectUrlState>({
    src: null,
    loading: false,
    failed: false,
  })
  const objectUrlRef = useRef<string | null>(null)

  useEffect(() => {
    const revokePrevious = () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }
    if (!absoluteUrl) {
      revokePrevious()
      setState({ src: null, loading: false, failed: false })
      return
    }
    const [path, fragment] = toRequestPath(absoluteUrl)
    let cancelled = false
    setState({ src: null, loading: true, failed: false })
    apiRequest<Blob>(path, { responseType: 'blob' })
      .then((blob) => {
        if (cancelled) return
        revokePrevious()
        const objectUrl = URL.createObjectURL(blob)
        objectUrlRef.current = objectUrl
        setState({
          src: fragment ? `${objectUrl}#${fragment}` : objectUrl,
          loading: false,
          failed: false,
        })
      })
      .catch(() => {
        if (cancelled) return
        setState({ src: null, loading: false, failed: true })
      })
    return () => {
      cancelled = true
    }
  }, [absoluteUrl])

  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
    },
    [],
  )

  return state
}
