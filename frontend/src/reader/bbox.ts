import type { Block } from "../api/types";

export interface CssBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function bboxToCss(
  bbox: Block["bbox"],
  viewportWidth: number,
  viewportHeight: number,
): CssBox {
  const [x0, y0, x1, y1] = bbox;
  return {
    left: (x0 / 1000) * viewportWidth,
    top: (y0 / 1000) * viewportHeight,
    width: ((x1 - x0) / 1000) * viewportWidth,
    height: ((y1 - y0) / 1000) * viewportHeight,
  };
}
