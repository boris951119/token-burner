# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-3-1-3_Select_rectangular_range_A1_B2_and_persist_after_r.spec.ts >> REQ-3-1-3 Select a Rectangular Cell Range >> select rectangular range persists after refresh
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-3-1-3_Select_rectangular_range_A1_B2_and_persist_after_r.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('gridcell', { name: /Item/i })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('gridcell', { name: /Item/i }) with timeout 10000ms
  - waiting for getByRole('gridcell', { name: /Item/i })

```

```yaml
- heading "Q3 Sales" [level=1]
- text: "Region: East, North"
- tablist:
  - tab "Sheet1" [selected]
  - tab "Sheet2"
- text: Formula bar
- textbox "Formula bar"
- grid "Worksheet grid":
  - rowgroup:
    - row "1 Delete row 1 Insert row above Insert row below A1 B1":
      - text: "1"
      - button "Delete row 1": Delete row
      - button "Insert row above"
      - button "Insert row below"
      - gridcell "A1": Region
      - gridcell "B1": Q3 Sales
    - row "2 Delete row 2 Insert row above Insert row below A2 B2":
      - text: "2"
      - button "Delete row 2": Delete row
      - button "Insert row above"
      - button "Insert row below"
      - gridcell "A2": East
      - gridcell "B2": "100"
    - row "3 Delete row 3 Insert row above Insert row below A3 B3":
      - text: "3"
      - button "Delete row 3": Delete row
      - button "Insert row above"
      - button "Insert row below"
      - gridcell "A3": North
      - gridcell "B3": "200"
- button "Insert 1 column left"
- button "Insert 1 column right"
- button "Delete column"
- button "Add worksheet"
- button "Export CSV"
- button "Delete worksheet"
- heading "Rename worksheet" [level=3]
- textbox "New name"
- button "Rename"
- link "Download current sheet":
  - /url: /editor/Q3%20Sales/download-csv?sheet=Sheet1
- heading "Pivot table editor" [level=3]
- text: Rows
- textbox "Rows"
- text: Columns
- textbox "Columns"
- text: Values
- textbox "Values"
- button "Refresh pivot table"
- button "Create pivot table"
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-3-1-3 Select a Rectangular Cell Range', () => {
  4  |   test('select rectangular range persists after refresh', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3 Sales/i }).click();
  7  |     const grid = page.getByRole('grid');
  8  |     await expect(grid).toBeVisible();
  9  |     await expect(grid).toHaveAttribute('aria-multiselectable', 'true');
  10 | 
  11 |     const cellA1 = page.getByRole('gridcell', { name: /Item/i });
  12 |     const cellB2 = page.getByRole('gridcell', { name: /^4$/i });
> 13 |     await expect(cellA1).toBeVisible();
     |                          ^ Error: expect(locator).toBeVisible() failed
  14 |     await expect(cellB2).toBeVisible();
  15 | 
  16 |     const boxA1 = await cellA1.boundingBox();
  17 |     const boxB2 = await cellB2.boundingBox();
  18 |     if (boxA1 && boxB2) {
  19 |       await page.mouse.move(boxA1.x + boxA1.width / 2, boxA1.y + boxA1.height / 2);
  20 |       await page.mouse.down();
  21 |       await page.mouse.move(boxB2.x + boxB2.width / 2, boxB2.y + boxB2.height / 2, { steps: 5 });
  22 |       await page.mouse.up();
  23 |     }
  24 | 
  25 |     await expect(page.getByRole('gridcell', { name: /Item/i })).toHaveAttribute('aria-selected', 'true');
  26 |     await expect(page.getByRole('gridcell', { name: /Qty/i })).toHaveAttribute('aria-selected', 'true');
  27 |     await expect(page.getByRole('gridcell', { name: /Pen/i })).toHaveAttribute('aria-selected', 'true');
  28 |     await expect(page.getByRole('gridcell', { name: /^4$/i })).toHaveAttribute('aria-selected', 'true');
  29 | 
  30 |     const outsideCell = page.getByRole('gridcell', { name: /^$/ }).first();
  31 |     await expect(outsideCell).toHaveAttribute('aria-selected', 'false');
  32 | 
  33 |     await page.reload();
  34 |     await expect(page.getByRole('grid')).toBeVisible();
  35 |     await expect(page.getByRole('gridcell', { name: /Item/i })).toHaveAttribute('aria-selected', 'true');
  36 |     await expect(page.getByRole('gridcell', { name: /^4$/i })).toHaveAttribute('aria-selected', 'true');
  37 |   });
  38 | });
```