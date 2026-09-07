import { describe, expect, it } from "vitest";

import { bboxToCss } from "./bbox";

describe("bboxToCss", () => {
  it("maps normalized coordinates to CSS viewport pixels", () => {
    expect(bboxToCss([100, 200, 600, 700], 800, 1000)).toEqual({
      left: 80,
      top: 200,
      width: 400,
      height: 500,
    });
  });

  it("scales with CSS viewport dimensions without applying DPR", () => {
    expect(bboxToCss([100, 200, 600, 700], 400, 500)).toEqual({
      left: 40,
      top: 100,
      width: 200,
      height: 250,
    });
  });
});
