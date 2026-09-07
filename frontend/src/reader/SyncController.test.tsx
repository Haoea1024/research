import { act, renderHook } from "@testing-library/react";
import type { MutableRefObject } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useReaderStore } from "../stores/readerStore";
import { makeBlock } from "../test/fixtures";
import type { BlockPaneHandle } from "./BlockPane";
import { useSyncController } from "./SyncController";
import type { PageReadyHandle } from "./types";

describe("useSyncController", () => {
  beforeEach(() => useReaderStore.getState().reset());

  it("maps a PDF block id to the virtual list without DOM assumptions", () => {
    const block = makeBlock({ id: "paper:7", order_idx: 7 });
    const { result } = renderHook(() => useSyncController([block]));
    const scrollToBlock = vi.fn(() => true);
    (result.current.blockPaneRef as MutableRefObject<BlockPaneHandle | null>).current = {
      scrollToBlock,
    };
    act(() => result.current.onPdfActiveBlock(block.id));
    expect(scrollToBlock).toHaveBeenCalledWith(block.id);
  });

  it("prevents an older asynchronous PDF jump from overriding a newer one", async () => {
    const first = makeBlock({ id: "paper:1", order_idx: 1 });
    const second = makeBlock({ id: "paper:2", order_idx: 2 });
    const pending: Array<(accepted: boolean) => void> = [];
    const scrollToBlock = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          pending.push(resolve);
        }),
    );
    const { result } = renderHook(() => useSyncController([first, second]));
    (result.current.pdfPaneRef as MutableRefObject<PageReadyHandle | null>).current = {
      ensurePageRendered: vi.fn(async () => undefined),
      scrollToBlock,
    };

    act(() => result.current.onBlocksActiveBlock(first.id));
    const oldGeneration = useReaderStore.getState().syncGeneration;
    act(() => result.current.onBlocksActiveBlock(second.id));
    const newGeneration = useReaderStore.getState().syncGeneration;
    expect(newGeneration).toBeGreaterThan(oldGeneration);
    expect(useReaderStore.getState().syncTargetBlockId).toBe(second.id);

    await act(async () => pending[0](false));
    expect(useReaderStore.getState().syncGeneration).toBe(newGeneration);
    expect(useReaderStore.getState().syncTargetBlockId).toBe(second.id);

    await act(async () => pending[1](true));
    act(() => result.current.onPdfActiveBlock(second.id));
    expect(useReaderStore.getState().syncOrigin).toBe("blocks");
    expect(useReaderStore.getState().activeBlockId).toBe(second.id);

    act(() => result.current.onPdfActiveBlock(first.id));
    expect(useReaderStore.getState().activeBlockId).toBe(second.id);
    expect(scrollToBlock).toHaveBeenCalledTimes(2);

    act(() => result.current.onPdfUserIntent());
    act(() => result.current.onPdfActiveBlock(first.id));
    expect(useReaderStore.getState().activeBlockId).toBe(first.id);
    expect(useReaderStore.getState().syncOrigin).not.toBe("blocks");
  });
});
