import type { Block, Figure } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { TranslationBlockContent } from "./TranslationBlockContent";

interface BlockCardProps { block: Block; figure?: Figure; onRetranslate?: (blockId: string) => void; }

export function BlockCard({ block, figure, onRetranslate }: BlockCardProps) {
  const activeBlockId = useReaderStore((state) => state.activeBlockId);
  const hoverBlockId = useReaderStore((state) => state.hoverBlockId);
  const setHoverBlockId = useReaderStore((state) => state.setHoverBlockId);
  const classes = ["block-card", `block-${block.type}`, activeBlockId === block.id ? "is-active" : "", hoverBlockId === block.id ? "is-hovered" : ""].filter(Boolean).join(" ");
  return (
    <article className={classes} data-block-id={block.id} data-order-idx={block.order_idx}
      onPointerEnter={() => setHoverBlockId(block.id)}
      onPointerLeave={() => { if (useReaderStore.getState().hoverBlockId === block.id) setHoverBlockId(null); }}>
      <div className="block-meta"><span>#{block.order_idx}</span><span>Page {block.page + 1}</span><span>{block.type}</span></div>
      <TranslationBlockContent block={block} figure={figure} showSourceDetails onRetranslate={onRetranslate} />
      {figure?.diagnostics.length ? <div className="diagnostic-note">{figure.diagnostics.join(", ")}</div> : null}
    </article>
  );
}
