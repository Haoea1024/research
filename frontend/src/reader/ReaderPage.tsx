import { useCallback, useEffect, useRef, useState } from "react";

import { paperApi } from "../api/client";
import { consumeTranslationStream } from "../api/sse";
import type { Block, Figure, Paper, Translation } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { useTranslationStore } from "../stores/translationStore";
import { PdfPane } from "./PdfPane";
import { TranslationPane } from "./TranslationPane";
import type { PageMetrics } from "./types";
import { useSyncController } from "./SyncController";

interface ReaderPageProps {
  paperId: string;
}

interface ReaderData {
  paper: Paper;
  blocks: Block[];
  figures: Figure[];
  translations: Translation[];
}

export function ReaderPage({ paperId }: ReaderPageProps) {
  const [data, setData] = useState<ReaderData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => useReaderStore.getState().reset(), []);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    Promise.all([
      paperApi.get(paperId, controller.signal),
      paperApi.blocks(paperId, controller.signal),
      paperApi.figures(paperId, controller.signal),
      paperApi.translations(paperId, controller.signal),
    ])
      .then(([paper, blocks, figures, translations]) => {
        setData({
          paper,
          blocks: [...blocks].sort((left, right) => left.order_idx - right.order_idx),
          figures,
          translations,
        });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => controller.abort();
  }, [paperId]);

  if (error) return <main className="state-page error-card">加载论文失败：{error}</main>;
  if (!data) return <main className="state-page">正在加载论文…</main>;
  if (data.paper.status !== "parsed") {
    return (
      <main className="state-page">
        <h1>{data.paper.title ?? "未命名论文"}</h1>
        <p>当前状态：{data.paper.status}</p>
        {data.paper.error ? <pre className="error-card">{data.paper.error}</pre> : null}
      </main>
    );
  }

  return <ReadyReader data={data} paperId={paperId} />;
}

function ReadyReader({ data, paperId }: { data: ReaderData; paperId: string }) {
  const sync = useSyncController(data.blocks);
  const replaceTranslations = useTranslationStore((state) => state.replace);
  const applyEvent = useTranslationStore((state) => state.apply);
  const progress = useTranslationStore((state) => state.progress);
  const streamError = useTranslationStore((state) => state.streamError);
  const streamErrorCode = useTranslationStore((state) => state.streamErrorCode);
  const clearRunError = useTranslationStore((state) => state.clearRunError);
  const translationByBlockId = useTranslationStore((state) => state.byBlockId);
  const [starting, setStarting] = useState(false);
  const [confirmFullTranslation, setConfirmFullTranslation] = useState(false);
  const [pageMetrics, setPageMetrics] = useState(new Map<number, PageMetrics>());
  const streams = useRef(new Map<string, AbortController>());

  useEffect(() => {
    replaceTranslations(data.translations);
    return () => {
      for (const controller of streams.current.values()) controller.abort();
      streams.current.clear();
      useTranslationStore.getState().reset();
    };
  }, [data.translations, replaceTranslations]);

  const watchRun = useCallback((runId: string) => {
    if (streams.current.has(runId)) return;
    const controller = new AbortController();
    streams.current.set(runId, controller);
    void consumeTranslationStream(paperId, runId, applyEvent, controller.signal)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          applyEvent({ id: 0, event: "error", data: { error: reason instanceof Error ? reason.message : String(reason) } });
        }
      })
      .finally(() => streams.current.delete(runId));
  }, [applyEvent, paperId]);

  const startTranslation = async () => {
    clearRunError();
    setStarting(true);
    try {
      const run = await paperApi.translate(paperId);
      watchRun(run.run_id);
    } catch (reason: unknown) {
      applyEvent({
        id: 0,
        event: "error",
        data: { error: reason instanceof Error ? reason.message : String(reason) },
      });
    } finally {
      setStarting(false);
    }
  };

  const retranslate = async (blockId: string) => {
    try {
      const run = await paperApi.retranslate(blockId);
      watchRun(run.run_id);
    } catch (reason: unknown) {
      applyEvent({
        id: 0,
        event: "error",
        data: { block_id: blockId, error: reason instanceof Error ? reason.message : String(reason) },
      });
    }
  };

  const viewport = useCallback((visibleBlockIds: string[]) => {
    if (streams.current.size === 0) return;
    void paperApi.viewport(paperId, visibleBlockIds).catch(() => undefined);
  }, [paperId]);

  const recordPageMetrics = useCallback((page: number, metrics: PageMetrics) => {
    setPageMetrics((current) => {
      const previous = current.get(page);
      if (previous?.width === metrics.width && previous.height === metrics.height) return current;
      const next = new Map(current);
      next.set(page, metrics);
      return next;
    });
  }, []);

  const estimatedTargetCount = data.blocks.filter((block) =>
    block.is_translatable && (translationByBlockId[block.id]?.status ?? "pending") === "pending"
  ).length;

  return (
    <main className="reader-shell">
      <header className="reader-header">
        <div>
          <span className="eyebrow">LAYOUT TRANSLATION READER · S3.5</span>
          <h1>{data.paper.title ?? "未命名论文"}</h1>
        </div>
        <div className="translation-actions">
          {streamError ? (
            <span className="translation-error">
              {streamErrorCode === "GLOSSARY_PREPARATION_FAILED"
                ? "术语表生成失败，可重新启动翻译"
                : streamError}
            </span>
          ) : null}
          {progress ? (
            <span className="status-pill">
              {progress.done}/{progress.total} done · {progress.failed} failed · {progress.skipped ?? 0} skipped
            </span>
          ) : null}
          <button className="translate-button" disabled={starting} onClick={() => setConfirmFullTranslation(true)}>
            {starting ? "正在创建任务…" : `翻译全文 · 预计目标 ${estimatedTargetCount} 个 Block`}
          </button>
        </div>
      </header>
      {confirmFullTranslation ? (
        <div className="translation-confirm-backdrop" role="presentation">
          <section className="translation-confirm" role="dialog" aria-modal="true" aria-labelledby="translation-confirm-title">
            <h2 id="translation-confirm-title">确认翻译全文</h2>
            <p>将提交整篇论文；预计有 {estimatedTargetCount} 个尚未处理的目标 Block。已完成、失败缓存和确定性跳过项不会自动重译。</p>
            <div className="translation-confirm-actions">
              <button type="button" onClick={() => setConfirmFullTranslation(false)}>取消</button>
              <button type="button" className="translate-button" onClick={() => {
                setConfirmFullTranslation(false);
                void startTranslation();
              }}>确认翻译全文</button>
            </div>
          </section>
        </div>
      ) : null}
      <div className="reader-grid">
        <PdfPane
          ref={sync.pdfPaneRef}
          pdfUrl={paperApi.pdfUrl(paperId)}
          blocks={data.blocks}
          onActiveBlock={sync.onPdfActiveBlock}
          onUserIntent={sync.onPdfUserIntent}
          onPageMetrics={recordPageMetrics}
        />
        <TranslationPane
          ref={sync.translationPaneRef}
          blocks={data.blocks}
          figures={data.figures}
          pageMetrics={pageMetrics}
          onActiveBlock={sync.onTranslationActiveBlock}
          onUserIntent={sync.onTranslationUserIntent}
          onVisibleBlocks={viewport}
          onRetranslate={(blockId) => void retranslate(blockId)}
        />
      </div>
    </main>
  );
}
