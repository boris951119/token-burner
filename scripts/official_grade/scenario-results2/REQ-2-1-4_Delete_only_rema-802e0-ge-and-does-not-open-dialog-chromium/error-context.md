# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-1-4_Delete_only_remaining_worksheet_shows_at_least_one.spec.ts >> REQ-2-1-4 Delete a Worksheet >> deleting last worksheet shows message and does not open dialog
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-1-4_Delete_only_remaining_worksheet_shows_at_least_one.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('tab', { name: /^Sheet1$/i })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('tab', { name: /^Sheet1$/i }) with timeout 10000ms
  - waiting for getByRole('tab', { name: /^Sheet1$/i })

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
  3  | test.describe('REQ-2-1-4 Delete a Worksheet', () => {
  4  |   test('deleting last worksheet shows message and does not open dialog', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3 Sales/i }).click();
> 7  |     await expect(page.getByRole('tab', { name: /^Sheet1$/i })).toBeVisible();
     |                                                                ^ Error: expect(locator).toBeVisible() failed
  8  |     await expect(page.getByRole('tab', { name: /^Sheet2$/i })).toBeVisible();
  9  | 
  10 |     const sheet2Tab = page.getByRole('tab', { name: /^Sheet2$/i });
  11 |     await sheet2Tab.click({ button: 'right' });
  12 |     await page.getByRole('menuitem', { name: /^Delete$/i }).first().click();
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