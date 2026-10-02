# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-1-1_REQ-2-1-1_Add_worksheet_creates_SheetN_sequentiall.spec.ts >> REQ-2-1-1 Add a Worksheet >> creates sequential sheet names
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-1-1_REQ-2-1-1_Add_worksheet_creates_SheetN_sequentiall.spec.ts:4:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('tab', { name: /^(Sheet1|工作表) *1$/i }).first()
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('tab', { name: /^(Sheet1|工作表) *1$/i }).first() with timeout 10000ms
  - waiting for getByRole('tab', { name: /^(Sheet1|工作表) *1$/i }).first()

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
  3  | test.describe('REQ-2-1-1 Add a Worksheet', () => {
  4  |   test('creates sequential sheet names', async ({ page }) => {
  5  |     await page.goto('/');
  6  | 
  7  |     const workbookEntry = page
  8  |       .getByRole('article')
  9  |       .filter({ has: page.getByText(/Q3 Sales/i) })
  10 |       .or(page.getByText(/Q3 Sales/i).first());
  11 |     await workbookEntry.first().click();
  12 | 
  13 |     const firstTab = page.getByRole('tab', { name: /^(Sheet1|工作表) *1$/i }).first();
> 14 |     await expect(firstTab).toBeVisible();
     |                            ^ Error: expect(locator).toBeVisible() failed
  15 | 
  16 |     const getMaxSheetNumber = async () => {
  17 |       const texts = await page.getByRole('tab').allTextContents();
  18 |       const numbers = texts.map((text) => {
  19 |         const match = text.match(/(?:Sheet|工作表) *(\d+)/i);
  20 |         return match ? parseInt(match[1], 10) : 0;
  21 |       });
  22 |       return numbers.length > 0 ? Math.max(...numbers) : 0;
  23 |     };
  24 | 
  25 |     const initialMax = await getMaxSheetNumber();
  26 |     const addWorksheetButton = page.getByRole('button', { name: /^Add worksheet$/i });
  27 | 
  28 |     await addWorksheetButton.click();
  29 |     const next1 = initialMax + 1;
  30 |     const tab1 = page.getByRole('tab', { name: new RegExp(`^(Sheet|工作表) *${next1}$`, 'i') }).first();
  31 |     await expect(tab1).toBeVisible();
  32 | 
  33 |     await addWorksheetButton.click();
  34 |     const next2 = initialMax + 2;
  35 |     const tab2 = page.getByRole('tab', { name: new RegExp(`^(Sheet|工作表) *${next2}$`, 'i') }).first();
  36 |     await expect(tab2).toBeVisible();
  37 |     await expect(tab2).toHaveAttribute('aria-selected', 'true');
  38 |   });
  39 | });
```