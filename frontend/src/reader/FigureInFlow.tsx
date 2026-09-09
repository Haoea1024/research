import type { Figure } from "../api/types";
import { ParserCrop } from "./ParserCrop";

export function FigureInFlow({ figure }: { figure?: Figure }) {
  const inlineCaption = figure?.caption_block_id ? null : figure?.caption_text;
  return (
    <figure className="layout-media" data-testid="figure-in-flow">
      <ParserCrop imageUrl={figure?.image_url} alt={figure?.caption_text ?? "Paper figure"} kind="Figure" />
      {inlineCaption ? <figcaption>{inlineCaption}</figcaption> : null}
    </figure>
  );
}
