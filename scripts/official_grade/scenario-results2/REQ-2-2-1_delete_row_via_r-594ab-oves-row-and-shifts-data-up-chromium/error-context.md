# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-2-1_delete_row_via_row-number_menu_removes_row_and_shi.spec.ts >> REQ-2-2-1 Insert and Delete Rows >> delete row via row-number menu removes row and shifts data up
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-2-1_delete_row_via_row-number_menu_removes_row_and_shi.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('tab', { name: /Sheet1/i })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('tab', { name: /Sheet1/i }) with timeout 10000ms
  - waiting for getByRole('tab', { name: /Sheet1/i })

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
  3  | test.describe('REQ-2-2-1 Insert and Delete Rows', () => {
  4  |   test('delete row via row-number menu removes row and shifts data up', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3\s+Sales/i }).first().click();
> 7  |     await expect(page.getByRole('tab', { name: /Sheet1/i })).toBeVisible();
     |                                                              ^ Error: expect(locator).toBeVisible() failed
  8  | 
  9  |     const row1 = page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '1', exact: true }) });
  10 |     await expect(row1).toContainText(/East/i);
  11 |     await expect(row1).toContainText(/1200/i);
  12 |     const row2 = page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '2', exact: true }) });
  13 |     await expect(row2).toContainText(/North/i);
  14 |     await expect(row2).toContainText(/800/i);
  15 | 
  16 |     await page.getByRole('rowheader', { name: '1', exact: true }).click({ button: 'right' });
  17 |     await page.getByRole('menuitem', { name: /Delete\s+row/i }).click();
  18 | 
  19 |     const row1After = page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '1', exact: true }) });
  20 |     await expect(row1After).toContainText(/North/i);
  21 |     await expect(row1After).toContainText(/800/i);
  22 |     await expect(row1After).not.toContainText(/East/i);
  23 |     await expect(row1After).not.toContainText(/1200/i);
  24 |   });
  25 | });
```