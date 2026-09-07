import { useEffect, useState } from "react";

import { paperApi } from "../api/client";
import type { Block, Figure, Paper } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { BlockPane } from "./BlockPane";
import { PdfPane } from "./PdfPane";
import { useSyncController } from "./SyncController";

interface ReaderPageProps {
  paperId: string;
}

interface ReaderData {
  paper: Paper;
  blocks: Block[];
  figures: Figure[];
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
    ])
      .then(([paper, blocks, figures]) => {
        setData({
          paper,
          blocks: [...blocks].sort((left, right) => left.order_idx - right.order_idx),
          figures,
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

  return (
    <main className="reader-shell">
      <header className="reader-header">
        <div>
          <span className="eyebrow">SIDE-BY-SIDE READER · S2</span>
          <h1>{data.paper.title ?? "未命名论文"}</h1>
        </div>
        <span className="status-pill">{data.blocks.length} blocks</span>
      </header>
      <div className="reader-grid">
        <PdfPane
          ref={sync.pdfPaneRef}
          pdfUrl={paperApi.pdfUrl(paperId)}
          blocks={data.blocks}
          onActiveBlock={sync.onPdfActiveBlock}
          onUserIntent={sync.onPdfUserIntent}
        />
        <BlockPane
          ref={sync.blockPaneRef}
          blocks={data.blocks}
          figures={data.figures}
          onActiveBlock={sync.onBlocksActiveBlock}
          onUserIntent={sync.onBlocksUserIntent}
        />
      </div>
    </main>
  );
}
