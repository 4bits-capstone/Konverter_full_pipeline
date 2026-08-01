import { runtimeConfig } from "../config/runtime";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiRequestInit extends RequestInit {
  timeoutMs?: number;
}

export async function apiRequest<T>(
  path: string,
  init: ApiRequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    init.timeoutMs ?? runtimeConfig.requestTimeoutMs,
  );
  const headers = new Headers(init.headers);

  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const { timeoutMs: _timeoutMs, ...fetchInit } = init;
    const response = await fetch(`${runtimeConfig.apiBaseUrl}${path}`, {
      ...fetchInit,
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      const details = await response.json().catch(() => null);
      const message =
        typeof details?.detail === "string"
          ? details.detail
          : `API request failed (${response.status})`;
      throw new ApiError(message, response.status, details);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "The backend request timed out. Large documents can take longer — try again and the cached output will finish faster.",
        408,
      );
    }
    throw new ApiError(
      error instanceof Error ? error.message : "Unable to reach the backend",
      0,
    );
  } finally {
    window.clearTimeout(timeout);
  }
}
