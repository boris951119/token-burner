# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-5-1-1_sort_by_Sales_ascending_persists_after_refresh.spec.ts >> REQ-5-1-1 Sort a Data Range by a Specified Column >> sort by Sales ascending persists after refresh
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-5-1-1_sort_by_Sales_ascending_persists_after_refresh.spec.ts:4:7

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
  4  |   test('sort by Sales ascending persists after refresh', async ({ page }) => {
  5  |     await page.goto('/');
  6  | 
  7  |     // Open the workbook from the home page
  8  |     const workbookLink = page.getByRole('link', { name: /Q3 Sales/i });
> 9  |     await expect(workbookLink).toBeVisible();
     |                                ^ Error: expect(locator).toBeVisible() failed
  10 |     await workbookLink.click();
  11 | 
  12 |     // Wait for the spreadsheet editor to be visible
  13 |     const nameBox = page.getByRole('textbox').first();
  14 |     await expect(nameBox).toBeVisible();
  15 | 
  16 |     // Select the seeded range A1:C6 via the name box
  17 |     await nameBox.fill('A1:C6');
  18 |     await nameBox.press('Enter');
  19 | 
  20 |     // Open the Data menu and choose Sort range
  21 |     await page.getByRole('button', { name: /Data/i }).click();
  22 |     await page.getByRole('menuitem', { name: /Sort range/i }).click();
  23 | 
  24 |     const dialog = page.getByRole('dialog', { name: /Sort range/i });
  25 |     await expect(dialog).toBeVisible();
  26 | 
  27 |     // Configure sort: by Sales ascending, first row is header
  28 |     await dialog.getByRole('combobox', { name: /Sort by/i }).click();
  29 |     await page.getByRole('option', { name: /Sales/i }).click();
  30 | 
  31 |     await dialog.getByRole('combobox', { name: /Order/i }).click();
  32 |     await page.getByRole('option', { name: /Ascending/i }).click();
  33 | 
  34 |     await dialog.getByRole('checkbox', { name: /Data has header row/i }).check();
  35 | 
  36 |     await dialog.getByRole('button', { name: /Sort/i }).click();
  37 |     await expect(dialog).toBeHidden();
  38 | 
  39 |     // Collect rows that contain seeded data
  40 |     const dataRows = page.getByRole('row').filter({ hasText: /East|North|South/i });
  41 |     await expect(dataRows.first()).toBeVisible();
  42 |     const rowTexts = await dataRows.allTextContents();
  43 | 
  44 |     const southIndex = rowTexts.findIndex((t) => /South/i.test(t) && /700/i.test(t));
  45 |     const eastIndex = rowTexts.findIndex((t) => /East/i.test(t) && /1200/i.test(t));
  46 |     expect(southIndex).toBeGreaterThanOrEqual(0);
  47 |     expect(eastIndex).toBeGreaterThanOrEqual(0);
  48 |     expect(southIndex).toBeLessThan(eastIndex);
  49 | 
  50 |     // Header row must remain the first row and contain Region/Sales/Status
  51 |     const allRows = page.getByRole('row');
  52 |     const allRowTexts = await allRows.allTextContents();
  53 |     expect(allRowTexts[0]).toMatch(/Region/i);
  54 |     expect(allRowTexts[0]).toMatch(/Sales/i);
  55 |     expect(allRowTexts[0]).toMatch(/Status/i);
  56 | 
  57 |     // Refresh and verify persistence
  58 |     await page.reload();
  59 |     await expect(page.getByRole('textbox').first()).toBeVisible();
  60 | 
  61 |     const dataRowsAfterReload = page.getByRole('row').filter({ hasText: /East|North|South/i });
  62 |     await expect(dataRowsAfterReload.first()).toBeVisible();
  63 |     const rowTextsAfterReload = await dataRowsAfterReload.allTextContents();
  64 | 
  65 |     const southIndexAfter = rowTextsAfterReload.findIndex((t) => /South/i.test(t) && /700/i.test(t));
  66 |     const eastIndexAfter = rowTextsAfterReload.findIndex((t) => /East/i.test(t) && /1200/i.test(t));
  67 |     expect(southIndexAfter).toBeGreaterThanOrEqual(0);
  68 |     expect(eastIndexAfter).toBeGreaterThanOrEqual(0);
  69 |     expect(southIndexAfter).toBeLessThan(eastIndexAfter);
  70 |   });
  71 | });
```