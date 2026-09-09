import { expect, test } from "@playwright/test";

const PAPER_ID = "0e82764a-ae5a-4f8a-a212-e2896ee50702";

test("real ResNet layout preserves structure, media, state, and local view restore", async ({ page }) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.goto(`/?paperId=${PAPER_ID}`);
  await expect(page.getByRole("heading", { name: "resnet_1512.03385" })).toBeVisible();
  await expect(page.getByRole("button", { name: "版式对照" })).toHaveClass(/is-selected/);
  const firstLayoutPage = page.locator('[data-layout-page="1"]');
  await expect(firstLayoutPage).toBeVisible();
  await expect(firstLayoutPage).toHaveAttribute("data-layout-mode", "two-column");
  await expect(firstLayoutPage.locator('.layout-full [data-order-idx="0"]')).toBeVisible();
  await expect(firstLayoutPage.locator('.layout-column-left [data-order-idx="6"]')).toContainText("摘要");
  await expect(firstLayoutPage.locator('.layout-marginalia [data-order-idx="17"]')).toBeVisible();
  await expect(firstLayoutPage.locator('.layout-column-left [data-order-idx="7"]')).toBeVisible();
  await expect(firstLayoutPage.locator('.layout-column-right [data-order-idx="14"]')).toBeVisible();
  await expect(firstLayoutPage.locator('[data-order-idx="8"] sup')).toHaveText("1");
  await expect(firstLayoutPage.locator('[data-testid="figure-in-flow"] img')).toHaveCount(2);
  await expect(firstLayoutPage.locator(".state-done")).toHaveCount(13);
  await expect(firstLayoutPage.locator(".state-skipped")).toHaveCount(4);
  await expect(firstLayoutPage.locator(".state-failed")).toHaveCount(0);
  await firstLayoutPage.locator('[data-order-idx="0"]').hover();
  await expect(page.locator('.bbox-box[data-order-idx="0"]')).toHaveClass(/is-hovered/);

  const layoutScroll = page.getByTestId("layout-scroll");
  await layoutScroll.evaluate((element) => { element.scrollTop = 220; element.dispatchEvent(new Event("scroll")); });
  await expect(firstLayoutPage.locator(".layout-block.is-active").first()).toBeVisible();
  const activeId = await firstLayoutPage.locator(".layout-block.is-active").first().getAttribute("data-block-id");
  const pdfBeforeSwitch = await page.getByTestId("pdf-scroll").evaluate((element) => element.scrollTop);
  await page.getByRole("button", { name: "结构化" }).click();
  await expect(page.locator(`.block-card[data-block-id="${activeId}"]`)).toHaveClass(/is-active/);
  const pdfAfterSwitch = await page.getByTestId("pdf-scroll").evaluate((element) => element.scrollTop);
  expect(Math.abs(pdfAfterSwitch - pdfBeforeSwitch)).toBeLessThan(2);
  await page.getByRole("button", { name: "版式对照" }).click();
  await expect(page.locator(`.layout-block[data-block-id="${activeId}"]`)).toHaveClass(/is-active/);

  async function seekLayoutBlock(orderIdx: number) {
    const target = page.locator(`.layout-block[data-order-idx="${orderIdx}"]`);
    await layoutScroll.hover();
    for (let step = 0; step < 80; step += 1) {
      if (await target.isVisible()) return target;
      const visible = await page.locator(".layout-block").evaluateAll((elements) => elements.map((element) => Number(element.getAttribute("data-order-idx"))));
      await page.mouse.wheel(0, orderIdx < Math.min(...visible) ? -620 : 620);
      await page.evaluate(() => new Promise(requestAnimationFrame));
    }
    throw new Error(`Layout block ${orderIdx} did not enter the page-level virtualized viewport`);
  }
  await seekLayoutBlock(40);
  await expect(page.locator('.layout-block[data-order-idx="40"] .katex')).toBeVisible();
  await seekLayoutBlock(35);
  await expect(page.locator('.layout-block[data-order-idx="35"] .mixed-math-inline .katex').first()).toBeVisible();
  await seekLayoutBlock(57);
  const pageFour = page.locator('[data-layout-page="4"]');
  await expect(pageFour).toHaveAttribute("data-layout-mode", "two-column");
  const figureThree = pageFour.locator('.layout-column-left [data-order-idx="57"]');
  const rightBody = pageFour.locator('.layout-column-right [data-order-idx="58"]');
  await expect(figureThree.locator('[data-testid="figure-in-flow"] img')).toBeVisible();
  await expect(rightBody).toBeVisible();
  expect(Math.abs((await figureThree.boundingBox())!.y - (await rightBody.boundingBox())!.y)).toBeLessThan(120);
  await seekLayoutBlock(67);
  const tableImage = page.locator('.layout-block[data-order-idx="67"] [data-testid="table-in-flow"] img');
  await expect(tableImage).toBeVisible();
  expect(await tableImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  await expect.poll(async () => page.getByTestId("pdf-scroll").evaluate((element) => element.scrollTop)).toBeGreaterThan(2_000);

  const pdfScroll = page.getByTestId("pdf-scroll");
  await pdfScroll.click({ position: { x: 300, y: 220 } });
  await pdfScroll.press("Home");
  await expect.poll(async () => layoutScroll.evaluate((element) => element.scrollTop)).toBeLessThan(500);
  await expect(page.locator('[data-layout-page="1"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test("real ResNet reader renders and synchronizes without console errors", async ({ page }) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.goto(`/?paperId=${PAPER_ID}`);
  await expect(page.getByRole("heading", { name: "resnet_1512.03385" })).toBeVisible();
  await expect(page.locator(".pdf-page-shell")).toHaveCount(12);
  await expect(page.locator('.pdf-page-shell[data-page-number="1"] .bbox-layer')).toBeVisible();
  await page.getByRole("button", { name: "结构化" }).click();
  await expect(page.locator(".block-card").first()).toContainText("Deep Residual Learning");

  const firstRightBlock = page.locator('.block-card[data-order-idx="0"]');
  await expect(firstRightBlock.locator(".translated-content")).toContainText(
    "用于图像识别的深度残差学习",
  );
  await expect(firstRightBlock.locator(".state-done")).toBeVisible();
  await expect(firstRightBlock.getByText("查看英文原文")).toBeVisible();
  await firstRightBlock.hover();
  await expect(page.locator('.bbox-box[data-order-idx="0"]')).toHaveClass(/is-hovered/);

  async function expectPairedBbox(orderIdx: number) {
    const rightBlock = page.locator(`.block-card[data-order-idx="${orderIdx}"]`);
    const overlay = page.locator(`.bbox-box[data-order-idx="${orderIdx}"]`);
    await rightBlock.hover();
    await expect(overlay).toBeVisible();
    await expect(overlay).toHaveClass(/is-hovered/);
    expect(
      await overlay.evaluate((element) => {
        const pageShell = element.closest(".pdf-page-shell");
        if (!pageShell) return false;
        const box = element.getBoundingClientRect();
        const pageBox = pageShell.getBoundingClientRect();
        return (
          box.left >= pageBox.left &&
          box.top >= pageBox.top &&
          box.right <= pageBox.right &&
          box.bottom <= pageBox.bottom
        );
      }),
    ).toBe(true);
  }

  await page.locator(".block-list-shell").hover();
  await page.mouse.wheel(0, 480);
  await expectPairedBbox(7);
  await expect(page.locator('.block-card[data-order-idx="7"] .translated-content')).toContainText(
    "残差学习框架",
  );

  await page.locator(".block-list-shell").click({ position: { x: 300, y: 300 } });
  async function seekBlock(orderIdx: number) {
    const target = page.locator(`.block-card[data-order-idx="${orderIdx}"]`);
    await page.locator(".block-list-shell").hover();
    for (let step = 0; step < 120; step += 1) {
      if (await target.isVisible()) return;
      const visibleIndices = await page.locator(".block-card").evaluateAll((elements) =>
        elements.map((element) => Number(element.getAttribute("data-order-idx"))),
      );
      const first = Math.min(...visibleIndices);
      const last = Math.max(...visibleIndices);
      await page.mouse.wheel(0, orderIdx < first ? -320 : orderIdx > last ? 320 : 0);
      await page.evaluate(() => new Promise(requestAnimationFrame));
    }
    throw new Error(`Block ${orderIdx} did not enter the virtualized viewport`);
  }

  await seekBlock(40);
  await expect(page.locator('.block-card[data-order-idx="40"] .katex')).toBeVisible();
  await expectPairedBbox(40);
  await seekBlock(57);
  await expect(
    page.locator('.block-card[data-order-idx="57"] [data-testid="figure-placeholder"]'),
  ).toBeVisible();
  await expectPairedBbox(57);
  await seekBlock(67);
  const tableCard = page.locator('.block-card[data-order-idx="67"]');
  await expect(tableCard.getByTestId("table-placeholder")).toBeVisible();
  await expect(tableCard.locator("table, img")).toHaveCount(0);
  await expectPairedBbox(67);

  await seekBlock(89);
  await expect(page.locator('.block-card[data-order-idx="89"] .state-skipped')).toBeVisible();
  await expect(page.locator('.block-card[data-order-idx="89"] .parser-warning')).toContainText("解析片段不完整");
  await seekBlock(123);
  await expect(page.locator('.block-card[data-order-idx="123"] .state-skipped')).toBeVisible();
  await expect(page.locator('.block-card[data-order-idx="123"] .parser-warning')).toContainText("参考文献列表");
  await seekBlock(128);
  await expect(page.locator('.block-card[data-order-idx="128"]')).toContainText("PASCAL VOC");

  await seekBlock(14);
  const repairedCard = page.locator('.block-card[data-order-idx="14"]');
  await expect(repairedCard.locator(".state-done")).toBeVisible();
  await expect(repairedCard.locator(".translated-content")).toContainText("梯度消失/爆炸");
  await expect(repairedCard.locator(".retry-button")).toHaveCount(0);

  for (const orderIdx of [5, 13, 17, 18]) {
    await seekBlock(orderIdx);
    const skippedCard = page.locator(`.block-card[data-order-idx="${orderIdx}"]`);
    await expect(skippedCard.locator(".state-skipped")).toBeVisible();
    await expect(skippedCard.locator(".english-fallback")).toBeVisible();
    await expect(skippedCard.locator(".translation-skip")).toBeVisible();
    await expect(skippedCard.locator(".retry-button")).toHaveCount(0);
  }

  await seekBlock(160);
  await expect
    .poll(async () => page.locator('.pdf-page-shell[data-page-number="12"] .bbox-box').count())
    .toBeGreaterThan(0);
  await expect
    .poll(async () => page.locator(".pdf-scroll").evaluate((element) => element.scrollTop))
    .toBeGreaterThan(9_000);

  const pdfPane = page.locator(".pdf-scroll");
  await pdfPane.click({ position: { x: 400, y: 300 } });
  await pdfPane.press("Home");
  await expect.poll(async () => pdfPane.evaluate((element) => element.scrollTop)).toBe(0);
  await expect
    .poll(async () =>
      Number(await page.locator(".block-card").first().getAttribute("data-order-idx")),
    )
    .toBeLessThanOrEqual(5);

  expect(errors).toEqual([]);
});

test("fake S3 stream replaces English with Chinese and keeps source fallback", async ({ page }) => {
  const blockId = `${PAPER_ID}:0`;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route(`**/api/papers/${PAPER_ID}/translations`, async (route) => {
    await route.fulfill({ json: [] });
  });
  let translateRequests = 0;
  await page.route(`**/api/papers/${PAPER_ID}/translate`, async (route) => {
    translateRequests += 1;
    await route.fulfill({
      status: 202,
      json: { run_id: "fake-run", paper_id: PAPER_ID, total: 1, states: { [blockId]: "queued" } },
    });
  });
  await page.route(`**/api/papers/${PAPER_ID}/translate/stream?run_id=fake-run`, async (route) => {
    const body = [
      `id: 1\nevent: block\ndata: ${JSON.stringify({ block_id: blockId, status: "done", zh_text: "深度残差学习的中文测试译文" })}`,
      `id: 2\nevent: progress\ndata: ${JSON.stringify({ run_id: "fake-run", total: 1, pending: 0, queued: 0, translating: 0, done: 1, failed: 0 })}`,
      `id: 3\nevent: finished\ndata: ${JSON.stringify({ run_id: "fake-run", total: 1, pending: 0, queued: 0, translating: 0, done: 1, failed: 0 })}`,
      "",
    ].join("\n\n");
    await route.fulfill({ status: 200, contentType: "text/event-stream", body });
  });

  await page.goto(`/?paperId=${PAPER_ID}`);
  await page.getByRole("button", { name: "结构化" }).click();
  await page.getByRole("button", { name: /翻译全文 · 预计目标/ }).click();
  await expect(page.getByRole("dialog", { name: "确认翻译全文" })).toBeVisible();
  expect(translateRequests).toBe(0);
  await page.getByRole("button", { name: "确认翻译全文" }).click();
  await expect.poll(() => translateRequests).toBe(1);
  const firstCard = page.locator('.block-card[data-order-idx="0"]');
  await expect(firstCard).toContainText("深度残差学习的中文测试译文");
  await expect(firstCard.getByText("查看英文原文")).toBeVisible();
  await expect(page.getByText("1/1 done · 0 failed · 0 skipped")).toBeVisible();
  expect(errors).toEqual([]);
});
