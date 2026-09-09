import { fireEvent, render, screen } from "@testing-library/react";
import { forwardRef, useImperativeHandle } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useReaderStore } from "../stores/readerStore";
import { makeBlock } from "../test/fixtures";
import type { TranslationPaneHandle } from "./types";

vi.mock("./LayoutTranslationView", () => ({ LayoutTranslationView: forwardRef<TranslationPaneHandle, { onActiveBlock?: (id: string) => void }>((props, ref) => { useImperativeHandle(ref, () => ({ scrollToBlock(id) { props.onActiveBlock?.(id); return true; } })); return <div>layout-view</div>; }) }));
vi.mock("./StructuredBlockView", () => ({ StructuredBlockView: forwardRef<TranslationPaneHandle, { onActiveBlock?: (id: string) => void }>((props, ref) => { useImperativeHandle(ref, () => ({ scrollToBlock(id) { props.onActiveBlock?.(id); return true; } })); return <div>structured-view</div>; }) }));
import { TranslationPane } from "./TranslationPane";

beforeEach(() => useReaderStore.getState().reset());
it("switches views as a local restore without changing the PDF or ping-ponging", () => {
  const onActiveBlock = vi.fn();
  const block = makeBlock({ id: "paper:12", order_idx: 12 });
  useReaderStore.getState().setActiveBlockId(block.id);
  render(<TranslationPane blocks={[block]} figures={[]} pageMetrics={new Map()} onActiveBlock={onActiveBlock} />);
  fireEvent.click(screen.getByRole("button", { name: "结构化" }));
  expect(useReaderStore.getState().activeBlockId).toBe(block.id);
  expect(useReaderStore.getState().syncOrigin).toBeNull();
  expect(onActiveBlock).not.toHaveBeenCalled();
  expect(screen.getByText("structured-view")).toBeInTheDocument();
});
