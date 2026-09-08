import { create } from "zustand";

import type { Translation, TranslationProgress } from "../api/types";
import type { ServerEvent } from "../api/sse";

interface TranslationState {
  byBlockId: Record<string, Translation>;
  progress: TranslationProgress | null;
  streamError: string | null;
  streamErrorCode: string | null;
  replace(items: Translation[]): void;
  apply(event: ServerEvent): void;
  clearRunError(): void;
  reset(): void;
}

const emptyTranslation = (blockId: string): Translation => ({
  block_id: blockId,
  status: "pending",
  zh_text: null,
  error: null,
  model: null,
  glossary_version: null,
  updated_at: null,
  cached: false,
  skip_reason: null,
});

export const useTranslationStore = create<TranslationState>((set) => ({
  byBlockId: {},
  progress: null,
  streamError: null,
  streamErrorCode: null,
  replace(items) {
    set({ byBlockId: Object.fromEntries(items.map((item) => [item.block_id, item])) });
  },
  apply(event) {
    if (event.event === "progress" || event.event === "finished") {
      set({ progress: event.data as unknown as TranslationProgress });
      return;
    }
    if (event.event === "error" && typeof event.data.error === "string") {
      set({
        streamError: event.data.error,
        streamErrorCode: typeof event.data.code === "string" ? event.data.code : null,
      });
    }
    if ((event.event === "block" || event.event === "error") && typeof event.data.block_id === "string") {
      set((state) => {
        const previous = state.byBlockId[event.data.block_id as string] ?? emptyTranslation(event.data.block_id as string);
        return {
          byBlockId: {
            ...state.byBlockId,
            [previous.block_id]: { ...previous, ...event.data } as Translation,
          },
        };
      });
    }
  },
  clearRunError() {
    set({ streamError: null, streamErrorCode: null });
  },
  reset() {
    set({ byBlockId: {}, progress: null, streamError: null, streamErrorCode: null });
  },
}));
