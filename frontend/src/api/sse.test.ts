import { describe, expect, it } from "vitest";

import { parseFrame } from "./sse";

describe("parseFrame", () => {
  it("parses named SSE events and JSON payloads", () => {
    expect(parseFrame('id: 7\nevent: block\ndata: {"block_id":"b1","status":"done"}')).toEqual({
      id: 7,
      event: "block",
      data: { block_id: "b1", status: "done" },
    });
  });

  it("ignores keepalives and unknown events", () => {
    expect(parseFrame(": ping")).toBeNull();
    expect(parseFrame("event: message\ndata: {}")) .toBeNull();
  });
});
