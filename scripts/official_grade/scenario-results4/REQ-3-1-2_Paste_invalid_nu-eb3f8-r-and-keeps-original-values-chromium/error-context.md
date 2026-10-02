# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-3-1-2_Paste_invalid_number_shows_validation_error.spec.ts >> REQ-3-1-2 Paste Two-Dimensional Table Data >> paste invalid number shows validation error and keeps original values
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-3-1-2_Paste_invalid_number_shows_validation_error.spec.ts:4:7

# Error details

```
Error: page.evaluate: NotAllowedError: Failed to execute 'writeText' on 'Clipboard': Write permission denied.
```

# Page snapshot

```yaml
- generic [ref=f1e1]:
  - heading "Q3 Sales" [level=1] [ref=f1e2]
  - generic [ref=f1e3]: "Region: East, North"
  - tablist [ref=f1e5]:
    - tab "Sheet1" [selected] [ref=f1e6] [cursor=pointer]
    - tab "Sheet2" [ref=f1e7] [cursor=pointer]
  - generic [ref=f1e8]:
    - text: Formula bar
    - textbox "Formula bar" [active] [ref=f1e9]: D1
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
  3  | test.describe('REQ-3-1-2 Paste Two-Dimensional Table Data', () => {
  4  |   test('paste invalid number shows validation error and keeps original values', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3 Sales/i }).first().click();
  7  | 
  8  |     const nameBox = page.getByRole('textbox').first();
  9  |     await expect(nameBox).toBeVisible();
  10 |     await nameBox.fill('D1');
  11 |     await page.keyboard.press('Enter');
  12 | 
> 13 |     await page.evaluate(() => navigator.clipboard.writeText('101\t1200'));
     |                ^ Error: page.evaluate: NotAllowedError: Failed to execute 'writeText' on 'Clipboard': Write permission denied.
  14 | 
  15 |     await page.getByRole('gridcell', { name: /D1/i }).click({ button: 'right' });
  16 |     await page.getByRole('menuitem', { name: /Paste/i }).click();
  17 | 
  18 |     await expect(page.getByRole('alert').or(page.getByRole('status')).or(page.getByText(/Please enter a number from 0 to 100/i)).first()).toBeVisible();
  19 |     await expect(page.getByText(/101/i)).toHaveCount(0);
  20 |   });
  21 | });
```