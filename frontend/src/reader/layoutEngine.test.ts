import { describe, expect, it } from "vitest";
import { makeBlock } from "../test/fixtures";
import { derivePageLayout } from "./layoutEngine";

const long = "A deterministic paragraph with enough content to qualify as body text. ".repeat(3);
function twoColumnBlocks() {
  return [
    makeBlock({ id: "title", type: "title", order_idx: 0, bbox: [120, 40, 880, 100], content_md: "Paper title" }),
    ...[0, 1, 2].map((index) => makeBlock({ id: `left-${index}`, order_idx: index + 1, bbox: [80, 180 + index * 130, 465, 280 + index * 130], content_md: long })),
    ...[0, 1, 2].map((index) => makeBlock({ id: `right-${index}`, order_idx: index + 4, bbox: [535, 180 + index * 130, 920, 280 + index * 130], content_md: long })),
  ];
}

describe("derivePageLayout", () => {
  it("derives a confident two-column page and preserves a full-width title", () => {
    const layout = derivePageLayout(0, twoColumnBlocks());
    expect(layout.mode).toBe("two-column");
    expect(layout.confidence).toBeGreaterThanOrEqual(0.72);
    expect(layout.segments[0].kind).toBe("full");
    const columns = layout.segments.find((segment) => segment.kind === "columns");
    expect(columns?.kind === "columns" ? columns.left.map((item) => item.block.id) : []).toEqual(["left-0", "left-1", "left-2"]);
    expect(columns?.kind === "columns" ? columns.right.map((item) => item.block.id) : []).toEqual(["right-0", "right-1", "right-2"]);
  });
  it("uses a normal document flow for a stable single-column page", () => {
    const blocks = [0, 1, 2].map((index) => makeBlock({ id: `single-${index}`, order_idx: index, bbox: [120, 100 + index * 180, 880, 240 + index * 180], content_md: long }));
    expect(derivePageLayout(0, blocks).mode).toBe("single-column");
  });
  it("falls back deterministically when bbox data is unreliable", () => {
    const blocks = twoColumnBlocks().map((block, index) => index < 2 ? { ...block, bbox: [900, 100, 100, 50] as [number, number, number, number] } : block);
    const first = derivePageLayout(0, blocks);
    expect(first.mode).toBe("fallback-flow");
    expect(first.diagnostics).toContain("FALLBACK_UNRELIABLE_BBOX");
    expect(derivePageLayout(0, blocks)).toEqual(first);
  });
  it("groups adjacent media visually without changing either block identity", () => {
    const blocks = twoColumnBlocks();
    blocks.push(makeBlock({ id: "figure-a", type: "figure", order_idx: 7, bbox: [540, 610, 710, 740], content_md: "" }));
    blocks.push(makeBlock({ id: "figure-b", type: "figure", order_idx: 8, bbox: [730, 610, 920, 740], content_md: "" }));
    const layout = derivePageLayout(0, blocks);
    const columns = layout.segments.find((segment) => segment.kind === "columns");
    const media = columns?.kind === "columns" ? columns.right.filter((item) => item.block.type === "figure") : [];
    expect(media.map((item) => item.block.id)).toEqual(["figure-a", "figure-b"]);
    expect(media[0].mediaRowId).toBeTruthy();
    expect(media[0].mediaRowId).toBe(media[1].mediaRowId);
  });
  it("keeps a full-width media block between the column bands around it", () => {
    const blocks = twoColumnBlocks().map((block) => block.id.startsWith("left-2") || block.id.startsWith("right-2") ? { ...block, bbox: [block.bbox[0], 700, block.bbox[2], 790] as [number, number, number, number] } : block);
    blocks.push(makeBlock({ id: "wide-figure", type: "figure", order_idx: 7, bbox: [90, 520, 910, 650], content_md: "" }));
    const layout = derivePageLayout(0, blocks);
    expect(layout.segments.map((segment) => segment.kind)).toEqual(["full", "columns", "full", "columns"]);
    const wide = layout.segments[2];
    expect(wide.kind === "full" ? wide.blocks[0].block.id : null).toBe("wide-figure");
  });
  it("keeps a narrow title in the left column while isolating true edge marginalia", () => {
    const blocks = twoColumnBlocks();
    blocks.push(makeBlock({ id: "abstract", type: "title", order_idx: 8, bbox: [233, 281, 313, 297], content_md: "Abstract" }));
    blocks.push(makeBlock({ id: "arxiv", type: "text", order_idx: 9, bbox: [22, 261, 57, 705], content_md: "arXiv:1512.03385v1 [cs.CV] 10 Dec 2015" }));
    const layout = derivePageLayout(0, blocks);
    const columnIds = layout.segments.flatMap((segment) => segment.kind === "columns"
      ? [...segment.left, ...segment.right].map((item) => item.block.id)
      : []);
    expect(layout.mode).toBe("two-column");
    expect(columnIds).toContain("abstract");
    expect(layout.marginalia.map((item) => item.block.id)).toEqual(["arxiv"]);
  });
  it("uses a tall single-column figure as evidence for a mixed-column page", () => {
    const blocks = [
      makeBlock({ id: "figure-3", type: "figure", order_idx: 0, bbox: [80, 99, 468, 780], content_md: "" }),
      ...[0, 1, 2, 3].map((index) => makeBlock({
        id: `right-body-${index}`,
        order_idx: index + 1,
        bbox: [498, 105 + index * 150, 905, 225 + index * 150],
        content_md: long,
      })),
    ];
    const layout = derivePageLayout(3, blocks);
    const columns = layout.segments.find((segment) => segment.kind === "columns");
    expect(layout.mode).toBe("two-column");
    expect(columns?.kind === "columns" ? columns.left.map((item) => item.block.id) : []).toEqual(["figure-3"]);
    expect(columns?.kind === "columns" ? columns.right.map((item) => item.block.id) : []).toEqual([
      "right-body-0", "right-body-1", "right-body-2", "right-body-3",
    ]);
  });
});
