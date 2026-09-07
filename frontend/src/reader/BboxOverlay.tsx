import type { Block } from "../api/types";
import { useReaderStore } from "../stores/readerStore";
import { bboxToCss } from "./bbox";

interface BboxOverlayProps {
  blocks: Block[];
  width: number;
  height: number;
}

export function BboxOverlay({ blocks, width, height }: BboxOverlayProps) {
  const activeBlockId = useReaderStore((state) => state.activeBlockId);
  const hoverBlockId = useReaderStore((state) => state.hoverBlockId);
  const setHoverBlockId = useReaderStore((state) => state.setHoverBlockId);

  return (
    <div className="bbox-layer" style={{ width, height }} aria-label="PDF block overlays">
      {blocks.map((block) => {
        const box = bboxToCss(block.bbox, width, height);
        const classNames = [
          "bbox-box",
          activeBlockId === block.id ? "is-active" : "",
          hoverBlockId === block.id ? "is-hovered" : "",
          block.confidence !== null && block.confidence < 0.5 ? "is-low-confidence" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <div
            key={block.id}
            className={classNames}
            data-block-id={block.id}
            data-order-idx={block.order_idx}
            aria-label={`Block ${block.order_idx}`}
            style={box}
            onPointerEnter={() => setHoverBlockId(block.id)}
            onPointerLeave={() => {
              if (useReaderStore.getState().hoverBlockId === block.id) {
                setHoverBlockId(null);
              }
            }}
          />
        );
      })}
    </div>
  );
}
