export type PaperStatus = "uploaded" | "parsing" | "parsed" | "parse_failed";

export interface Paper {
  id: string;
  title: string | null;
  authors: string | null;
  year: number | null;
  status: PaperStatus;
  parser: string | null;
  parser_version: string | null;
  error: string | null;
  created_at: string | null;
}

export type BlockType =
  | "text"
  | "title"
  | "formula"
  | "figure"
  | "table"
  | "caption";

export interface Block {
  id: string;
  paper_id: string;
  order_idx: number;
  page: number;
  bbox: [number, number, number, number];
  type: BlockType;
  content_md: string | null;
  confidence: number | null;
  is_translatable: boolean;
}

export interface Figure {
  id: string;
  paper_id: string | null;
  block_id: string | null;
  caption_block_id: string | null;
  image_path: string;
  table_html: string | null;
  caption_text: string | null;
  diagnostics: string[];
  status: string | null;
  error: string | null;
}

export type TranslationStatus =
  | "pending"
  | "queued"
  | "translating"
  | "done"
  | "failed"
  | "skipped";

export interface Translation {
  block_id: string;
  status: TranslationStatus;
  zh_text: string | null;
  error: string | null;
  model: string | null;
  glossary_version: number | null;
  updated_at: string | null;
  cached: boolean;
  retranslate_failed?: boolean;
  skip_reason?: string | null;
}

export interface TranslateRun {
  run_id: string;
  paper_id: string;
  total: number;
  states: Record<string, TranslationStatus>;
}

export interface TranslationProgress {
  run_id: string;
  status?: "preparing_glossary" | "running" | "success" | "failed";
  total: number;
  pending: number;
  queued: number;
  translating: number;
  done: number;
  failed: number;
  skipped: number;
}
