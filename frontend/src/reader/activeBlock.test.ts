import { describe, expect, it } from "vitest";

import { closestBlockAtGuide } from "./activeBlock";

function rect(top: number, height: number): DOMRect {
  return { top, bottom: top + height, height, left: 0, right: 100, width: 100 } as DOMRect;
}

describe("closestBlockAtGuide", () => {
  it("selects the visible block nearest the shared 35% guide", () => {
    const container = document.createElement("div");
    Object.defineProperty(container, "clientHeight", { value: 1000 });
    container.getBoundingClientRect = () => rect(100, 1000);
    const first = document.createElement("div");
    first.dataset.blockId = "first";
    first.getBoundingClientRect = () => rect(200, 100);
    const second = document.createElement("div");
    second.dataset.blockId = "second";
    second.getBoundingClientRect = () => rect(400, 100);
    expect(closestBlockAtGuide(container, [first, second])).toBe("second");
  });
});
