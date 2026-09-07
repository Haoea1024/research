import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from "pdfjs-dist";

import type { Block } from "../api/types";
import { BboxOverlay } from "./BboxOverlay";
import { PAGE_PRELOAD_MARGIN, PAGE_SCALE } from "./types";

export interface PdfPageHandle {
  ensureRendered(): Promise<void>;
  getBlockElement(blockId: string): HTMLElement | null;
}

interface PdfPageProps {
  document: PDFDocumentProxy;
  pageNumber: number;
  blocks: Block[];
  scrollRootRef: RefObject<HTMLDivElement>;
}

export const PdfPage = forwardRef<PdfPageHandle, PdfPageProps>(function PdfPage(
  { document, pageNumber, blocks, scrollRootRef },
  ref,
) {
  const shellRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pagePromiseRef = useRef<Promise<PDFPageProxy> | null>(null);
  const readyPromiseRef = useRef<Promise<void> | null>(null);
  const overlayCommitPromiseRef = useRef<Promise<void> | null>(null);
  const resolveOverlayCommitRef = useRef<(() => void) | null>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);
  const mountedRef = useRef(true);
  const [viewportSize, setViewportSize] = useState({ width: 612, height: 792 });
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ensureRendered = () => {
    if (readyPromiseRef.current) return readyPromiseRef.current;
    readyPromiseRef.current = (async () => {
      const pagePromise =
        pagePromiseRef.current ?? (pagePromiseRef.current = document.getPage(pageNumber));
      const page = await pagePromise;
      const viewport = page.getViewport({ scale: PAGE_SCALE });
      if (!mountedRef.current) return;
      setViewportSize({ width: viewport.width, height: viewport.height });
      const canvas = canvasRef.current;
      if (!canvas) throw new Error(`Canvas for PDF page ${pageNumber} is unavailable`);
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Canvas 2D context is unavailable");
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      renderTaskRef.current = page.render({
        canvas,
        canvasContext: context,
        viewport,
        transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
      });
      await renderTaskRef.current.promise;
      renderTaskRef.current = null;
      if (mountedRef.current) {
        overlayCommitPromiseRef.current = new Promise<void>((resolve) => {
          resolveOverlayCommitRef.current = resolve;
        });
        setReady(true);
        await overlayCommitPromiseRef.current;
      }
    })().catch((reason: unknown) => {
      if (mountedRef.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
      throw reason;
    });
    return readyPromiseRef.current;
  };

  useImperativeHandle(
    ref,
    () => ({
      ensureRendered,
      getBlockElement(blockId) {
        return (
          Array.from(shellRef.current?.querySelectorAll<HTMLElement>("[data-block-id]") ?? []).find(
            (element) => element.dataset.blockId === blockId,
          ) ?? null
        );
      },
    }),
  );

  useLayoutEffect(() => {
    if (ready) {
      resolveOverlayCommitRef.current?.();
      resolveOverlayCommitRef.current = null;
    }
  }, [ready]);

  useEffect(() => {
    mountedRef.current = true;
    const pagePromise =
      pagePromiseRef.current ?? (pagePromiseRef.current = document.getPage(pageNumber));
    void pagePromise
      .then((page) => {
        if (!mountedRef.current) return;
        const viewport = page.getViewport({ scale: PAGE_SCALE });
        setViewportSize({ width: viewport.width, height: viewport.height });
      })
      .catch((reason: unknown) => {
        if (mountedRef.current) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    const shell = shellRef.current;
    const root = scrollRootRef.current;
    if (!shell || !root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void ensureRendered().catch(() => undefined);
          observer.disconnect();
        }
      },
      { root, rootMargin: PAGE_PRELOAD_MARGIN },
    );
    observer.observe(shell);
    return () => {
      mountedRef.current = false;
      observer.disconnect();
      renderTaskRef.current?.cancel();
      renderTaskRef.current = null;
      resolveOverlayCommitRef.current?.();
      resolveOverlayCommitRef.current = null;
      overlayCommitPromiseRef.current = null;
      readyPromiseRef.current = null;
      pagePromiseRef.current = null;
    };
  }, [document, pageNumber, scrollRootRef]);

  return (
    <article
      ref={shellRef}
      className="pdf-page-shell"
      data-page-number={pageNumber}
      style={{ width: viewportSize.width, height: viewportSize.height }}
    >
      <canvas ref={canvasRef} aria-label={`PDF 第 ${pageNumber} 页`} />
      {ready ? (
        <BboxOverlay blocks={blocks} width={viewportSize.width} height={viewportSize.height} />
      ) : (
        <div className="page-loading">第 {pageNumber} 页{error ? `加载失败：${error}` : "准备中"}</div>
      )}
    </article>
  );
});
