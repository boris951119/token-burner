# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-1-3_Rename_worksheet_duplicate_name_shows_validation_e.spec.ts >> REQ-2-1-3 Rename a Worksheet >> duplicate name shows validation error and keeps original name
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-1-3_Rename_worksheet_duplicate_name_shows_validation_e.spec.ts:4:7

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
  3  | test.describe('REQ-2-1-3 Rename a Worksheet', () => {
  4  |   test('duplicate name shows validation error and keeps original name', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('link', { name: /Q3 Sales/i }).click();
> 7  |     await expect(page.getByRole('tab', { name: /^Sheet1$/i })).toBeVisible();
     |                                                                ^ Error: expect(locator).toBeVisible() failed
  8  |     await expect(page.getByRole('tab', { name: /^Sheet2$/i })).toBeVisible();
  9  | 
  10 |     const sheet1Tab = page.getByRole('tab', { name: /^Sheet1$/i });
  11 |     await sheet1Tab.click({ button: 'right' });
  12 |     const renameMenuItem = page.getByRole('menuitem', { name: /^Rename$/i }).first();
  13 |     await expect(renameMenuItem).toBeVisible();
  14 |     await renameMenuItem.click();
  15 | 
  16 |     const dialog = page.getByRole('dialog', { name: /^Rename worksheet$/i });
  17 |     await expect(dialog).toBeVisible();
  18 | 
  19 |     const input = dialog.getByLabel(/Worksheet name/i)
  20 |       .or(dialog.getByPlaceholder(/Worksheet name/i))
  21 |       .or(dialog.getByRole('textbox'))
  22 |       .or(dialog.getByRole('searchbox'))
  23 |       .first();
  24 |     await expect(input).toBeVisible();
  25 |     await input.fill('Sheet2');
  26 | 
  27 |     await dialog.getByRole('button', { name: /^Save$/i }).click();
  28 | 
  29 |     const duplicateError = dialog.getByRole('alert')
  30 |       .or(dialog.getByRole('status'))
  31 |       .or(dialog.getByText(/Worksheet name already exists/i))
  32 |       .first();
  33 |     await expect(duplicateError).toBeVisible();
  34 |     await expect(page.getByRole('tab', { name: /^Sheet1$/i })).toBeVisible();
  35 |     await expect(page.getByRole('tab', { name: /^Sheet2$/i })).toBeVisible();
  36 |   });
  37 | });
```