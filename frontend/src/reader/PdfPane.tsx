import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  GlobalWorkerOptions,
  getDocument,
  type PDFDocumentProxy,
} from "pdfjs-dist";

import type { Block } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { closestBlockAtGuide } from "./activeBlock";
import { PdfPage, type PdfPageHandle } from "./PdfPage";
import { ACTIVE_LINE_RATIO, type PageReadyHandle } from "./types";

GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

interface PdfPaneProps {
  pdfUrl: string;
  blocks: Block[];
  onActiveBlock?: (blockId: string) => void;
  onUserIntent?: () => void;
}

export const PdfPane = forwardRef<PageReadyHandle, PdfPaneProps>(function PdfPane(
  { pdfUrl, blocks, onActiveBlock, onUserIntent },
  ref,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef(new Map<number, PdfPageHandle>());
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollFrameRef = useRef<number | null>(null);

  const blocksByPage = useMemo(() => {
    const grouped = new Map<number, Block[]>();
    for (const block of blocks) {
      const pageNumber = block.page + 1;
      const pageBlocks = grouped.get(pageNumber) ?? [];
      pageBlocks.push(block);
      grouped.set(pageNumber, pageBlocks);
    }
    return grouped;
  }, [blocks]);

  useImperativeHandle(
    ref,
    () => ({
      async ensurePageRendered(pageNumber) {
        const page = pagesRef.current.get(pageNumber);
        if (!page) throw new Error(`PDF page ${pageNumber} is not mounted`);
        await page.ensureRendered();
      },
      async scrollToBlock(block, generation) {
        const page = pagesRef.current.get(block.page + 1);
        const container = scrollRef.current;
        if (!page || !container) return false;
        await page.ensureRendered();
        if (useReaderStore.getState().syncGeneration !== generation) return false;
        const element = page.getBlockElement(block.id);
        if (!element) return false;
        const containerRect = container.getBoundingClientRect();
        const elementRect = element.getBoundingClientRect();
        const targetTop =
          container.scrollTop +
          elementRect.top -
          containerRect.top -
          container.clientHeight * ACTIVE_LINE_RATIO +
          elementRect.height / 2;
        container.scrollTo({ top: Math.max(0, targetTop), behavior: "auto" });
        return true;
      },
    }),
  );

  useEffect(() => {
    let disposed = false;
    const loadingTask = getDocument({ url: pdfUrl });
    setDocument(null);
    setError(null);
    loadingTask.promise
      .then((loaded) => {
        if (!disposed) setDocument(loaded);
      })
      .catch((reason: unknown) => {
        if (!disposed) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      disposed = true;
      pagesRef.current.clear();
      void loadingTask.destroy();
    };
  }, [pdfUrl]);

  const handleScroll = () => {
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const container = scrollRef.current;
      if (!container) return;
      const blockId = closestBlockAtGuide(
        container,
        container.querySelectorAll<HTMLElement>("[data-block-id]"),
      );
      if (blockId) onActiveBlock?.(blockId);
    });
  };

  useEffect(
    () => () => {
      if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current);
    },
    [],
  );

  return (
    <section className="pdf-pane" aria-label="PDF 原文">
      <header className="pane-header">
        <strong>原始 PDF</strong>
        <span>{document ? `${document.numPages} 页` : "载入中"}</span>
      </header>
      <div
        className="pdf-scroll"
        ref={scrollRef}
        data-testid="pdf-scroll"
        tabIndex={0}
        onScroll={handleScroll}
        onWheel={onUserIntent}
        onPointerDown={onUserIntent}
        onTouchStart={onUserIntent}
      >
        {error ? <div className="error-card">PDF 加载失败：{error}</div> : null}
        {document
          ? Array.from({ length: document.numPages }, (_, index) => {
              const pageNumber = index + 1;
              return (
                <PdfPage
                  key={pageNumber}
                  ref={(handle) => {
                    if (handle) pagesRef.current.set(pageNumber, handle);
                    else pagesRef.current.delete(pageNumber);
                  }}
                  document={document}
                  pageNumber={pageNumber}
                  blocks={blocksByPage.get(pageNumber) ?? []}
                  scrollRootRef={scrollRef}
                />
              );
            })
          : null}
      </div>
    </section>
  );
});
