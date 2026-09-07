import { expect, test } from "@playwright/test";

const PAPER_ID = "0e82764a-ae5a-4f8a-a212-e2896ee50702";

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
  await expect(page.locator(".block-card").first()).toContainText("Deep Residual Learning");

  const firstRightBlock = page.locator('.block-card[data-order-idx="0"]');
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

  await expectPairedBbox(7);

  await firstRightBlock.click();
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
