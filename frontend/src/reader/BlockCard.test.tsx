import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useReaderStore } from "../stores/readerStore";
import { makeBlock, makeFigure } from "../test/fixtures";
import { BlockCard } from "./BlockCard";

describe("BlockCard", () => {
  beforeEach(() => useReaderStore.getState().reset());

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
});
