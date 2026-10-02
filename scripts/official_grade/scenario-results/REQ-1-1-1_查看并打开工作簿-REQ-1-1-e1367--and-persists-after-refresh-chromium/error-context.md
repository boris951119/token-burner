# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-1-1-1_查看并打开工作簿.spec.ts >> REQ-1-1-1 View and Open a Workbook >> opens seeded workbook Q3 Sales and persists after refresh
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-1-1-1_查看并打开工作簿.spec.ts:4:7

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
  3  | test.describe('REQ-1-1-1 View and Open a Workbook', () => {
  4  |   test('opens seeded workbook Q3 Sales and persists after refresh', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookLink = page.getByRole('link', { name: /Q3 Sales/i });
  7  |     await expect(workbookLink).toBeVisible();
  8  |     await workbookLink.click();
  9  | 
  10 |     await expect(page.getByText(/Q3 Sales/i).first()).toBeVisible();
  11 | 
  12 |     const sheetTab = page.getByRole('tab', { name: /Sheet1/i });
> 13 |     await expect(sheetTab).toBeVisible();
     |                            ^ Error: expect(locator).toBeVisible() failed
  14 |     await expect(sheetTab).toHaveAttribute('aria-selected', 'true');
  15 | 
  16 |     const grid = page.getByRole('grid', { name: /Worksheet grid/i });
  17 |     await expect(grid).toBeVisible();
  18 |     await expect(grid).toHaveAttribute('aria-multiselectable', 'true');
  19 | 
  20 |     const cellA1 = page.getByRole('gridcell', { name: /A1/i });
  21 |     await expect(cellA1).toBeVisible();
  22 |     await expect(cellA1).toHaveText(/Region/i);
  23 | 
  24 |     await page.reload();
  25 |     await expect(page.getByText(/Q3 Sales/i).first()).toBeVisible();
  26 |     await expect(page.getByRole('tab', { name: /Sheet1/i })).toHaveAttribute('aria-selected', 'true');
  27 |     await expect(page.getByRole('grid', { name: /Worksheet grid/i })).toBeVisible();
  28 |     await expect(page.getByRole('gridcell', { name: /A1/i })).toHaveText(/Region/i);
  29 |   });
  30 | });
```