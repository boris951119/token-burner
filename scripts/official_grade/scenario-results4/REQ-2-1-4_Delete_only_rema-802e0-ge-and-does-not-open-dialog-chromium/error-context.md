# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-1-4_Delete_only_remaining_worksheet_shows_at_least_one.spec.ts >> REQ-2-1-4 Delete a Worksheet >> deleting last worksheet shows message and does not open dialog
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-1-4_Delete_only_remaining_worksheet_shows_at_least_one.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('menuitem', { name: /^Delete$/i }).first()

```

# Page snapshot

```yaml
- generic [ref=f1e1]:
  - heading "Q3 Sales" [level=1] [ref=f1e2]
  - generic [ref=f1e3]: "Region: East, North"
  - tablist [ref=f1e5]:
    - tab "Sheet1" [selected] [ref=f1e6] [cursor=pointer]
    - tab "Sheet2" [active] [ref=f1e7] [cursor=pointer]
  - generic [ref=f1e8]:
    - text: Formula bar
    - textbox "Formula bar" [ref=f1e9]
  - grid "Worksheet grid" [ref=f1e11]:
    - rowgroup [ref=f1e12]:
      - row [ref=f1e13]:
        - text: "1"
        - button "Delete row 1" [ref=f1e15]: Delete row
        - button "Insert row above" [ref=f1e17]
        - button "Insert row below" [ref=f1e19]
        - gridcell "A1" [ref=f1e20]: Region
        - gridcell "B1" [ref=f1e21]: Q3 Sales
      - row [ref=f1e22]:
        - text: "2"
        - button "Delete row 2" [ref=f1e24]: Delete row
        - button "Insert row above" [ref=f1e26]
        - button "Insert row below" [ref=f1e28]
        - gridcell "A2" [ref=f1e29]: East
        - gridcell "B2" [ref=f1e30]: "100"
      - row [ref=f1e31]:
        - text: "3"
        - button "Delete row 3" [ref=f1e33]: Delete row
        - button "Insert row above" [ref=f1e35]
        - button "Insert row below" [ref=f1e37]
        - gridcell "A3" [ref=f1e38]: North
        - gridcell "B3" [ref=f1e39]: "200"
  - generic [ref=f1e40]:
    - button "Insert 1 column left" [ref=f1e42]
    - button "Insert 1 column right" [ref=f1e44]
    - button "Delete column" [ref=f1e46]
  - generic [ref=f1e47]:
    - button "Add worksheet" [ref=f1e49]
    - button "Export CSV" [ref=f1e51]
    - button "Delete worksheet" [ref=f1e53]
  - generic [ref=f1e54]:
    - heading "Rename worksheet" [level=3] [ref=f1e55]
    - generic [ref=f1e56]:
      - textbox "New name" [ref=f1e57]
      - button "Rename" [ref=f1e58]
    - link "Download current sheet" [ref=f1e59] [cursor=pointer]:
      - /url: /editor/Q3%20Sales/download-csv?sheet=Sheet1
  - generic [ref=f1e60]:
    - heading "Pivot table editor" [level=3] [ref=f1e61]
    - generic [ref=f1e62]:
      - generic [ref=f1e63]:
        - text: Rows
        - textbox "Rows" [ref=f1e64]
      - generic [ref=f1e65]:
        - text: Columns
        - textbox "Columns" [ref=f1e66]
      - generic [ref=f1e67]:
        - text: Values
        - textbox "Values" [ref=f1e68]
      - button "Refresh pivot table" [ref=f1e69]
      - button "Create pivot table" [ref=f1e70]
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-2-1-4 Delete a Worksheet', () => {
  4  |   test('deleting last worksheet shows message and does not open dialog', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3 Sales/i }).click();
  7  |     await expect(page.getByRole('tab', { name: /^Sheet1$/i })).toBeVisible();
  8  |     await expect(page.getByRole('tab', { name: /^Sheet2$/i })).toBeVisible();
  9  | 
  10 |     const sheet2Tab = page.getByRole('tab', { name: /^Sheet2$/i });
  11 |     await sheet2Tab.click({ button: 'right' });
> 12 |     await page.getByRole('menuitem', { name: /^Delete$/i }).first().click();
     |                                                                     ^ Error: locator.click: Test timeout of 60000ms exceeded.
  13 |     const deleteDialog = page.getByRole('dialog', { name: /^Delete worksheet$/i });
  14 |     await expect(deleteDialog).toBeVisible();
  15 |     await deleteDialog.getByRole('button', { name: /^Delete worksheet$/i }).click();
  16 |     await expect(page.getByRole('tab', { name: /^Sheet2$/i })).toHaveCount(0);
  17 |     await expect(page.getByRole('tab', { name: /^Sheet1$/i })).toBeVisible();
  18 | 
  19 |     const sheet1Tab = page.getByRole('tab', { name: /^Sheet1$/i });
  20 |     await sheet1Tab.click({ button: 'right' });
  21 |     const deleteMenuItem = page.getByRole('menuitem', { name: /^Delete$/i }).first();
  22 |     await expect(deleteMenuItem).toBeVisible();
  23 |     await deleteMenuItem.click();
  24 | 
  25 |     await expect(page.getByRole('dialog', { name: /^Delete worksheet$/i })).toHaveCount(0);
  26 |     const message = page.getByRole('alert')
  27 |       .or(page.getByRole('status'))
  28 |       .or(page.getByText(/A workbook must contain at least one worksheet/i))
  29 |       .first();
  30 |     await expect(message).toBeVisible();
  31 |     await expect(page.getByRole('tab', { name: /^Sheet1$/i })).toBeVisible();
  32 |   });
  33 | });
```