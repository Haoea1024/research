import type { Block, Figure } from "../api/types";

export function makeBlock(overrides: Partial<Block> = {}): Block {
  return {
    id: "paper:0",
    paper_id: "paper",
    order_idx: 0,
    page: 0,
    bbox: [100, 200, 500, 300],
    type: "text",
    content_md: "Example block",
    confidence: null,
    is_translatable: true,
    ...overrides,
  };
}

export function makeFigure(overrides: Partial<Figure> = {}): Figure {
  return {
    id: "figure:0",
    paper_id: "paper",
    block_id: "paper:0",
    caption_block_id: null,
    image_path: "C:/private/figure.jpg",
    table_html: null,
    caption_text: null,
    diagnostics: [],
    status: "pending",
    error: null,
    ...overrides,
  };
}
