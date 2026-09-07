import { ACTIVE_LINE_RATIO } from "./types";

export function closestBlockAtGuide(
  container: HTMLElement,
  elements: Iterable<HTMLElement>,
): string | null {
  const containerRect = container.getBoundingClientRect();
  const guideY = containerRect.top + container.clientHeight * ACTIVE_LINE_RATIO;
  let best: { id: string; distance: number } | null = null;
  for (const element of elements) {
    const rect = element.getBoundingClientRect();
    if (rect.bottom < containerRect.top || rect.top > containerRect.bottom) continue;
    const distance = Math.abs(rect.top + rect.height / 2 - guideY);
    const id = element.dataset.blockId;
    if (id && (!best || distance < best.distance)) best = { id, distance };
  }
  return best?.id ?? null;
}
