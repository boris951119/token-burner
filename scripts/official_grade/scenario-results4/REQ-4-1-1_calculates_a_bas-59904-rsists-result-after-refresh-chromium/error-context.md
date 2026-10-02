# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-4-1-1_calculates_a_basic_formula_and_persists_result_aft.spec.ts >> REQ-4-1-1 Calculate Basic Expressions and Aggregate Functions >> calculates a basic formula and persists result after refresh
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-4-1-1_calculates_a_basic_formula_and_persists_result_aft.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText(/^5$/i).first()
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByText(/^5$/i).first() with timeout 10000ms
  - waiting for getByText(/^5$/i).first()

```

```yaml
- heading "Workbooks" [level=1]
- text: Create
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
  3  | test.describe('REQ-4-1-1 Calculate Basic Expressions and Aggregate Functions', () => {
  4  |   test('calculates a basic formula and persists result after refresh', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookEntry = page.getByRole('article').filter({ has: page.getByText(/Q3 Sales/i) }).first()
  7  |       .or(page.getByText(/Q3 Sales/i).first()).first();
  8  |     await workbookEntry.click();
  9  | 
  10 |     const nameBox = page.getByLabel(/^A1$/i).or(page.getByPlaceholder(/^A1$/i)).or(page.getByRole('textbox')).or(page.getByRole('searchbox')).first();
  11 |     const formulaBar = page.getByLabel(/fx/i).or(page.getByPlaceholder(/fx/i)).or(page.getByRole('textbox')).or(page.getByRole('searchbox')).nth(1);
  12 | 
  13 |     await nameBox.click();
  14 |     await nameBox.fill('C1');
  15 |     await nameBox.press('Enter');
  16 |     await formulaBar.click();
  17 |     await formulaBar.fill('=A1+B1');
  18 |     await formulaBar.press('Enter');
  19 | 
> 20 |     await expect(page.getByText(/^5$/i).first()).toBeVisible();
     |                                                  ^ Error: expect(locator).toBeVisible() failed
  21 |     await expect(formulaBar).toHaveValue('=A1+B1');
  22 | 
  23 |     await page.goto('/');
  24 |     await workbookEntry.click();
  25 |     await nameBox.click();
  26 |     await nameBox.fill('C1');
  27 |     await nameBox.press('Enter');
  28 |     await expect(page.getByText(/^5$/i).first()).toBeVisible();
  29 |     await expect(formulaBar).toHaveValue('=A1+B1');
  30 |   });
  31 | });
```