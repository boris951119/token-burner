# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-1-2-2_重命名工作簿.spec.ts >> REQ-1-2-2 Rename a Workbook >> rejects empty workbook name
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-1-2-2_重命名工作簿.spec.ts:32:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('link', { name: /Q3 Sales/i })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('link', { name: /Q3 Sales/i }) with timeout 10000ms
  - waiting for getByRole('link', { name: /Q3 Sales/i })

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
  3  | test.describe('REQ-1-2-2 Rename a Workbook', () => {
  4  |   test('renames workbook and persists new name on home page', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookLink = page.getByRole('link', { name: /Q3 Sales/i });
  7  |     await expect(workbookLink).toBeVisible();
  8  |     await workbookLink.click();
  9  | 
  10 |     const renameButton = page.getByRole('button', { name: /Rename workbook/i });
  11 |     await expect(renameButton).toBeVisible();
  12 |     await renameButton.click();
  13 | 
  14 |     const nameInput = page.getByLabel(/Workbook name/i);
  15 |     await expect(nameInput).toBeVisible();
  16 |     await nameInput.fill('Renamed Sheet');
  17 | 
  18 |     const saveButton = page.getByRole('button', { name: /Save/i });
  19 |     await expect(saveButton).toBeVisible();
  20 |     await saveButton.click();
  21 | 
  22 |     await expect(page.getByText(/Renamed Sheet/i).first()).toBeVisible();
  23 | 
  24 |     await page.goto('/');
  25 |     const renamedLink = page.getByRole('link', { name: /Renamed Sheet/i });
  26 |     await expect(renamedLink).toBeVisible();
  27 | 
  28 |     await renamedLink.click();
  29 |     await expect(page.getByText(/Renamed Sheet/i).first()).toBeVisible();
  30 |   });
  31 | 
  32 |   test('rejects empty workbook name', async ({ page }) => {
  33 |     await page.goto('/');
  34 |     const workbookLink = page.getByRole('link', { name: /Q3 Sales/i });
> 35 |     await expect(workbookLink).toBeVisible();
     |                                ^ Error: expect(locator).toBeVisible() failed
  36 |     await workbookLink.click();
  37 | 
  38 |     const renameButton = page.getByRole('button', { name: /Rename workbook/i });
  39 |     await expect(renameButton).toBeVisible();
  40 |     await renameButton.click();
  41 | 
  42 |     const nameInput = page.getByLabel(/Workbook name/i);
  43 |     await expect(nameInput).toBeVisible();
  44 |     await nameInput.fill('');
  45 | 
  46 |     const saveButton = page.getByRole('button', { name: /Save/i });
  47 |     await expect(saveButton).toBeVisible();
  48 |     await saveButton.click();
  49 | 
  50 |     await expect(page.getByText(/Workbook name cannot be empty/i).first()).toBeVisible();
  51 |     await expect(page.getByText(/Q3 Sales/i).first()).toBeVisible();
  52 |   });
  53 | });
```