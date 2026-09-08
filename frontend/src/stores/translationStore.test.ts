import { beforeEach, describe, expect, it } from "vitest";

import { useTranslationStore } from "./translationStore";

describe("translationStore", () => {
  beforeEach(() => useTranslationStore.getState().reset());

  it("applies block and progress events independently", () => {
    useTranslationStore.getState().apply({
      id: 1,
      event: "block",
      data: { block_id: "b1", status: "done", zh_text: "译文" },
    });
    useTranslationStore.getState().apply({
      id: 2,
      event: "progress",
      data: { run_id: "r1", total: 1, pending: 0, queued: 0, translating: 0, done: 1, failed: 0 },
    });
    expect(useTranslationStore.getState().byBlockId.b1.zh_text).toBe("译文");
    expect(useTranslationStore.getState().progress?.done).toBe(1);
  });

  it("keeps a successful translation when retranslation reports an error", () => {
    useTranslationStore.getState().replace([{
      block_id: "b1",
      status: "done",
      zh_text: "旧译文",
      error: null,
      model: "fake/old",
      glossary_version: 1,
      updated_at: null,
      cached: true,
    }]);
    useTranslationStore.getState().apply({
      id: 3,
      event: "error",
      data: { block_id: "b1", status: "done", error: "重译失败", retranslate_failed: true },
    });
    expect(useTranslationStore.getState().byBlockId.b1.zh_text).toBe("旧译文");
    expect(useTranslationStore.getState().byBlockId.b1.retranslate_failed).toBe(true);
  });

  it("treats glossary preparation failure as run-level and keeps blocks pending", () => {
    useTranslationStore.getState().replace([{
      block_id: "b1",
      status: "pending",
      zh_text: null,
      error: null,
      model: null,
      glossary_version: null,
      updated_at: null,
      cached: false,
    }]);
    useTranslationStore.getState().apply({
      id: 4,
      event: "error",
      data: {
        block_id: null,
        code: "GLOSSARY_PREPARATION_FAILED",
        retryable: true,
        error: "timeout",
      },
    });
    expect(useTranslationStore.getState().byBlockId.b1.status).toBe("pending");
    expect(useTranslationStore.getState().streamErrorCode).toBe("GLOSSARY_PREPARATION_FAILED");
  });
});
