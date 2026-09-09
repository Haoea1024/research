import { forwardRef, useCallback, useImperativeHandle, useRef } from "react";
import type { Block, Figure } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { LayoutTranslationView } from "./LayoutTranslationView";
import { StructuredBlockView } from "./StructuredBlockView";
import type { PageMetrics, TranslationPaneHandle } from "./types";

interface Props { blocks: Block[]; figures: Figure[]; pageMetrics: Map<number, PageMetrics>; onActiveBlock?: (blockId: string) => void; onUserIntent?: () => void; onVisibleBlocks?: (blockIds: string[]) => void; onRetranslate?: (blockId: string) => void; }
interface RestoreTarget { blockId: string; generation: number; }

export const TranslationPane = forwardRef<TranslationPaneHandle, Props>(function TranslationPane(props, ref) {
  const viewMode = useReaderStore((state) => state.viewMode);
  const setViewMode = useReaderStore((state) => state.setViewMode);
  const paneHandle = useRef<TranslationPaneHandle | null>(null);
  const restore = useRef<RestoreTarget | null>(null);

  const runRestore = useCallback((handle: TranslationPaneHandle, target: RestoreTarget) => {
    void Promise.resolve(handle.scrollToBlock(target.blockId, target.generation)).then((accepted) => {
      if (!accepted && restore.current?.generation === target.generation) {
        restore.current = null;
        useReaderStore.getState().finishSync(target.generation);
      } else if (accepted && restore.current?.generation === target.generation) {
        const state = useReaderStore.getState();
        state.setActiveBlockId(target.blockId);
        state.finishSync(target.generation);
      }
    });
  }, []);
  const setPaneHandle = useCallback((handle: TranslationPaneHandle | null) => {
    paneHandle.current = handle;
    if (handle && restore.current) runRestore(handle, restore.current);
  }, [runRestore]);
  useImperativeHandle(ref, () => ({ scrollToBlock(blockId, generation) { return paneHandle.current?.scrollToBlock(blockId, generation) ?? false; } }));

  const switchView = (nextMode: "layout" | "structured") => {
    if (nextMode === viewMode) return;
    const state = useReaderStore.getState();
    if (state.activeBlockId) {
      restore.current = {
        blockId: state.activeBlockId,
        generation: state.beginSync("blocks", state.activeBlockId),
      };
    }
    setViewMode(nextMode);
  };

  const handleActiveBlock = (blockId: string) => {
    const target = restore.current;
    if (target) {
      restore.current = null;
      const state = useReaderStore.getState();
      state.setActiveBlockId(target.blockId);
      state.finishSync(target.generation);
      return;
    }
    props.onActiveBlock?.(blockId);
  };
  const handleUserIntent = () => { restore.current = null; props.onUserIntent?.(); };
  const shared = { blocks: props.blocks, figures: props.figures, onActiveBlock: handleActiveBlock, onUserIntent: handleUserIntent, onVisibleBlocks: props.onVisibleBlocks, onRetranslate: props.onRetranslate };

  return (
    <section className="translation-pane" aria-label="中文版式阅读页">
      <header className="pane-header">
        <strong>{viewMode === "layout" ? "中文版式阅读" : "结构化块视图"}</strong>
        <div className="view-mode-switch" role="group" aria-label="阅读视图">
          <button className={viewMode === "layout" ? "is-selected" : ""} onClick={() => switchView("layout")}>版式对照</button>
          <button className={viewMode === "structured" ? "is-selected" : ""} onClick={() => switchView("structured")}>结构化</button>
        </div>
      </header>
      {viewMode === "layout" ? <LayoutTranslationView {...shared} pageMetrics={props.pageMetrics} ref={setPaneHandle} /> : <StructuredBlockView {...shared} ref={setPaneHandle} />}
    </section>
  );
});
