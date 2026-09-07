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
});
