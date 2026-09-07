import { useEffect, useState } from "react";

import { paperApi } from "./api/client";
import type { Paper } from "./api/types";
import { ReaderPage } from "./reader/ReaderPage";

function queryPaperId() {
  return new URLSearchParams(window.location.search).get("paperId");
}

export function App() {
  const [paperId, setPaperId] = useState(queryPaperId);
  const [papers, setPapers] = useState<Paper[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (paperId) return;
    const controller = new AbortController();
    paperApi
      .list(controller.signal)
      .then(setPapers)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => controller.abort();
  }, [paperId]);

  if (paperId) return <ReaderPage paperId={paperId} />;
  return (
    <main className="library-page">
      <span className="eyebrow">PAPER READING AGENT</span>
      <h1>选择一篇已解析论文</h1>
      {error ? <div className="error-card">{error}</div> : null}
      {!papers && !error ? <p>正在读取论文列表…</p> : null}
      <div className="paper-list">
        {papers?.map((paper) => (
          <button
            className="paper-row"
            key={paper.id}
            type="button"
            onClick={() => {
              const url = new URL(window.location.href);
              url.searchParams.set("paperId", paper.id);
              window.history.replaceState(null, "", url);
              setPaperId(paper.id);
            }}
          >
            <strong>{paper.title ?? "未命名论文"}</strong>
            <span>{paper.status}</span>
          </button>
        ))}
      </div>
    </main>
  );
}
