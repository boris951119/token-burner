# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-3-1-2_Paste_2D_data_via_context_menu_updates_rectangle.spec.ts >> REQ-3-1-2 Paste Two-Dimensional Table Data >> paste 2D data via context menu updates rectangle
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-3-1-2_Paste_2D_data_via_context_menu_updates_rectangle.spec.ts:4:7

# Error details

```
Error: page.evaluate: NotAllowedError: Failed to execute 'writeText' on 'Clipboard': Write permission denied.
```

# Page snapshot

```yaml
- generic [ref=f1e1]:
  - heading "Q3 Sales" [level=1] [ref=f1e2]
  - generic [ref=f1e3]: "Region: East, North"
  - generic [ref=f1e4]:
    - link "Sheet1" [ref=f1e5] [cursor=pointer]:
      - /url: /editor/Q3%20Sales?sheet=Sheet1
    - link "Sheet2" [ref=f1e6] [cursor=pointer]:
      - /url: /editor/Q3%20Sales?sheet=Sheet2
  - generic [ref=f1e7]:
    - text: Formula bar
    - textbox "Formula bar" [active] [ref=f1e8]: D1
  - table [ref=f1e10]:
    - rowgroup [ref=f1e11]:
      - row [ref=f1e12]:
        - cell [ref=f1e13]:
          - text: "1"
          - button "Delete row 1" [ref=f1e15]: Delete row
          - button "Insert row above" [ref=f1e17]
          - button "Insert row below" [ref=f1e19]
        - rowheader "Region" [ref=f1e20]
        - columnheader "Q3 Sales" [ref=f1e21]
      - row [ref=f1e22]:
        - cell [ref=f1e23]:
          - text: "2"
          - button "Delete row 2" [ref=f1e25]: Delete row
          - button "Insert row above" [ref=f1e27]
          - button "Insert row below" [ref=f1e29]
        - cell "East" [ref=f1e30]
        - cell "100" [ref=f1e31]
      - row [ref=f1e32]:
        - cell [ref=f1e33]:
          - text: "3"
          - button "Delete row 3" [ref=f1e35]: Delete row
          - button "Insert row above" [ref=f1e37]
          - button "Insert row below" [ref=f1e39]
        - cell "North" [ref=f1e40]
        - cell "200" [ref=f1e41]
  - generic [ref=f1e42]:
    - button "Insert 1 column left" [ref=f1e44]
    - button "Insert 1 column right" [ref=f1e46]
    - button "Delete column" [ref=f1e48]
  - generic [ref=f1e49]:
    - button "Add worksheet" [ref=f1e51]
    - button "Export CSV" [ref=f1e53]
    - button "Delete worksheet" [ref=f1e55]
  - generic [ref=f1e56]:
    - heading "Rename worksheet" [level=3] [ref=f1e57]
    - generic [ref=f1e58]:
      - textbox "New name" [ref=f1e59]
      - button "Rename" [ref=f1e60]
    - link "Download current sheet" [ref=f1e61] [cursor=pointer]:
      - /url: /editor/Q3%20Sales/download-csv?sheet=Sheet1
  - generic [ref=f1e62]:
    - heading "Pivot table editor" [level=3] [ref=f1e63]
    - generic [ref=f1e64]:
      - generic [ref=f1e65]:
        - text: Rows
        - textbox "Rows" [ref=f1e66]
      - generic [ref=f1e67]:
        - text: Columns
        - textbox "Columns" [ref=f1e68]
      - generic [ref=f1e69]:
        - text: Values
        - textbox "Values" [ref=f1e70]
      - button "Refresh pivot table" [ref=f1e71]
      - button "Create pivot table" [ref=f1e72]
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-3-1-2 Paste Two-Dimensional Table Data', () => {
  4  |   test('paste 2D data via context menu updates rectangle', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3 Sales/i }).first().click();
  7  | 
  8  |     const nameBox = page.getByRole('textbox').first();
  9  |     await expect(nameBox).toBeVisible();
  10 |     await nameBox.fill('D1');
  11 |     await page.keyboard.press('Enter');
  12 | 
> 13 |     await page.evaluate(() => navigator.clipboard.writeText('East\t1200\nNorth\t800'));
     |                ^ Error: page.evaluate: NotAllowedError: Failed to execute 'writeText' on 'Clipboard': Write permission denied.
  14 | 
  15 |     await page.getByRole('gridcell', { name: /D1/i }).click({ button: 'right' });
  16 |     await page.getByRole('menuitem', { name: /Paste/i }).click();
  17 | 
  18 |     await expect(page.getByText(/East/i).first()).toBeVisible();
  19 |     await expect(page.getByText(/1200/i).first()).toBeVisible();
  20 |     await expect(page.getByText(/North/i).first()).toBeVisible();
  21 |     await expect(page.getByText(/800/i).first()).toBeVisible();
  22 |     await page.reload();
  23 |     await expect(page.getByText(/East/i).first()).toBeVisible();
  24 |   });
  25 | });
```