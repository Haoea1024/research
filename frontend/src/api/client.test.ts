import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, paperApi } from "./client";

describe("paperApi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("constructs an encoded PDF URL", () => {
    expect(paperApi.pdfUrl("paper/id")).toBe("/api/papers/paper%2Fid/pdf");
  });

  it("keeps explicit backend errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "paper not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(paperApi.get("missing")).rejects.toEqual(
      expect.objectContaining({ status: 404, detail: "paper not found" }),
    );
  });

  it("sends only visible block ids to the viewport endpoint", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await paperApi.viewport("paper/id", ["b1", "b2"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/papers/paper%2Fid/viewport",
      expect.objectContaining({ body: JSON.stringify({ visible_block_ids: ["b1", "b2"] }) }),
    );
  });
});
