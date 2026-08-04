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
          : response.status === 413
            ? "This file is too large to upload. Choose a PDF under the upload limit."
            : response.status === 415
              ? "This file type is not supported. Please upload a PDF document."
              : response.status === 422
                ? "The PDF could not be read. Please check the file and upload it again."
                : response.status >= 500
                  ? "The document could not be processed right now. Please try again."
                  : "The request could not be completed. Please try again.";
      throw new ApiError(message, response.status, details);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "The request took too long. Large documents can take longer; please try again.",
        408,
      );
    }
    throw new ApiError(
      "The connection was interrupted. Please check your connection and try again.",
      0,
    );
  } finally {
    window.clearTimeout(timeout);
  }
}
