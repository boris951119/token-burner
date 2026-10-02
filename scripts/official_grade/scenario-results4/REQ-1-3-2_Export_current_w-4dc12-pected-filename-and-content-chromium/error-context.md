# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-1-3-2_Export_current_worksheet_as_CSV_with_expected_file.spec.ts >> REQ-1-3-2 Export the Current Worksheet as CSV >> exports current worksheet as CSV with expected filename and content
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-1-3-2_Export_current_worksheet_as_CSV_with_expected_file.spec.ts:5:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: page.waitForEvent: Test timeout of 60000ms exceeded.
=========================== logs ===========================
waiting for event "download"
============================================================
```

# Page snapshot

```yaml
- generic [active] [ref=f2e1]:
  - heading "Q3 Sales" [level=1] [ref=f2e2]
  - generic [ref=f2e3]: Export CSV
  - generic [ref=f2e4]: Sheet1
  - generic [ref=f2e5]: "Region: East, North"
  - tablist [ref=f2e7]:
    - tab "Sheet1" [selected] [ref=f2e8] [cursor=pointer]
    - tab "Sheet2" [ref=f2e9] [cursor=pointer]
  - generic [ref=f2e10]:
    - text: Formula bar
    - textbox "Formula bar" [ref=f2e11]
  - grid "Worksheet grid" [ref=f2e13]:
    - rowgroup [ref=f2e14]:
      - row [ref=f2e15]:
        - text: "1"
        - button "Delete row 1" [ref=f2e17]: Delete row
        - button "Insert row above" [ref=f2e19]
        - button "Insert row below" [ref=f2e21]
        - gridcell "A1" [ref=f2e22]: Region
        - gridcell "B1" [ref=f2e23]: Q3 Sales
      - row [ref=f2e24]:
        - text: "2"
        - button "Delete row 2" [ref=f2e26]: Delete row
        - button "Insert row above" [ref=f2e28]
        - button "Insert row below" [ref=f2e30]
        - gridcell "A2" [ref=f2e31]: East
        - gridcell "B2" [ref=f2e32]: "100"
      - row [ref=f2e33]:
        - text: "3"
        - button "Delete row 3" [ref=f2e35]: Delete row
        - button "Insert row above" [ref=f2e37]
        - button "Insert row below" [ref=f2e39]
        - gridcell "A3" [ref=f2e40]: North
        - gridcell "B3" [ref=f2e41]: "200"
  - generic [ref=f2e42]:
    - button "Insert 1 column left" [ref=f2e44]
    - button "Insert 1 column right" [ref=f2e46]
    - button "Delete column" [ref=f2e48]
  - generic [ref=f2e49]:
    - button "Add worksheet" [ref=f2e51]
    - button "Export CSV" [ref=f2e53]
    - button "Delete worksheet" [ref=f2e55]
  - generic [ref=f2e56]:
    - heading "Rename worksheet" [level=3] [ref=f2e57]
    - generic [ref=f2e58]:
      - textbox "New name" [ref=f2e59]
      - button "Rename" [ref=f2e60]
    - link "Download current sheet" [ref=f2e61] [cursor=pointer]:
      - /url: /editor/Q3%20Sales/download-csv?sheet=Sheet1
  - generic [ref=f2e62]:
    - heading "Pivot table editor" [level=3] [ref=f2e63]
    - generic [ref=f2e64]:
      - generic [ref=f2e65]:
        - text: Rows
        - textbox "Rows" [ref=f2e66]
      - generic [ref=f2e67]:
        - text: Columns
        - textbox "Columns" [ref=f2e68]
      - generic [ref=f2e69]:
        - text: Values
        - textbox "Values" [ref=f2e70]
      - button "Refresh pivot table" [ref=f2e71]
      - button "Create pivot table" [ref=f2e72]
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
  10 |     await expect(grid).toBeVisible();
> 11 |     const downloadPromise = page.waitForEvent('download');
     |                                  ^ Error: page.waitForEvent: Test timeout of 60000ms exceeded.
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