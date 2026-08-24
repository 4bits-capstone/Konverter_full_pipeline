import { runtimeConfig } from "../config/runtime";
import { supabase } from "../lib/supabaseClient";

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

  const buildHeaders = async () => {
    const headers = new Headers(init.headers);
    if (
      init.body &&
      !(init.body instanceof FormData) &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return headers;
  };

  try {
    const { timeoutMs: _timeoutMs, ...fetchInit } = init;
    const doFetch = async () =>
      fetch(`${runtimeConfig.apiBaseUrl}${path}`, {
        ...fetchInit,
        headers: await buildHeaders(),
        signal: controller.signal,
      });

    let response = await doFetch();

    if (response.status === 401) {
      // The backend re-validates the token against Supabase on every
      // request, so a single 401 can be a transient validation hiccup
      // rather than a genuinely expired session. Force a fresh access
      // token and retry once before treating the user as signed out.
      const { error: refreshError } = await supabase.auth.refreshSession();
      if (!refreshError) {
        response = await doFetch();
      }
    }

    if (!response.ok) {
      if (response.status === 401) {
        await supabase.auth.signOut();
        throw new ApiError(
          "Your session has expired. Please sign in again.",
          response.status,
        );
      }

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
