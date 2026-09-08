import katex from "katex";
import "katex/dist/katex.min.css";

import type { Block, Figure } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { useTranslationStore } from "../stores/translationStore";

interface BlockCardProps {
  block: Block;
  figure?: Figure;
  onRetranslate?: (blockId: string) => void;
}

export function BlockCard({ block, figure, onRetranslate }: BlockCardProps) {
  const activeBlockId = useReaderStore((state) => state.activeBlockId);
  const hoverBlockId = useReaderStore((state) => state.hoverBlockId);
  const setHoverBlockId = useReaderStore((state) => state.setHoverBlockId);
  const translation = useTranslationStore((state) => state.byBlockId[block.id]);
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
  // A retranslation keeps the last successful text visible while its new work
  // item is queued/translating; only first-time failures fall back to English.
  const showTranslation = block.is_translatable && Boolean(translation?.zh_text);
  const stateLabel = block.is_translatable ? (translation?.status ?? "pending") : null;

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
        {stateLabel ? <span className={`translation-state state-${stateLabel}`}>{stateLabel}</span> : null}
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
        <>
          <div className={`block-content ${showTranslation ? "translated-content" : "english-fallback"}`}>
            {showTranslation ? translation.zh_text : displayContent}
          </div>
          {showTranslation ? <details className="source-fallback"><summary>查看英文原文</summary>{displayContent}</details> : null}
          {translation?.error ? <div className="translation-error">{translation.error}</div> : null}
          {translation?.status === "skipped" ? (
            <div className="translation-skip">已跳过：{translation.skip_reason}</div>
          ) : null}
          {block.is_translatable && (translation?.status === "failed" || translation?.retranslate_failed) ? (
            <button className="retry-button" onClick={() => onRetranslate?.(block.id)}>重试翻译</button>
          ) : null}
        </>
      )}
      {figure?.diagnostics.length ? (
        <div className="diagnostic-note">{figure.diagnostics.join(", ")}</div>
      ) : null}
    </article>
  );
}
