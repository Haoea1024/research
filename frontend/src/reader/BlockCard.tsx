import katex from "katex";
import "katex/dist/katex.min.css";

import type { Block, Figure } from "../api/types";
import { useReaderStore } from "../stores/readerStore";

interface BlockCardProps {
  block: Block;
  figure?: Figure;
}

export function BlockCard({ block, figure }: BlockCardProps) {
  const activeBlockId = useReaderStore((state) => state.activeBlockId);
  const hoverBlockId = useReaderStore((state) => state.hoverBlockId);
  const setHoverBlockId = useReaderStore((state) => state.setHoverBlockId);
  const classes = [
    "block-card",
    `block-${block.type}`,
    activeBlockId === block.id ? "is-active" : "",
    hoverBlockId === block.id ? "is-hovered" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const formulaSource = (block.content_md ?? "")
    .trim()
    .replace(/^\$\$\s*/, "")
    .replace(/\s*\$\$$/, "");
  const displayContent =
    block.type === "table"
      ? figure?.caption_text || "[Table content available in parsed data]"
      : block.content_md || "[No textual content]";

  return (
    <article
      className={classes}
      data-block-id={block.id}
      data-order-idx={block.order_idx}
      onPointerEnter={() => setHoverBlockId(block.id)}
      onPointerLeave={() => {
        if (useReaderStore.getState().hoverBlockId === block.id) {
          setHoverBlockId(null);
        }
      }}
    >
      <div className="block-meta">
        <span>#{block.order_idx}</span>
        <span>Page {block.page + 1}</span>
        <span>{block.type}</span>
      </div>
      {block.type === "figure" || block.type === "table" ? (
        <div className="media-placeholder" data-testid={`${block.type}-placeholder`}>
          <span className="media-icon">{block.type === "table" ? "▦" : "▧"}</span>
          <strong>{block.type === "table" ? "Table" : "Figure"} 占位</strong>
          <small>S2 不加载裁切图片或视觉卡片</small>
        </div>
      ) : null}
      {block.type === "formula" ? (
        <div
          className="formula-content"
          aria-label="Formula"
          dangerouslySetInnerHTML={{
            __html: katex.renderToString(formulaSource, {
              displayMode: true,
              throwOnError: false,
              strict: "ignore",
            }),
          }}
        />
      ) : (
        <div className="block-content">{displayContent}</div>
      )}
      {figure?.diagnostics.length ? (
        <div className="diagnostic-note">{figure.diagnostics.join(", ")}</div>
      ) : null}
    </article>
  );
}
