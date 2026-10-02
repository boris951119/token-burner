# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-3-2-1_Cut_range_A1_B2_to_D1_E2_clears_source_and_populat.spec.ts >> REQ-3-2-1 Copy, Cut, and Paste Cell Ranges >> cut range A1:B2 to D1:E2 clears source and populates target
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-3-2-1_Cut_range_A1_B2_to_D1_E2_clears_source_and_populat.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('grid')
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('grid') with timeout 10000ms
  - waiting for getByRole('grid')

```

```yaml
- heading "Q3 Sales" [level=1]
- text: "Region: East, North"
- link "Sheet1":
  - /url: /editor/Q3%20Sales?sheet=Sheet1
- link "Sheet2":
  - /url: /editor/Q3%20Sales?sheet=Sheet2
- text: Formula bar
- textbox "Formula bar"
- table:
  - rowgroup:
    - row "1 Delete row 1 Insert row above Insert row below Region Q3 Sales":
      - cell "1 Delete row 1 Insert row above Insert row below":
        - text: "1"
        - button "Delete row 1": Delete row
        - button "Insert row above"
        - button "Insert row below"
      - rowheader "Region"
      - columnheader "Q3 Sales"
    - row "2 Delete row 2 Insert row above Insert row below East 100":
      - cell "2 Delete row 2 Insert row above Insert row below":
        - text: "2"
        - button "Delete row 2": Delete row
        - button "Insert row above"
        - button "Insert row below"
      - cell "East"
      - cell "100"
    - row "3 Delete row 3 Insert row above Insert row below North 200":
      - cell "3 Delete row 3 Insert row above Insert row below":
        - text: "3"
        - button "Delete row 3": Delete row
        - button "Insert row above"
        - button "Insert row below"
      - cell "North"
      - cell "200"
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
  3  | test.describe('REQ-3-2-1 Copy, Cut, and Paste Cell Ranges', () => {
  4  |   test('cut range A1:B2 to D1:E2 clears source and populates target', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3 Sales/i }).click();
  7  |     const grid = page.getByRole('grid');
> 8  |     await expect(grid).toBeVisible();
     |                        ^ Error: expect(locator).toBeVisible() failed
  9  | 
  10 |     const cellA1 = page.getByRole('gridcell', { name: /Item/i });
  11 |     const cellB2 = page.getByRole('gridcell', { name: /^4$/i });
  12 |     await expect(cellA1).toBeVisible();
  13 |     await expect(cellB2).toBeVisible();
  14 | 
  15 |     const boxA1 = await cellA1.boundingBox();
  16 |     const boxB2 = await cellB2.boundingBox();
  17 |     if (boxA1 && boxB2) {
  18 |       await page.mouse.move(boxA1.x + boxA1.width / 2, boxA1.y + boxA1.height / 2);
  19 |       await page.mouse.down();
  20 |       await page.mouse.move(boxB2.x + boxB2.width / 2, boxB2.y + boxB2.height / 2, { steps: 5 });
  21 |       await page.mouse.up();
  22 |     }
  23 | 
  24 |     await page.keyboard.press('Control+X');
  25 | 
  26 |     const nameBox = page.getByLabel('名称').or(page.getByPlaceholder('名称')).or(page.getByRole('textbox')).first();
  27 |     await nameBox.click();
  28 |     await nameBox.fill('D1');
  29 |     await page.keyboard.press('Enter');
  30 | 
  31 |     await page.keyboard.press('Control+V');
  32 | 
  33 |     await expect(page.getByRole('gridcell', { name: /Item/i })).toHaveCount(1);
  34 |     await expect(page.getByRole('gridcell', { name: /Qty/i })).toHaveCount(1);
  35 |     await expect(page.getByRole('gridcell', { name: /Pen/i })).toHaveCount(1);
  36 |     await expect(page.getByRole('gridcell', { name: /^4$/i })).toHaveCount(1);
  37 |   });
  38 | });
```