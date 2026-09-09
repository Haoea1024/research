import type { Figure } from "../api/types";
import { ParserCrop } from "./ParserCrop";

export function TableInFlow({ table }: { table?: Figure }) {
  const inlineCaption = table?.caption_block_id ? null : table?.caption_text;
  return (
    <figure className="layout-media layout-table" data-testid="table-in-flow">
      <ParserCrop imageUrl={table?.image_url} alt={table?.caption_text ?? "Paper table"} kind="Table" />
      {inlineCaption ? <figcaption>{inlineCaption}</figcaption> : null}
    </figure>
  );
}
