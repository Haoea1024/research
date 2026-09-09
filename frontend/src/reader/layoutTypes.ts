import type { Block } from "../api/types";

export type PageLayoutMode = "single-column" | "two-column" | "fallback-flow";
export type LayoutColumn = "full" | "left" | "right" | "flow" | "marginalia";

export interface DerivedLayoutBlock {
  block: Block;
  column: LayoutColumn;
  originalXRatio: number | null;
  originalWidthRatio: number | null;
  layoutGroupId: string;
  mediaRowId: string | null;
  verticalOrder: number;
}

export interface FullLayoutSegment {
  kind: "full";
  blocks: DerivedLayoutBlock[];
}

export interface ColumnLayoutSegment {
  kind: "columns";
  left: DerivedLayoutBlock[];
  right: DerivedLayoutBlock[];
}

export interface FlowLayoutSegment {
  kind: "flow";
  blocks: DerivedLayoutBlock[];
}

export type LayoutSegment = FullLayoutSegment | ColumnLayoutSegment | FlowLayoutSegment;

export interface DerivedPageLayout {
  page: number;
  mode: PageLayoutMode;
  confidence: number;
  diagnostics: string[];
  segments: LayoutSegment[];
  marginalia: DerivedLayoutBlock[];
}
