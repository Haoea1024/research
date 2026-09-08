import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useReaderStore } from "../stores/readerStore";
import { useTranslationStore } from "../stores/translationStore";
import { makeBlock, makeFigure } from "../test/fixtures";
import { BlockCard } from "./BlockCard";

describe("BlockCard", () => {
  beforeEach(() => {
    useReaderStore.getState().reset();
    useTranslationStore.getState().reset();
  });

  it("shares hover state without changing active state", () => {
    const block = makeBlock();
    render(<BlockCard block={block} />);
    fireEvent.pointerEnter(screen.getByText("Example block").closest("article")!);
    expect(useReaderStore.getState().hoverBlockId).toBe(block.id);
    expect(useReaderStore.getState().activeBlockId).toBeNull();
  });

  it("shows a safe table placeholder without injecting table_html", () => {
    const block = makeBlock({
      type: "table",
      content_md: 'Table 1 caption\n\n<table><img src=x onerror="window.__unsafe=true"></table>',
    });
    const figure = makeFigure({
      table_html: '<img src=x onerror="window.__unsafe=true">',
      caption_text: "Table 1 caption",
    });
    const { container } = render(<BlockCard block={block} figure={figure} />);
    expect(screen.getByTestId("table-placeholder")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
    expect(screen.getByText("Table 1 caption")).toBeInTheDocument();
  });

  it("renders formula content through KaTeX", () => {
    render(<BlockCard block={makeBlock({ type: "formula", content_md: "$$x+y$$" })} />);
    expect(screen.getByLabelText("Formula").querySelector(".katex")).not.toBeNull();
  });

  it("prefers completed Chinese while retaining English disclosure", () => {
    const block = makeBlock({ content_md: "English source" });
    useTranslationStore.getState().replace([{
      block_id: block.id,
      status: "done",
      zh_text: "中文译文",
      error: null,
      model: "fake/translate",
      glossary_version: 1,
      updated_at: null,
      cached: false,
    }]);
    render(<BlockCard block={block} />);
    expect(screen.getByText("中文译文")).toBeInTheDocument();
    expect(screen.getByText("查看英文原文")).toBeInTheDocument();
  });

  it("uses English fallback and exposes retry for failed translations", () => {
    const retry = vi.fn();
    const block = makeBlock({ content_md: "English fallback" });
    useTranslationStore.getState().replace([{
      block_id: block.id,
      status: "failed",
      zh_text: null,
      error: "raw failure",
      model: "fake/translate",
      glossary_version: 1,
      updated_at: null,
      cached: false,
    }]);
    render(<BlockCard block={block} onRetranslate={retry} />);
    expect(screen.getByText("English fallback")).toBeInTheDocument();
    fireEvent.click(screen.getByText("重试翻译"));
    expect(retry).toHaveBeenCalledWith(block.id);
  });

  it("shows skipped content as English without a retry action", () => {
    const block = makeBlock({ content_md: "https://example.com" });
    useTranslationStore.getState().replace([{
      block_id: block.id,
      status: "skipped",
      zh_text: null,
      error: null,
      model: null,
      glossary_version: null,
      updated_at: null,
      cached: false,
      skip_reason: "URL_METADATA",
    }]);
    render(<BlockCard block={block} />);
    expect(screen.getByText("https://example.com")).toBeInTheDocument();
    expect(screen.getByText("已跳过：URL_METADATA")).toBeInTheDocument();
    expect(screen.queryByText("重试翻译")).toBeNull();
  });

  it("keeps the old successful text visible during retranslation", () => {
    const block = makeBlock({ content_md: "English source" });
    useTranslationStore.getState().replace([{
      block_id: block.id,
      status: "translating",
      zh_text: "旧的成功译文",
      error: null,
      model: "fake/old",
      glossary_version: 1,
      updated_at: null,
      cached: true,
    }]);
    render(<BlockCard block={block} />);
    expect(screen.getByText("旧的成功译文")).toBeInTheDocument();
    expect(screen.getByText("translating")).toBeInTheDocument();
  });
});
