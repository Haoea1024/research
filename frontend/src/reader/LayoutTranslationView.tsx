import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import type { Block, Figure } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { closestBlockAtGuide } from "./activeBlock";
import { deriveDocumentLayout } from "./layoutEngine";
import { LAYOUT_DEFAULT_PAGE_HEIGHT, LAYOUT_DEFAULT_PAGE_WIDTH } from "./layoutConstants";
import { LayoutPage } from "./LayoutPage";
import { ACTIVE_LINE_RATIO, type PageMetrics, type TranslationPaneHandle } from "./types";

interface Props {
  blocks: Block[];
  figures: Figure[];
  pageMetrics: Map<number, PageMetrics>;
  onActiveBlock?: (blockId: string) => void;
  onUserIntent?: () => void;
  onVisibleBlocks?: (blockIds: string[]) => void;
  onRetranslate?: (blockId: string) => void;
}

interface PendingTarget { generation: number; resolve: (accepted: boolean) => void; }

export const LayoutTranslationView = forwardRef<TranslationPaneHandle, Props>(function LayoutTranslationView({ blocks, figures, pageMetrics, onActiveBlock, onUserIntent, onVisibleBlocks, onRetranslate }, ref) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollParent, setScrollParent] = useState<HTMLDivElement | null>(null);
  const elements = useRef(new Map<string, HTMLElement>());
  const pending = useRef(new Map<string, PendingTarget>());
  const programmaticPinnedId = useRef<string | null>(null);
  const frame = useRef<number | null>(null);
  const lastVisibleKey = useRef("");
  const layouts = useMemo(() => deriveDocumentLayout(blocks), [blocks]);
  const pageIndexByBlockId = useMemo(() => new Map(blocks.map((block) => [block.id, block.page])), [blocks]);
  const figuresByBlockId = useMemo(() => new Map(figures.flatMap((figure) => figure.block_id ? [[figure.block_id, figure] as const] : [])), [figures]);
  const attachScrollParent = useCallback((node: HTMLDivElement | null) => {
    scrollRef.current = node;
    setScrollParent(node);
  }, []);

  const positionElement = (blockId: string, generation: number) => {
    const container = scrollRef.current;
    const element = elements.current.get(blockId);
    if (!container || !element || useReaderStore.getState().syncGeneration !== generation) return false;
    const containerRect = container.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();
    container.scrollTo({ top: Math.max(0, container.scrollTop + elementRect.top - containerRect.top - container.clientHeight * ACTIVE_LINE_RATIO + elementRect.height / 2), behavior: "auto" });
    return true;
  };

  const registerElement = (blockId: string, element: HTMLElement | null) => {
    if (element) elements.current.set(blockId, element);
    else elements.current.delete(blockId);
    const target = element ? pending.current.get(blockId) : undefined;
    if (target) {
      pending.current.delete(blockId);
      target.resolve(positionElement(blockId, target.generation));
    }
  };

  useImperativeHandle(ref, () => ({
    scrollToBlock(blockId, generation) {
      const pageIndex = pageIndexByBlockId.get(blockId);
      if (pageIndex === undefined) return false;
      programmaticPinnedId.current = blockId;
      const previous = pending.current.get(blockId);
      if (previous) previous.resolve(false);
      if (elements.current.has(blockId)) return positionElement(blockId, generation);
      virtuosoRef.current?.scrollToIndex({ index: pageIndex, align: "center", behavior: "auto" });
      return new Promise<boolean>((resolve) => pending.current.set(blockId, { generation, resolve }));
    },
  }));

  const handleScroll = () => {
    if (frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const container = scrollRef.current;
      if (!container) return;
      const visible = [...container.querySelectorAll<HTMLElement>("[data-block-id]")].filter((element) => {
        const rect = element.getBoundingClientRect();
        const root = container.getBoundingClientRect();
        return rect.bottom >= root.top && rect.top <= root.bottom;
      });
      const active = programmaticPinnedId.current ?? closestBlockAtGuide(container, visible);
      if (active) onActiveBlock?.(active);
      const ids = visible.map((element) => element.dataset.blockId).filter((id): id is string => Boolean(id));
      const key = ids.join("\u0000");
      if (key !== lastVisibleKey.current) { lastVisibleKey.current = key; onVisibleBlocks?.(ids); }
    });
  };

  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    for (const target of pending.current.values()) target.resolve(false);
    pending.current.clear();
  }, []);

  return (
    <div className="layout-list-shell" ref={attachScrollParent} data-testid="layout-scroll" tabIndex={0} onScroll={handleScroll} onWheel={() => { programmaticPinnedId.current = null; onUserIntent?.(); }} onPointerDown={() => { programmaticPinnedId.current = null; onUserIntent?.(); }} onTouchStart={() => { programmaticPinnedId.current = null; onUserIntent?.(); }}>
      {scrollParent ? <Virtuoso ref={virtuosoRef} customScrollParent={scrollParent} data={layouts} computeItemKey={(_, layout) => layout.page} itemContent={(_, layout) => <LayoutPage layout={layout} metrics={pageMetrics.get(layout.page) ?? { width: LAYOUT_DEFAULT_PAGE_WIDTH, height: LAYOUT_DEFAULT_PAGE_HEIGHT }} figuresByBlockId={figuresByBlockId} registerElement={registerElement} onRetranslate={onRetranslate} />} /> : null}
    </div>
  );
});
