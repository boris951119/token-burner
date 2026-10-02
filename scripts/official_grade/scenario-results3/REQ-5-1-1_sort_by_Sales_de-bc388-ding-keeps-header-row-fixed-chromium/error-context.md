# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-5-1-1_sort_by_Sales_descending_keeps_header_row_fixed.spec.ts >> REQ-5-1-1 Sort a Data Range by a Specified Column >> sort by Sales descending keeps header row fixed
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-5-1-1_sort_by_Sales_descending_keeps_header_row_fixed.spec.ts:4:7

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
  3  | test.describe('REQ-5-1-1 Sort a Data Range by a Specified Column', () => {
  4  |   test('sort by Sales descending keeps header row fixed', async ({ page }) => {
  5  |     await page.goto('/');
  6  | 
  7  |     const workbookLink = page.getByRole('link', { name: /Q3 Sales/i });
> 8  |     await expect(workbookLink).toBeVisible();
     |                                ^ Error: expect(locator).toBeVisible() failed
  9  |     await workbookLink.click();
  10 | 
  11 |     const nameBox = page.getByRole('textbox').first();
  12 |     await expect(nameBox).toBeVisible();
  13 | 
  14 |     await nameBox.fill('A1:C6');
  15 |     await nameBox.press('Enter');
  16 | 
  17 |     await page.getByRole('button', { name: /Data/i }).click();
  18 |     await page.getByRole('menuitem', { name: /Sort range/i }).click();
  19 | 
  20 |     const dialog = page.getByRole('dialog', { name: /Sort range/i });
  21 |     await expect(dialog).toBeVisible();
  22 | 
  23 |     // Sort by Sales descending
  24 |     await dialog.getByRole('combobox', { name: /Sort by/i }).click();
  25 |     await page.getByRole('option', { name: /Sales/i }).click();
  26 | 
  27 |     await dialog.getByRole('combobox', { name: /Order/i }).click();
  28 |     await page.getByRole('option', { name: /Descending/i }).click();
  29 | 
  30 |     await dialog.getByRole('checkbox', { name: /Data has header row/i }).check();
  31 | 
  32 |     await dialog.getByRole('button', { name: /Sort/i }).click();
  33 |     await expect(dialog).toBeHidden();
  34 | 
  35 |     // Collect rows with seeded data
  36 |     const dataRows = page.getByRole('row').filter({ hasText: /East|North|South/i });
  37 |     await expect(dataRows.first()).toBeVisible();
  38 |     const rowTexts = await dataRows.allTextContents();
  39 | 
  40 |     const eastIndex = rowTexts.findIndex((t) => /East/i.test(t) && /1200/i.test(t));
  41 |     const northIndex = rowTexts.findIndex((t) => /North/i.test(t) && /800/i.test(t));
  42 |     const southIndex = rowTexts.findIndex((t) => /South/i.test(t) && /700/i.test(t));
  43 | 
  44 |     expect(eastIndex).toBeGreaterThanOrEqual(0);
  45 |     expect(northIndex).toBeGreaterThanOrEqual(0);
  46 |     expect(southIndex).toBeGreaterThanOrEqual(0);
  47 | 
  48 |     // Descending order: East (1200) > North (800) > South (700)
  49 |     expect(eastIndex).toBeLessThan(northIndex);
  50 |     expect(northIndex).toBeLessThan(southIndex);
  51 | 
  52 |     // Header row must still be first and contain the header labels
  53 |     const allRows = page.getByRole('row');
  54 |     const allRowTexts = await allRows.allTextContents();
  55 |     expect(allRowTexts[0]).toMatch(/Region/i);
  56 |     expect(allRowTexts[0]).toMatch(/Sales/i);
  57 |     expect(allRowTexts[0]).toMatch(/Status/i);
  58 |   });
  59 | });
```