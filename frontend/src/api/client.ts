import type { Block, Figure, Paper, TranslateRun, Translation } from "./types";

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

async function requestJson<T>(
  path: string,
  signal?: AbortSignal,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...init.headers },
    signal,
  });
  if (!response.ok) {
    const detail = await errorMessage(response);
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
  translations(paperId: string, signal?: AbortSignal) {
    return requestJson<Translation[]>(
      `/api/papers/${encodeURIComponent(paperId)}/translations`,
      signal,
    );
  },
  translate(paperId: string, body: { pages?: number[]; block_ids?: string[] } = {}) {
    return requestJson<TranslateRun>(
      `/api/papers/${encodeURIComponent(paperId)}/translate`,
      undefined,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    );
  },
  viewport(paperId: string, visibleBlockIds: string[]) {
    return requestEmpty(`/api/papers/${encodeURIComponent(paperId)}/viewport`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible_block_ids: visibleBlockIds }),
    });
  },
  retranslate(blockId: string) {
    return requestJson<TranslateRun>(
      `/api/blocks/${encodeURIComponent(blockId)}/retranslate`,
      undefined,
      { method: "POST" },
    );
  },
};

async function requestEmpty(url: string, init: RequestInit): Promise<void> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await errorMessage(response);
    throw new ApiError(`Request failed (${response.status}): ${detail}`, response.status, detail);
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}
