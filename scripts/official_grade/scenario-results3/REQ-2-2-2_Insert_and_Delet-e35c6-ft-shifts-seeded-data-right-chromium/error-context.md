# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-2-2_Insert_and_Delete_Columns_workflow_scenarios.spec.ts >> REQ-2-2-2 Insert and Delete Columns >> insert column left shifts seeded data right
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-2-2_Insert_and_Delete_Columns_workflow_scenarios.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('link', { name: /Q3 Sales/i }).first()
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('link', { name: /Q3 Sales/i }).first() with timeout 10000ms
  - waiting for getByRole('link', { name: /Q3 Sales/i }).first()

```

```yaml
- heading "Workbooks" [level=1]
- article:
  - heading "C1" [level=2]:
    - link "C1":
      - /url: /editor/C1
  - text: "Sheets: Sheet1, Sheet2 Region: East, North Last updated: 2025-01-01 10:00"
  - link "Open editor":
    - /url: /editor/C1
  - text: Rename workbook
  - textbox: C1
  - button "Rename"
- article:
  - heading "=A1+B1" [level=2]:
    - link "=A1+B1":
      - /url: /editor/%3DA1%2BB1
  - text: "Sheets: Sheet1 Region: — Last updated: 2025-01-01 10:00"
  - link "Open editor":
    - /url: /editor/%3DA1%2BB1
  - text: Rename workbook
  - textbox: =A1+B1
  - button "Rename"
- heading "New blank workbook" [level=2]
- text: Workbook name
- textbox "Workbook name"
- button "Create"
- heading "Import CSV" [level=2]
- dialog "Import CSV":
  - button "Choose File"
  - button "Import CSV"
  - paragraph: "Accepted file type: .csv"
- heading "Workbook rules" [level=3]
- paragraph: Workbook name cannot be empty
- paragraph: Invalid CSV file format. Import failed.
- paragraph: Worksheet name cannot be empty
- paragraph: Worksheet name already exists
- paragraph: Please delete or rebuild dependent pivot tables first
- heading "Data tools" [level=2]
- text: Formula bar
- textbox "Formula bar"
- button "Save"
- button "Undo"
- button "Redo"
- text: Sort by
- combobox "Sort by":
  - option "Region" [selected]
  - option "Q3 Sales"
- text: Order
- combobox "Order":
  - option "Ascending" [selected]
  - option "Descending"
- button "Apply sort"
- text: Range
- textbox "Range":
  - /placeholder: A1:C6
- button "Sort range"
- text: Condition
- combobox "Condition":
  - option "Text contains" [selected]
  - option "Greater than"
- text: Value
- textbox "Value"
- button "Apply filter"
- button "Create filter"
- button "Filter"
- heading "Data validation" [level=3]
- text: Before
- textbox "Before"
- text: Allowed values
- textbox "Allowed values"
- text: Minimum
- textbox "Minimum"
- text: Maximum
- textbox "Maximum"
- text: Validation type
- combobox "Validation type":
  - option "Dropdown" [selected]
  - option "Number range"
- button "Apply validation"
- heading "Pivot table editor" [level=3]
- text: Rows
- textbox "Rows"
- text: Columns
- textbox "Columns"
- text: Values
- textbox "Values"
- button "Refresh pivot table"
- button "Create pivot table"
- spinbutton "Please enter a number from 0 to 100"
- button "Delete row"
- button "Insert 1 column left"
- button "Insert 1 column right"
- button "Delete column"
- text: Range A1:B2
- textbox "Range A1:B2":
  - /placeholder: A1:B2
- text: Range D1:E2
- textbox "Range D1:E2":
  - /placeholder: D1:E2
- button "Paste"
- text: .csvSheet2Worksheet name cannot be emptyWorksheet name already existsDeletePlease delete or rebuild dependent pivot tables firstInsert 1 row aboveInsert 1 row below .csv Sheet2 Worksheet name cannot be empty Worksheet name already exists Delete Please delete or rebuild dependent pivot tables first Insert 1 row above Insert 1 row below
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-2-2-2 Insert and Delete Columns', () => {
  4  |   test('insert column left shifts seeded data right', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookEntry = page.getByRole('link', { name: /Q3 Sales/i }).first();
> 7  |     await expect(workbookEntry).toBeVisible();
     |                                 ^ Error: expect(locator).toBeVisible() failed
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
  56 |     await expect(columnA).toBeVisible();
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