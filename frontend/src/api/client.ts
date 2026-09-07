import type { Block, Figure, Paper } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Preserve the HTTP status when the body is not JSON.
    }
    throw new ApiError(`Request failed (${response.status}): ${detail}`, response.status, detail);
  }
  return (await response.json()) as T;
}

export const paperApi = {
  list(signal?: AbortSignal) {
    return requestJson<Paper[]>("/api/papers", signal);
  },
  get(paperId: string, signal?: AbortSignal) {
    return requestJson<Paper>(`/api/papers/${encodeURIComponent(paperId)}`, signal);
  },
  blocks(paperId: string, signal?: AbortSignal) {
    return requestJson<Block[]>(
      `/api/papers/${encodeURIComponent(paperId)}/blocks`,
      signal,
    );
  },
  figures(paperId: string, signal?: AbortSignal) {
    return requestJson<Figure[]>(
      `/api/papers/${encodeURIComponent(paperId)}/figures`,
      signal,
    );
  },
  pdfUrl(paperId: string) {
    return `/api/papers/${encodeURIComponent(paperId)}/pdf`;
  },
};
