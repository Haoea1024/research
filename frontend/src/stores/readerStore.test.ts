import { beforeEach, describe, expect, it } from "vitest";

import { useReaderStore } from "./readerStore";

describe("readerStore generation control", () => {
  beforeEach(() => useReaderStore.getState().reset());

  it("invalidates an old generation when the user takes control", () => {
    const oldGeneration = useReaderStore.getState().beginSync("pdf", "paper:4");
    const newGeneration = useReaderStore.getState().takeControl("blocks");
    expect(newGeneration).toBeGreaterThan(oldGeneration);
    useReaderStore.getState().finishSync(oldGeneration);
    expect(useReaderStore.getState().syncOrigin).toBe("blocks");
  });

  it("only releases the current generation", () => {
    const generation = useReaderStore.getState().beginSync("blocks", "paper:8");
    useReaderStore.getState().finishSync(generation);
    expect(useReaderStore.getState().syncOrigin).toBeNull();
    expect(useReaderStore.getState().syncTargetBlockId).toBeNull();
  });
});
