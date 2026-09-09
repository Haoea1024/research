import type { Figure } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { TranslationBlockContent } from "./TranslationBlockContent";
import type { DerivedLayoutBlock } from "./layoutTypes";

interface Props {
  item: DerivedLayoutBlock;
  figure?: Figure;
  registerElement: (blockId: string, element: HTMLElement | null) => void;
  onRetranslate?: (blockId: string) => void;
}

export function LayoutBlock({ item, figure, registerElement, onRetranslate }: Props) {
  const { block } = item;
  const active = useReaderStore((state) => state.activeBlockId === block.id);
  const hovered = useReaderStore((state) => state.hoverBlockId === block.id);
  const setHoverBlockId = useReaderStore((state) => state.setHoverBlockId);
  return (
    <article
      ref={(element) => registerElement(block.id, element)}
      className={`layout-block layout-${block.type} ${active ? "is-active" : ""} ${hovered ? "is-hovered" : ""}`}
      data-block-id={block.id}
      data-order-idx={block.order_idx}
      data-layout-column={item.column}
      onPointerEnter={() => setHoverBlockId(block.id)}
      onPointerLeave={() => { if (useReaderStore.getState().hoverBlockId === block.id) setHoverBlockId(null); }}
    >
      <TranslationBlockContent block={block} figure={figure} layout onRetranslate={onRetranslate} />
    </article>
  );
}
