import { useCallback, useMemo, useRef } from "react";

import type { Block } from "../api/types";
import { useReaderStore, type SyncOrigin } from "../stores/readerStore";
import type { BlockPaneHandle } from "./BlockPane";
import type { PageReadyHandle } from "./types";

type Pane = Exclude<SyncOrigin, null>;

export function useSyncController(blocks: Block[]) {
  const pdfPaneRef = useRef<PageReadyHandle>(null);
  const blockPaneRef = useRef<BlockPaneHandle>(null);
  const activeByPane = useRef<Record<Pane, string | null>>({ pdf: null, blocks: null });
  const blockById = useMemo(
    () => new Map(blocks.map((block) => [block.id, block])),
    [blocks],
  );

  const handleUserIntent = useCallback((origin: Pane) => {
    useReaderStore.getState().takeControl(origin);
    activeByPane.current[origin] = null;
  }, []);

  const handleActiveBlock = useCallback(
    (origin: Pane, blockId: string) => {
      activeByPane.current[origin] = blockId;
      const state = useReaderStore.getState();

      if (state.syncOrigin && state.syncOrigin !== origin) {
        if (state.syncTargetBlockId === blockId) {
          state.setActiveBlockId(blockId);
        }
        return;
      }

      state.setActiveBlockId(blockId);
      if (state.syncOrigin === origin && state.syncTargetBlockId === blockId) return;

      const targetPane: Pane = origin === "pdf" ? "blocks" : "pdf";
      const generation = state.beginSync(origin, blockId);
      if (activeByPane.current[targetPane] === blockId) {
        useReaderStore.getState().finishSync(generation);
        return;
      }

      if (origin === "pdf") {
        const accepted = blockPaneRef.current?.scrollToBlock(blockId) ?? false;
        if (!accepted) useReaderStore.getState().finishSync(generation);
        return;
      }

      const block = blockById.get(blockId);
      const pdfPane = pdfPaneRef.current;
      if (!block || !pdfPane) {
        useReaderStore.getState().finishSync(generation);
        return;
      }
      void pdfPane
        .scrollToBlock(block, generation)
        .then((accepted) => {
          if (!accepted) useReaderStore.getState().finishSync(generation);
        })
        .catch(() => useReaderStore.getState().finishSync(generation));
    },
    [blockById],
  );

  return {
    pdfPaneRef,
    blockPaneRef,
    onPdfActiveBlock: (blockId: string) => handleActiveBlock("pdf", blockId),
    onBlocksActiveBlock: (blockId: string) => handleActiveBlock("blocks", blockId),
    onPdfUserIntent: () => handleUserIntent("pdf"),
    onBlocksUserIntent: () => handleUserIntent("blocks"),
  };
}
