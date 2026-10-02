# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-2-2_Insert_and_Delete_Columns_workflow_scenarios.spec.ts >> REQ-2-2-2 Insert and Delete Columns >> column insertion persists after reopening the workbook
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-2-2_Insert_and_Delete_Columns_workflow_scenarios.spec.ts:52:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('columnheader', { name: /^A$/i }).first()
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('columnheader', { name: /^A$/i }).first() with timeout 10000ms
  - waiting for getByRole('columnheader', { name: /^A$/i }).first()

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
  3  | test.describe('REQ-2-2-2 Insert and Delete Columns', () => {
  4  |   test('insert column left shifts seeded data right', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookEntry = page.getByRole('link', { name: /Q3 Sales/i }).first();
  7  |     await expect(workbookEntry).toBeVisible();
  8  |     await workbookEntry.click();
  9  |     const columnA = page.getByRole('columnheader', { name: /^A$/i }).first();
  10 |     await expect(columnA).toBeVisible();
  11 |     await columnA.click({ button: 'right' });
  12 |     const insertLeft = page.getByRole('menuitem', { name: /Insert 1 column left/i }).first();
  13 |     await expect(insertLeft).toBeVisible();
  14 |     await insertLeft.click();
  15 |     const eastCell = page.getByRole('cell', { name: /East/i }).first();
  16 |     await expect(eastCell).toBeVisible();
  17 |     await eastCell.click();
  18 |     const nameBox = page.getByLabel(/名称/i).or(page.getByRole('textbox', { name: /名称/i })).first();
  19 |     await expect(nameBox).toHaveValue(/^B1$/i);
  20 |   });
  21 | 
  22 |   test('insert column right shifts trailing data right', async ({ page }) => {
  23 |     await page.goto('/');
  24 |     await page.getByRole('link', { name: /Q3 Sales/i }).first().click();
  25 |     const columnA = page.getByRole('columnheader', { name: /^A$/i }).first();
  26 |     await expect(columnA).toBeVisible();
  27 |     await columnA.click({ button: 'right' });
  28 |     await page.getByRole('menuitem', { name: /Insert 1 column right/i }).first().click();
  29 |     const valueCell = page.getByRole('cell', { name: /1200/i }).first();
  30 |     await expect(valueCell).toBeVisible();
  31 |     await valueCell.click();
  32 |     const nameBox = page.getByLabel(/名称/i).or(page.getByRole('textbox', { name: /名称/i })).first();
  33 |     await expect(nameBox).toHaveValue(/^C1$/i);
  34 |   });
  35 | 
  36 |   test('delete column removes target data and shifts subsequent columns left', async ({ page }) => {
  37 |     await page.goto('/');
  38 |     await page.getByRole('link', { name: /Q3 Sales/i }).first().click();
  39 |     const columnA = page.getByRole('columnheader', { name: /^A$/i }).first();
  40 |     await expect(columnA).toBeVisible();
  41 |     await columnA.click({ button: 'right' });
  42 |     await page.getByRole('menuitem', { name: /Delete column/i }).first().click();
  43 |     const eastCell = page.getByRole('cell', { name: /East/i });
  44 |     await expect(eastCell).toHaveCount(0);
  45 |     const valueCell = page.getByRole('cell', { name: /1200/i }).first();
  46 |     await expect(valueCell).toBeVisible();
  47 |     await valueCell.click();
  48 |     const nameBox = page.getByLabel(/名称/i).or(page.getByRole('textbox', { name: /名称/i })).first();
  49 |     await expect(nameBox).toHaveValue(/^A1$/i);
  50 |   });
  51 | 
  52 |   test('column insertion persists after reopening the workbook', async ({ page }) => {
  53 |     await page.goto('/');
  54 |     await page.getByRole('link', { name: /Q3 Sales/i }).first().click();
  55 |     const columnA = page.getByRole('columnheader', { name: /^A$/i }).first();
> 56 |     await expect(columnA).toBeVisible();
     |                           ^ Error: expect(locator).toBeVisible() failed
  57 |     await columnA.click({ button: 'right' });
  58 |     await page.getByRole('menuitem', { name: /Insert 1 column left/i }).first().click();
  59 |     const eastCell = page.getByRole('cell', { name: /East/i }).first();
  60 |     await expect(eastCell).toBeVisible();
  61 |     await eastCell.click();
  62 |     const nameBox = page.getByLabel(/名称/i).or(page.getByRole('textbox', { name: /名称/i })).first();
  63 |     await expect(nameBox).toHaveValue(/^B1$/i);
  64 | 
  65 |     await page.goto('/');
  66 |     await page.getByRole('link', { name: /Q3 Sales/i }).first().click();
  67 |     const eastCellAfterReopen = page.getByRole('cell', { name: /East/i }).first();
  68 |     await expect(eastCellAfterReopen).toBeVisible();
  69 |     await eastCellAfterReopen.click();
  70 |     const nameBoxAfterReopen = page.getByLabel(/名称/i).or(page.getByRole('textbox', { name: /名称/i })).first();
  71 |     await expect(nameBoxAfterReopen).toHaveValue(/^B1$/i);
  72 |   });
  73 | });
```