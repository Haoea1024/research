import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import { Virtuoso, type ListRange, type VirtuosoHandle } from "react-virtuoso";

import type { Block, Figure } from "../api/types";
import { BlockCard } from "./BlockCard";
import { ACTIVE_LINE_RATIO } from "./types";

export interface BlockPaneHandle {
  scrollToBlock(blockId: string): boolean | Promise<boolean>;
}

export interface BlockPaneProps {
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
  const programmaticTarget = useRef<{ id: string; index: number; resolve: (accepted: boolean) => void } | null>(null);
  const programmaticPinnedId = useRef<string | null>(null);
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
      if (!virtuosoRef.current) return false;
      programmaticTarget.current?.resolve(false);
      programmaticPinnedId.current = null;
      virtuosoRef.current?.scrollToIndex({ index, align: "center", behavior: "auto" });
      return new Promise<boolean>((resolve) => {
        programmaticTarget.current = { id: blockId, index, resolve };
      });
    },
  }));

  const handleRangeChanged = (range: ListRange) => {
    const target = programmaticTarget.current;
    if (target) {
      if (target.index >= range.startIndex && target.index <= range.endIndex) {
        programmaticTarget.current = null;
        programmaticPinnedId.current = target.id;
        onActiveBlock?.(target.id);
        target.resolve(true);
      }
    } else if (!programmaticPinnedId.current) {
    const offset = Math.round((range.endIndex - range.startIndex) * ACTIVE_LINE_RATIO);
    const block = blocks[Math.min(range.endIndex, range.startIndex + offset)];
    if (block) onActiveBlock?.(block.id);
    }
    const visibleIds = blocks
      .slice(range.startIndex, range.endIndex + 1)
      .map((item) => item.id);
    const visibleKey = visibleIds.join("\u0000");
    if (visibleKey !== lastVisibleKey.current) {
      lastVisibleKey.current = visibleKey;
      onVisibleBlocks?.(visibleIds);
    }
  };

  useEffect(() => () => {
    programmaticTarget.current?.resolve(false);
    programmaticTarget.current = null;
    programmaticPinnedId.current = null;
  }, []);

  const handleUserIntent = () => {
    programmaticTarget.current?.resolve(false);
    programmaticTarget.current = null;
    programmaticPinnedId.current = null;
    onUserIntent?.();
  };

  return (
    <section className="block-pane" aria-label="翻译块流">
      <header className="pane-header">
        <strong>中文翻译块流</strong>
        <span>英文按块回退</span>
      </header>
      <div
        className="block-list-shell"
        onWheel={handleUserIntent}
        onPointerDown={handleUserIntent}
        onTouchStart={handleUserIntent}
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
