import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useReaderStore } from "../stores/readerStore";
import { useTranslationStore } from "../stores/translationStore";
import { makeBlock, makeFigure } from "../test/fixtures";
import { BlockCard } from "./BlockCard";
import { TableInFlow } from "./TableInFlow";

describe("Block rendering", () => {
  beforeEach(() => { useReaderStore.getState().reset(); useTranslationStore.getState().reset(); });
  it("shares hover state without changing active state", () => {
    const block = makeBlock();
    render(<BlockCard block={block} />);
    fireEvent.pointerEnter(screen.getByText("Example block").closest("article")!);
    expect(useReaderStore.getState().hoverBlockId).toBe(block.id);
    expect(useReaderStore.getState().activeBlockId).toBeNull();
  });
  it("keeps raw table HTML inert in structured and layout views", () => {
    const block = makeBlock({ type: "table", content_md: "Table 1 caption\n\n<table><img src=x onerror=attack></table>" });
    const figure = makeFigure({ table_html: "<img src=x onerror=attack>", caption_text: "Table 1 caption" });
    const structured = render(<BlockCard block={block} figure={figure} />);
    expect(screen.getByTestId("table-placeholder")).toBeInTheDocument();
    expect(structured.container.innerHTML).not.toContain("onerror");
    structured.unmount();
    const layout = render(<TableInFlow table={figure} />);
    expect(layout.container.querySelectorAll("img")).toHaveLength(1);
    expect(layout.container.innerHTML).not.toContain("onerror");
    expect(screen.getByText("Table 1 caption")).toBeInTheDocument();
  });
  it("turns a missing parser crop into an explicit placeholder", () => {
    const table = makeFigure({ image_url: "/api/figures/missing/image", caption_text: "Missing crop" });
    const { container } = render(<TableInFlow table={table} />);
    fireEvent.error(container.querySelector("img")!);
    expect(screen.getByText("Table crop unavailable")).toBeInTheDocument();
    expect(screen.getByText("Missing crop")).toBeInTheDocument();
  });
  it("renders formula content through KaTeX", () => {
    render(<BlockCard block={makeBlock({ type: "formula", content_md: "$$x+y$$" })} />);
    expect(screen.getByLabelText("Formula").querySelector(".katex")).not.toBeNull();
  });
  it("renders inline math and safe superscript in the shared mixed-content renderer", () => {
    const source = String.raw`The maps $\mathcal{H}(\mathbf{x})$ and \(\mathcal{F}(\mathbf{x})\) use ResNet<sup>1</sup>.`;
    const { container } = render(<BlockCard block={makeBlock({ content_md: source })} />);
    expect(screen.getAllByLabelText("Math expression")).toHaveLength(2);
    expect(container.querySelectorAll(".katex")).toHaveLength(2);
    expect(container.querySelector("sup")).toHaveTextContent("1");
  });
  it("keeps unsupported HTML escaped instead of injecting it", () => {
    const { container } = render(<BlockCard block={makeBlock({ content_md: "safe <img src=x onerror=attack> text" })} />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x onerror=attack>/)).toBeInTheDocument();
  });
  it("prefers completed Chinese while retaining English disclosure", () => {
    const block = makeBlock({ content_md: "English source" });
    useTranslationStore.getState().replace([{ block_id: block.id, status: "done", zh_text: "中文译文", error: null, model: "fake/translate", glossary_version: 1, updated_at: null, cached: false }]);
    render(<BlockCard block={block} />);
    expect(screen.getByText("中文译文")).toBeInTheDocument();
    expect(screen.getByText("查看英文原文")).toBeInTheDocument();
  });
  it("falls back to English and exposes only explicit failed retry", () => {
    const retry = vi.fn();
    const block = makeBlock({ content_md: "English fallback" });
    useTranslationStore.getState().replace([{ block_id: block.id, status: "failed", zh_text: null, error: "raw failure", model: "fake/translate", glossary_version: 1, updated_at: null, cached: false }]);
    render(<BlockCard block={block} onRetranslate={retry} />);
    fireEvent.click(screen.getByText("重试翻译"));
    expect(retry).toHaveBeenCalledWith(block.id);
  });
  it("shows skipped English without a retry action", () => {
    const block = makeBlock({ content_md: "https://example.com" });
    useTranslationStore.getState().replace([{ block_id: block.id, status: "skipped", zh_text: null, error: null, model: null, glossary_version: null, updated_at: null, cached: false, skip_reason: "URL_METADATA" }]);
    render(<BlockCard block={block} />);
    expect(screen.getByText("已跳过：URL_METADATA")).toBeInTheDocument();
    expect(screen.queryByText("重试翻译")).toBeNull();
  });
  it("keeps an old successful translation visible during retranslation", () => {
    const block = makeBlock({ content_md: "English source" });
    useTranslationStore.getState().replace([{ block_id: block.id, status: "translating", zh_text: "旧的成功译文", error: null, model: "fake/old", glossary_version: 1, updated_at: null, cached: true }]);
    render(<BlockCard block={block} />);
    expect(screen.getByText("旧的成功译文")).toBeInTheDocument();
    expect(screen.getByText("translating")).toBeInTheDocument();
  });
});
