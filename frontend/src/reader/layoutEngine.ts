import type { Block } from "../api/types";
import {
  LAYOUT_COLUMN_GUTTER_X,
  LAYOUT_FULL_WIDTH_RATIO,
  LAYOUT_HEADER_GAP,
  LAYOUT_MAX_INVALID_BBOX_RATIO,
  LAYOUT_MARGINALIA_EDGE_RATIO,
  LAYOUT_MARGINALIA_MAX_BODY_OVERLAP,
  LAYOUT_MARGINALIA_MIN_ASPECT,
  LAYOUT_MARGINALIA_MIN_HEIGHT,
  LAYOUT_MEDIA_COLUMN_MAX_WIDTH_RATIO,
  LAYOUT_MEDIA_GUTTER_CLEARANCE,
  LAYOUT_MEDIA_ROW_OVERLAP,
  LAYOUT_MIN_BODY_CHARS,
  LAYOUT_MIN_CENTROID_SEPARATION,
  LAYOUT_MIN_COLUMN_BLOCKS,
  LAYOUT_MIN_CONFIDENCE,
} from "./layoutConstants";
import type {
  DerivedLayoutBlock,
  DerivedPageLayout,
  LayoutColumn,
  LayoutSegment,
} from "./layoutTypes";

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  width: number;
  height: number;
  centerX: number;
  centerY: number;
}

function validBox(block: Block): Box | null {
  const [x0, y0, x1, y1] = block.bbox;
  if (![x0, y0, x1, y1].every(Number.isFinite)) return null;
  if (x0 < 0 || y0 < 0 || x1 > 1000 || y1 > 1000 || x1 <= x0 || y1 <= y0) return null;
  return {
    x0,
    y0,
    x1,
    y1,
    width: x1 - x0,
    height: y1 - y0,
    centerX: (x0 + x1) / 2,
    centerY: (y0 + y1) / 2,
  };
}

function isMedia(block: Block) {
  return block.type === "figure" || block.type === "table";
}

function normalizedTextLength(block: Block) {
  return (block.content_md ?? "").replace(/\s+/g, " ").trim().length;
}

function horizontalOverlapRatio(box: Box, candidates: Array<{ box: Box }>) {
  return Math.max(0, ...candidates.map(({ box: candidate }) => {
    const overlap = Math.max(0, Math.min(box.x1, candidate.x1) - Math.max(box.x0, candidate.x0));
    return overlap / Math.max(1, Math.min(box.width, candidate.width));
  }));
}

function isMarginalia(
  block: Block,
  box: Box,
  contentX0: number,
  contentX1: number,
  contentWidth: number,
  bodyCandidates: Array<{ box: Box }>,
) {
  if (block.type === "title" || isMedia(block)) return false;
  const edgeInset = contentWidth * LAYOUT_MARGINALIA_EDGE_RATIO;
  const nearEdge = box.x1 <= contentX0 + edgeInset || box.x0 >= contentX1 - edgeInset;
  const tallAndNarrow =
    box.height >= LAYOUT_MARGINALIA_MIN_HEIGHT &&
    box.height / Math.max(1, box.width) >= LAYOUT_MARGINALIA_MIN_ASPECT;
  return nearEdge && tallAndNarrow &&
    horizontalOverlapRatio(box, bodyCandidates) <= LAYOUT_MARGINALIA_MAX_BODY_OVERLAP;
}

function layoutBlock(
  block: Block,
  column: LayoutColumn,
  group: string,
  contentX0: number,
  contentWidth: number,
): DerivedLayoutBlock {
  const box = validBox(block);
  return {
    block,
    column,
    originalXRatio: box ? (box.x0 - contentX0) / contentWidth : null,
    originalWidthRatio: box ? box.width / contentWidth : null,
    layoutGroupId: group,
    mediaRowId: null,
    verticalOrder: block.order_idx,
  };
}

function addMediaRows(blocks: DerivedLayoutBlock[], page: number, column: string) {
  for (let index = 0; index < blocks.length - 1; index += 1) {
    const current = blocks[index];
    const next = blocks[index + 1];
    if (!isMedia(current.block) || !isMedia(next.block)) continue;
    const a = validBox(current.block);
    const b = validBox(next.block);
    if (!a || !b) continue;
    const overlap = Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
    const ratio = overlap / Math.max(1, Math.min(a.height, b.height));
    if (ratio >= LAYOUT_MEDIA_ROW_OVERLAP) {
      const id = `page-${page}-${column}-media-${Math.min(current.block.order_idx, next.block.order_idx)}`;
      current.mediaRowId = id;
      next.mediaRowId = id;
    }
  }
}

