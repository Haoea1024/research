import type { Block } from "../api/types";

export const ACTIVE_LINE_RATIO = 0.35;
export const PAGE_PRELOAD_MARGIN = "1200px 0px";
export const PAGE_SCALE = 1.35;

export interface PageReadyHandle {
  ensurePageRendered(pageNumber: number): Promise<void>;
  scrollToBlock(block: Block, generation: number): Promise<boolean>;
}
