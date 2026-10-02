# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-3-2-2_Consecutive_undo_restores_changes_in_reverse_order.spec.ts >> REQ-3-2-2 Undo and Redo Recent Operations >> consecutive undo restores changes in reverse order
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-3-2-2_Consecutive_undo_restores_changes_in_reverse_order.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('cell', { name: /^Item$/i }).or(getByRole('gridcell', { name: /^Item$/i })).first()
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('cell', { name: /^Item$/i }).or(getByRole('gridcell', { name: /^Item$/i })).first() with timeout 10000ms
  - waiting for getByRole('cell', { name: /^Item$/i }).or(getByRole('gridcell', { name: /^Item$/i })).first()

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
  3  | test.describe('REQ-3-2-2 Undo and Redo Recent Operations', () => {
  4  |   test('consecutive undo restores changes in reverse order', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByText(/Q3\s+Sales/i).first().click();
  7  |     const cellItem = page.getByRole('cell', { name: /^Item$/i }).or(page.getByRole('gridcell', { name: /^Item$/i })).first();
  8  |     const cellPen = page.getByRole('cell', { name: /^Pen$/i }).or(page.getByRole('gridcell', { name: /^Pen$/i })).first();
> 9  |     await expect(cellItem).toBeVisible();
     |                            ^ Error: expect(locator).toBeVisible() failed
  10 |     await expect(cellPen).toBeVisible();
  11 |     await cellItem.dblclick();
  12 |     await page.keyboard.type('First');
  13 |     await page.keyboard.press('Enter');
  14 |     await cellPen.dblclick();
  15 |     await page.keyboard.type('Second');
  16 |     await page.keyboard.press('Enter');
  17 |     const cellFirst = page.getByRole('cell', { name: /^First$/i }).or(page.getByRole('gridcell', { name: /^First$/i })).first();
  18 |     const cellSecond = page.getByRole('cell', { name: /^Second$/i }).or(page.getByRole('gridcell', { name: /^Second$/i })).first();
  19 |     await expect(cellFirst).toBeVisible();
  20 |     await expect(cellSecond).toBeVisible();
  21 |     await page.keyboard.press('Control+z');
  22 |     await expect(cellPen).toBeVisible();
  23 |     await page.keyboard.press('Control+z');
  24 |     await expect(cellItem).toBeVisible();
  25 |   });
  26 | });
```