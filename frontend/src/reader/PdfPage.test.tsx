import { act, render } from "@testing-library/react";
import { createRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PDFDocumentProxy } from "pdfjs-dist";

import { makeBlock } from "../test/fixtures";
import { PdfPage, type PdfPageHandle } from "./PdfPage";

describe("PdfPage render readiness", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as CanvasRenderingContext2D);
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {}
        disconnect() {}
        unobserve() {}
        takeRecords() {
          return [];
        }
      },
    );
  });

  function fixture() {
    let resolveRender!: () => void;
    const renderPromise = new Promise<void>((resolve) => {
      resolveRender = resolve;
    });
    const cancel = vi.fn();
    const renderPage = vi.fn(() => ({ promise: renderPromise, cancel }));
    const page = {
      getViewport: () => ({ width: 800, height: 1000 }),
      render: renderPage,
    };
    const document = {
      getPage: vi.fn(async () => page),
    } as unknown as PDFDocumentProxy;
    const root = documentOwner().createElement("div");
    const ref = createRef<PdfPageHandle>();
    const rendered = render(
      <PdfPage
        ref={ref}
        document={document}
        pageNumber={1}
        blocks={[makeBlock()]}
        scrollRootRef={{ current: root }}
      />,
    );
    return { ...rendered, ref, resolveRender, renderPage, cancel };
  }

  it("shares one promise and commits overlay only after RenderTask.promise", async () => {
    const page = fixture();
    const first = page.ref.current!.ensureRendered();
    const second = page.ref.current!.ensureRendered();
    expect(first).toBe(second);
    await act(async () => Promise.resolve());
    expect(page.renderPage).toHaveBeenCalledTimes(1);
    expect(page.container.querySelector(".bbox-layer")).toBeNull();

    await act(async () => {
      page.resolveRender();
      await Promise.resolve();
    });
    await first;
    expect(page.container.querySelector(".bbox-layer")).not.toBeNull();
  });

  it("cancels an in-flight RenderTask on unmount", async () => {
    const page = fixture();
    void page.ref.current!.ensureRendered();
    await act(async () => Promise.resolve());
    page.unmount();
    expect(page.cancel).toHaveBeenCalledOnce();
  });

  it("handles a metadata page rejection instead of leaving it unhandled", async () => {
    const document = {
      getPage: vi.fn(() => Promise.reject(new Error("Transport destroyed"))),
    } as unknown as PDFDocumentProxy;
    const root = documentOwner().createElement("div");
    const rendered = render(
      <PdfPage
        document={document}
        pageNumber={1}
        blocks={[]}
        scrollRootRef={{ current: root }}
      />,
    );

    await act(async () => Promise.resolve());
    expect(rendered.getByText(/Transport destroyed/)).toBeInTheDocument();
  });
});

function documentOwner() {
  return window.document;
}
