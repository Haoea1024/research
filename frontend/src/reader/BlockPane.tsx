import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import { Virtuoso, type ListRange, type VirtuosoHandle } from "react-virtuoso";

import type { Block, Figure } from "../api/types";
import { BlockCard } from "./BlockCard";
import { ACTIVE_LINE_RATIO } from "./types";

export interface BlockPaneHandle {
  scrollToBlock(blockId: string): boolean;
}

interface BlockPaneProps {
  blocks: Block[];
  figures: Figure[];
  onActiveBlock?: (blockId: string) => void;
  onUserIntent?: () => void;
  onVisibleBlocks?: (blockIds: string[]) => void;
  onRetranslate?: (blockId: string) => void;
}

export const BlockPane = forwardRef<BlockPaneHandle, BlockPaneProps>(function BlockPane(
  { blocks, figures, onActiveBlock, onUserIntent, onVisibleBlocks, onRetranslate },
  ref,
) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const lastVisibleKey = useRef("");
  const indexById = useMemo(
    () => new Map(blocks.map((block, index) => [block.id, index])),
    [blocks],
  );
  const figuresByBlockId = useMemo(
    () =>
      new Map(
        figures.flatMap((figure) =>
          figure.block_id ? ([[figure.block_id, figure]] as const) : [],
        ),
      ),
    [figures],
  );

  useImperativeHandle(ref, () => ({
    scrollToBlock(blockId) {
      const index = indexById.get(blockId);
      if (index === undefined) return false;
      virtuosoRef.current?.scrollToIndex({ index, align: "center", behavior: "auto" });
      return virtuosoRef.current !== null;
    },
  }));

  const handleRangeChanged = (range: ListRange) => {
    const offset = Math.round((range.endIndex - range.startIndex) * ACTIVE_LINE_RATIO);
    const block = blocks[Math.min(range.endIndex, range.startIndex + offset)];
    if (block) onActiveBlock?.(block.id);
    const visibleIds = blocks
      .slice(range.startIndex, range.endIndex + 1)
      .map((item) => item.id);
    const visibleKey = visibleIds.join("\u0000");
    if (visibleKey !== lastVisibleKey.current) {
      lastVisibleKey.current = visibleKey;
      onVisibleBlocks?.(visibleIds);
    }
  };

  return (
    <section className="block-pane" aria-label="翻译块流">
      <header className="pane-header">
        <strong>中文翻译块流</strong>
        <span>英文按块回退</span>
      </header>
      <div
        className="block-list-shell"
        onWheel={onUserIntent}
        onPointerDown={onUserIntent}
        onTouchStart={onUserIntent}
      >
        <Virtuoso
          ref={virtuosoRef}
          data={blocks}
          rangeChanged={handleRangeChanged}
          computeItemKey={(_, block) => block.id}
          itemContent={(_, block) => (
            <BlockCard
              block={block}
              figure={figuresByBlockId.get(block.id)}
              onRetranslate={onRetranslate}
            />
          )}
        />
      </div>
    </section>
  );
});