export function derivePageLayout(page: number, input: Block[]): DerivedPageLayout {
  const blocks = [...input].sort((a, b) => a.order_idx - b.order_idx);
  const diagnostics: string[] = [];
  if (blocks.length === 0) {
    return { page, mode: "single-column", confidence: 1, diagnostics, segments: [], marginalia: [] };
  }

  const boxed = blocks.flatMap((block) => {
    const box = validBox(block);
    return box ? [{ block, box }] : [];
  });
  const invalidRatio = 1 - boxed.length / blocks.length;
  if (invalidRatio > 0) diagnostics.push(`INVALID_BBOX:${blocks.length - boxed.length}`);
  if (boxed.length === 0 || invalidRatio > LAYOUT_MAX_INVALID_BBOX_RATIO) {
    diagnostics.push("FALLBACK_UNRELIABLE_BBOX");
    return {
      page,
      mode: "fallback-flow",
      confidence: Math.max(0, 1 - invalidRatio),
      diagnostics,
      segments: [{ kind: "flow", blocks: blocks.map((block) => layoutBlock(block, "flow", `page-${page}-flow`, 0, 1000)) }],
      marginalia: [],
    };
  }

  const contentX0 = Math.min(...boxed.map(({ box }) => box.x0));
  const contentX1 = Math.max(...boxed.map(({ box }) => box.x1));
  const contentWidth = Math.max(1, contentX1 - contentX0);
  const bodyCandidates = boxed.filter(
    ({ block, box }) =>
      !isMedia(block) &&
      block.type !== "formula" &&
      normalizedTextLength(block) >= LAYOUT_MIN_BODY_CHARS &&
      box.width / contentWidth < LAYOUT_FULL_WIDTH_RATIO,
  );
  const mediaCandidates = boxed.filter(({ block, box }) => {
    if (!isMedia(block) || box.width / contentWidth > LAYOUT_MEDIA_COLUMN_MAX_WIDTH_RATIO) return false;
    const gutter = LAYOUT_COLUMN_GUTTER_X * 1000;
    const clearance = LAYOUT_MEDIA_GUTTER_CLEARANCE * 1000;
    return box.x1 <= gutter - clearance || box.x0 >= gutter + clearance;
  });
  const leftBodyCandidates = bodyCandidates.filter(({ box }) => box.centerX < 500);
  const rightBodyCandidates = bodyCandidates.filter(({ box }) => box.centerX >= 500);
  const leftMediaCandidates = mediaCandidates.filter(({ box }) => box.centerX < 500);
  const rightMediaCandidates = mediaCandidates.filter(({ box }) => box.centerX >= 500);
  diagnostics.push(
    `COLUMN_EVIDENCE:body=${leftBodyCandidates.length}/${rightBodyCandidates.length},media=${leftMediaCandidates.length}/${rightMediaCandidates.length}`,
  );
  const leftCandidates = [...leftBodyCandidates, ...leftMediaCandidates];
  const rightCandidates = [...rightBodyCandidates, ...rightMediaCandidates];
  const leftCentroid = leftCandidates.length
    ? leftCandidates.reduce((sum, item) => sum + item.box.centerX, 0) / leftCandidates.length
    : 0;
  const rightCentroid = rightCandidates.length
    ? rightCandidates.reduce((sum, item) => sum + item.box.centerX, 0) / rightCandidates.length
    : 0;
  const separation = (rightCentroid - leftCentroid) / 1000;
  const effectiveLeftCount = Math.max(
    leftBodyCandidates.length,
    leftMediaCandidates.length > 0 && rightBodyCandidates.length >= LAYOUT_MIN_COLUMN_BLOCKS
      ? LAYOUT_MIN_COLUMN_BLOCKS
      : 0,
  );
  const effectiveRightCount = Math.max(
    rightBodyCandidates.length,
    rightMediaCandidates.length > 0 && leftBodyCandidates.length >= LAYOUT_MIN_COLUMN_BLOCKS
      ? LAYOUT_MIN_COLUMN_BLOCKS
      : 0,
  );
  const countScore = Math.min(1, Math.min(effectiveLeftCount, effectiveRightCount) / LAYOUT_MIN_COLUMN_BLOCKS);
  const separationScore = Math.min(1, Math.max(0, separation) / 0.36);
  const gutterEvidence = boxed.some(
    ({ box }) => box.x1 / 1000 < LAYOUT_COLUMN_GUTTER_X - 0.01,
  ) && boxed.some(({ box }) => box.x0 / 1000 > LAYOUT_COLUMN_GUTTER_X + 0.01);
  const confidence = Number(
    (countScore * 0.5 + separationScore * 0.35 + (gutterEvidence ? 0.15 : 0)).toFixed(3),
  );
  const hasBothColumns =
    effectiveLeftCount >= LAYOUT_MIN_COLUMN_BLOCKS &&
    effectiveRightCount >= LAYOUT_MIN_COLUMN_BLOCKS &&
    separation >= LAYOUT_MIN_CENTROID_SEPARATION;

  if (!hasBothColumns) {
    diagnostics.push("SINGLE_COLUMN_NO_STABLE_SPLIT");
    return {
      page,
      mode: "single-column",
      confidence: Number(Math.max(0.5, 1 - confidence).toFixed(3)),
      diagnostics,
      segments: [{ kind: "flow", blocks: blocks.map((block) => layoutBlock(block, "flow", `page-${page}-flow`, contentX0, contentWidth)) }],
      marginalia: [],
    };
  }
  if (confidence < LAYOUT_MIN_CONFIDENCE) {
    diagnostics.push(`FALLBACK_LOW_COLUMN_CONFIDENCE:${confidence}`);
    return {
      page,
      mode: "fallback-flow",
      confidence,
      diagnostics,
      segments: [{ kind: "flow", blocks: blocks.map((block) => layoutBlock(block, "flow", `page-${page}-flow`, contentX0, contentWidth)) }],
      marginalia: [],
    };
  }

  diagnostics.push(`TWO_COLUMN_CONFIDENCE:${confidence}`);
  const firstBodyY = Math.min(...bodyCandidates.map(({ box }) => box.y0));
  const headerCutoff = firstBodyY - LAYOUT_HEADER_GAP * 1000;
  const headers: Block[] = [];
  const full: Block[] = [];
  const left: Block[] = [];
  const right: Block[] = [];
  const marginalia: Block[] = [];
  for (const block of blocks) {
    const box = validBox(block);
    if (!box) {
      full.push(block);
    } else if (isMarginalia(block, box, contentX0, contentX1, contentWidth, bodyCandidates)) {
      marginalia.push(block);
      diagnostics.push(`MARGINALIA:${block.id}:EDGE_TALL_LOW_OVERLAP`);
    } else if (
      box.y1 < headerCutoff &&
      !isMedia(block) &&
      normalizedTextLength(block) < LAYOUT_MIN_BODY_CHARS
    ) {
      headers.push(block);
    } else if (box.width / contentWidth >= LAYOUT_FULL_WIDTH_RATIO) {
      full.push(block);
    } else if (box.centerX < 500) {
      left.push(block);
    } else {
      right.push(block);
    }
  }

  const segments: LayoutSegment[] = [];
  if (headers.length) {
    segments.push({
      kind: "full",
      blocks: headers.map((block) => layoutBlock(block, "full", `page-${page}-header`, contentX0, contentWidth)),
    });
  }
  const fullOrdered = [...full].sort((a, b) => (validBox(a)?.centerY ?? 1001) - (validBox(b)?.centerY ?? 1001) || a.order_idx - b.order_idx);
  const bandFor = (block: Block) => {
    const y = validBox(block)?.centerY ?? 1001;
    return fullOrdered.filter((fullBlock) => (validBox(fullBlock)?.centerY ?? 1001) < y).length;
  };
  for (let band = 0; band <= fullOrdered.length; band += 1) {
    const leftDerived = left.filter((block) => bandFor(block) === band).map((block) => layoutBlock(block, "left", `page-${page}-columns-${band}`, contentX0, contentWidth));
    const rightDerived = right.filter((block) => bandFor(block) === band).map((block) => layoutBlock(block, "right", `page-${page}-columns-${band}`, contentX0, contentWidth));
    addMediaRows(leftDerived, page, `left-${band}`);
    addMediaRows(rightDerived, page, `right-${band}`);
    if (leftDerived.length || rightDerived.length) segments.push({ kind: "columns", left: leftDerived, right: rightDerived });
    const fullBlock = fullOrdered[band];
    if (fullBlock) {
      segments.push({ kind: "full", blocks: [layoutBlock(fullBlock, "full", `page-${page}-full-${band}`, contentX0, contentWidth)] });
    }
  }
  return {
    page,
    mode: "two-column",
    confidence,
    diagnostics,
    segments,
    marginalia: marginalia.map((block) => layoutBlock(block, "marginalia", `page-${page}-marginalia`, contentX0, contentWidth)),
  };
}

export function deriveDocumentLayout(blocks: Block[]): DerivedPageLayout[] {
  const byPage = new Map<number, Block[]>();
  for (const block of blocks) {
    const pageBlocks = byPage.get(block.page) ?? [];
    pageBlocks.push(block);
    byPage.set(block.page, pageBlocks);
  }
  const lastPage = Math.max(-1, ...blocks.map((block) => block.page));
  return Array.from({ length: lastPage + 1 }, (_, page) => derivePageLayout(page, byPage.get(page) ?? []));
}
