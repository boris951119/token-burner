# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-3-2-2_New_modification_after_undo_disables_redo.spec.ts >> REQ-3-2-2 Undo and Redo Recent Operations >> new modification after undo disables redo
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-3-2-2_New_modification_after_undo_disables_redo.spec.ts:4:7

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
  4  |   test('new modification after undo disables redo', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByText(/Q3\s+Sales/i).first().click();
  7  |     const cellItem = page.getByRole('cell', { name: /^Item$/i }).or(page.getByRole('gridcell', { name: /^Item$/i })).first();
> 8  |     await expect(cellItem).toBeVisible();
     |                            ^ Error: expect(locator).toBeVisible() failed
  9  |     await cellItem.dblclick();
  10 |     await page.keyboard.type('Changed');
  11 |     await page.keyboard.press('Enter');
  12 |     await page.getByRole('button', { name: 'Undo' }).click();
  13 |     const redoButton = page.getByRole('button', { name: 'Redo' });
  14 |     await expect(redoButton).toBeEnabled();
  15 |     await cellItem.dblclick();
  16 |     await page.keyboard.type('New Value');
  17 |     await page.keyboard.press('Enter');
  18 |     await expect(redoButton).toBeDisabled();
  19 |   });
  20 | });
```