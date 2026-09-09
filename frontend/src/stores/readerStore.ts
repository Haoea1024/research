import { create } from "zustand";

export type ViewMode = "layout" | "structured";
export type SyncOrigin = "pdf" | "blocks" | null;

interface ReaderState {
  activeBlockId: string | null;
  hoverBlockId: string | null;
  viewMode: ViewMode;
  syncOrigin: SyncOrigin;
  syncGeneration: number;
  syncTargetBlockId: string | null;
  setActiveBlockId: (blockId: string | null) => void;
  setHoverBlockId: (blockId: string | null) => void;
  setViewMode: (viewMode: ViewMode) => void;
  beginSync: (origin: Exclude<SyncOrigin, null>, targetBlockId: string) => number;
  takeControl: (origin: Exclude<SyncOrigin, null>) => number;
  finishSync: (generation: number) => void;
  reset: () => void;
}

const initialState = {
  activeBlockId: null,
  hoverBlockId: null,
  viewMode: "layout" as const,
  syncOrigin: null,
  syncGeneration: 0,
  syncTargetBlockId: null,
};

export const useReaderStore = create<ReaderState>((set, get) => ({
  ...initialState,
  setActiveBlockId: (activeBlockId) => set({ activeBlockId }),
  setHoverBlockId: (hoverBlockId) => set({ hoverBlockId }),
  setViewMode: (viewMode) => set({ viewMode }),
  beginSync: (syncOrigin, syncTargetBlockId) => {
    const syncGeneration = get().syncGeneration + 1;
    set({ syncOrigin, syncTargetBlockId, syncGeneration });
    return syncGeneration;
  },
  takeControl: (syncOrigin) => {
    const syncGeneration = get().syncGeneration + 1;
    set({ syncOrigin, syncTargetBlockId: null, syncGeneration });
    return syncGeneration;
  },
  finishSync: (generation) => {
    if (get().syncGeneration === generation) {
      set({ syncOrigin: null, syncTargetBlockId: null });
    }
  },
  reset: () => set({ ...initialState, syncGeneration: get().syncGeneration + 1 }),
}));
