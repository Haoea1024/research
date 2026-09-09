import type { Figure } from "../api/types";
import type { PageMetrics } from "./types";
import { LayoutBlock } from "./LayoutBlock";
import type { DerivedLayoutBlock, DerivedPageLayout } from "./layoutTypes";

interface Props {
  layout: DerivedPageLayout;
  metrics: PageMetrics;
  figuresByBlockId: Map<string, Figure>;
  registerElement: (blockId: string, element: HTMLElement | null) => void;
  onRetranslate?: (blockId: string) => void;
}

function renderItems(items: DerivedLayoutBlock[], props: Omit<Props, "layout" | "metrics">) {
  const result: React.ReactNode[] = [];
  for (let index = 0; index < items.length;) {
    const item = items[index];
    const rowId = item.mediaRowId;
    const row = rowId ? items.slice(index).filter((candidate) => candidate.mediaRowId === rowId) : [];
    if (rowId && row.length > 1) {
      result.push(
        <div className="layout-media-row" data-layout-media-row={rowId} key={rowId}>
          {row.map((entry) => <LayoutBlock key={entry.block.id} item={entry} figure={props.figuresByBlockId.get(entry.block.id)} registerElement={props.registerElement} onRetranslate={props.onRetranslate} />)}
        </div>,
      );
      index += row.length;
    } else {
      result.push(<LayoutBlock key={item.block.id} item={item} figure={props.figuresByBlockId.get(item.block.id)} registerElement={props.registerElement} onRetranslate={props.onRetranslate} />);
      index += 1;
    }
  }
  return result;
}

export function LayoutPage({ layout, metrics, ...props }: Props) {
  return (
    <article className={`layout-page layout-mode-${layout.mode}`} data-layout-page={layout.page + 1} data-layout-mode={layout.mode} style={{ aspectRatio: `${metrics.width} / ${metrics.height}` }}>
      <div className="layout-page-label">{layout.page + 1}</div>
      <div className="layout-page-content">
        {layout.segments.map((segment, index) => segment.kind === "columns" ? (
          <section className="layout-columns" key={`columns-${index}`}>
            <div className="layout-column layout-column-left">{renderItems(segment.left, props)}</div>
            <div className="layout-column layout-column-right">{renderItems(segment.right, props)}</div>
          </section>
        ) : (
          <section className={segment.kind === "full" ? "layout-full" : "layout-flow"} key={`${segment.kind}-${index}`}>{renderItems(segment.blocks, props)}</section>
        ))}
      </div>
      {layout.marginalia.length ? <aside className="layout-marginalia">{renderItems(layout.marginalia, props)}</aside> : null}
      <div className="layout-diagnostics" title={layout.diagnostics.join("\n")}>{layout.mode} · {layout.confidence.toFixed(2)}</div>
    </article>
  );
}
