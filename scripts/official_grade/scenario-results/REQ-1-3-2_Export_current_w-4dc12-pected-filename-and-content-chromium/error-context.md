# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-1-3-2_Export_current_worksheet_as_CSV_with_expected_file.spec.ts >> REQ-1-3-2 Export the Current Worksheet as CSV >> exports current worksheet as CSV with expected filename and content
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-1-3-2_Export_current_worksheet_as_CSV_with_expected_file.spec.ts:5:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('grid', { name: /Worksheet grid/i })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('grid', { name: /Worksheet grid/i }) with timeout 10000ms
  - waiting for getByRole('grid', { name: /Worksheet grid/i })

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
  2  | import { readFileSync } from 'fs';
  3  | 
  4  | test.describe('REQ-1-3-2 Export the Current Worksheet as CSV', () => {
  5  |   test('exports current worksheet as CSV with expected filename and content', async ({ page }) => {
  6  |     await page.goto('/');
  7  |     const entry = page.getByRole('link', { name: /Q3 Sales/i }).or(page.getByText(/Q3 Sales/i));
  8  |     await entry.first().click();
  9  |     const grid = page.getByRole('grid', { name: /Worksheet grid/i });
> 10 |     await expect(grid).toBeVisible();
     |                        ^ Error: expect(locator).toBeVisible() failed
  11 |     const downloadPromise = page.waitForEvent('download');
  12 |     await page.getByRole('button', { name: /Export CSV/i }).click();
  13 |     const download = await downloadPromise;
  14 |     expect(download.suggestedFilename()).toMatch(/\.csv$/i);
  15 |     const filePath = await download.path();
  16 |     const content = readFileSync(filePath, 'utf-8');
  17 |     expect(content).toContain('Region');
  18 |     await expect(grid).toBeVisible();
  19 |     await expect(page.getByRole('gridcell', { name: 'A1' })).toHaveText(/Region/);
  20 |   });
  21 | });
```