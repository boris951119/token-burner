# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2.1_云端硬盘主页-新建菜单包含GoogleSheets.spec.ts >> 云端硬盘主页 >> 新建菜单包含 Google Sheets 并显示 new sheet
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2.1_云端硬盘主页-新建菜单包含GoogleSheets.spec.ts:4:7

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('navigation').or(getByRole('complementary')).first()
Expected pattern: /我的云端硬盘/i
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toContainText" getByRole('navigation').or(getByRole('complementary')).first() with timeout 10000ms
  - waiting for getByRole('navigation').or(getByRole('complementary')).first()

```

```yaml
- heading "Workbooks" [level=1]
- article:
  - heading "Q3 Sales" [level=2]:
    - link "Q3 Sales":
      - /url: /editor/Q3%20Sales
  - text: "Sheets: Sheet1, Sheet2 Region: East, North Last updated: 2025-01-01 10:00"
  - link "Open editor":
    - /url: /editor/Q3%20Sales
  - text: Rename workbook
  - textbox: Q3 Sales
  - button "Rename"
- heading "New blank workbook" [level=2]
- text: Workbook name
- textbox "Workbook name"
- button "Create"
- heading "Import CSV" [level=2]
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
  3  | test.describe('云端硬盘主页', () => {
  4  |   test('新建菜单包含 Google Sheets 并显示 new sheet', async ({ page }) => {
  5  |     await page.goto('/');
> 6  |     await expect(page.getByRole('navigation').or(page.getByRole('complementary')).first()).toContainText(/我的云端硬盘/i);
     |                                                                                            ^ Error: expect(locator).toContainText(expected) failed
  7  |     await expect(page.getByText(/new sheet/i).first()).toBeVisible();
  8  |     const newBtn = page.getByRole('button', { name: /新建/ }).first();
  9  |     await newBtn.click();
  10 |     const googleSheets = page.getByRole('menuitem', { name: /Google Sheets/i }).or(page.getByText(/Google Sheets/i));
  11 |     await expect(googleSheets.first()).toBeVisible();
  12 |     await googleSheets.first().click();
  13 |     await expect(page.getByText(/^A1$/i).first()).toBeVisible();
  14 |   });
  15 | });
```