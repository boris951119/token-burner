# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-1-3-1_Import_CSV_successfully_with_UTF-8_Chinese__Englis.spec.ts >> REQ-1-3-1 Import CSV to Create a Workbook >> successful import of UTF-8 CSV with Chinese, English, and numbers
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-1-3-1_Import_CSV_successfully_with_UTF-8_Chinese__Englis.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.setInputFiles: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('dialog', { name: /Import CSV/i }).getByLabel(/CSV file/i)

```

# Page snapshot

```yaml
- generic [active] [ref=f1e1]:
  - heading "Workbooks" [level=1] [ref=f1e2]
  - generic [ref=f1e3]: Invalid CSV file format. Import failed.
  - article [ref=f1e5]:
    - heading [level=2] [ref=f1e6]:
      - link "Q3 Sales" [ref=f1e7] [cursor=pointer]:
        - /url: /editor/Q3%20Sales
    - generic [ref=f1e8]: "Sheets: Sheet1, Sheet2"
    - generic [ref=f1e9]: "Region: East, North"
    - generic [ref=f1e10]: "Last updated: 2025-01-01 10:00"
    - link "Open editor" [ref=f1e11] [cursor=pointer]:
      - /url: /editor/Q3%20Sales
    - generic [ref=f1e13]:
      - text: Rename workbook
      - textbox [ref=f1e14]: Q3 Sales
      - button "Rename" [ref=f1e15]
  - generic [ref=f1e16]:
    - heading "New blank workbook" [level=2] [ref=f1e17]
    - generic [ref=f1e18]:
      - generic [ref=f1e19]:
        - text: Workbook name
        - textbox "Workbook name" [ref=f1e20]
      - button "Create" [ref=f1e21]
  - generic [ref=f1e22]:
    - heading "Import CSV" [level=2] [ref=f1e23]
    - dialog "Import CSV" [ref=f1e24]:
      - generic [ref=f1e25]:
        - button "Choose File" [ref=f1e26]
        - button "Import CSV" [ref=f1e27]
      - paragraph [ref=f1e28]: "Accepted file type: .csv"
  - generic [ref=f1e29]:
    - heading "Workbook rules" [level=3] [ref=f1e30]
    - paragraph [ref=f1e31]: Workbook name cannot be empty
    - paragraph [ref=f1e32]: Invalid CSV file format. Import failed.
    - paragraph [ref=f1e33]: Worksheet name cannot be empty
    - paragraph [ref=f1e34]: Worksheet name already exists
    - paragraph [ref=f1e35]: Please delete or rebuild dependent pivot tables first
  - generic [ref=f1e36]:
    - heading "Data tools" [level=2] [ref=f1e37]
    - generic [ref=f1e38]:
      - text: Formula bar
      - textbox "Formula bar" [ref=f1e39]
    - generic [ref=f1e40]:
      - button "Save" [ref=f1e42]
      - button "Undo" [ref=f1e44]
      - button "Redo" [ref=f1e46]
    - generic [ref=f1e47]:
      - generic [ref=f1e48]:
        - text: Sort by
        - combobox "Sort by" [ref=f1e49]:
          - option "Region" [selected]
          - option "Q3 Sales"
      - generic [ref=f1e50]:
        - text: Order
        - combobox "Order" [ref=f1e51]:
          - option "Ascending" [selected]
          - option "Descending"
      - button "Apply sort" [ref=f1e52]
    - generic [ref=f1e53]:
      - generic [ref=f1e54]:
        - text: Range
        - textbox "Range" [ref=f1e55]:
          - /placeholder: A1:C6
      - button "Sort range" [ref=f1e56]
    - generic [ref=f1e57]:
      - generic [ref=f1e58]:
        - text: Condition
        - combobox "Condition" [ref=f1e59]:
          - option "Text contains" [selected]
          - option "Greater than"
      - generic [ref=f1e60]:
        - text: Value
        - textbox "Value" [ref=f1e61]
      - button "Apply filter" [ref=f1e62]
    - button "Create filter" [ref=f1e64]
    - button "Filter" [ref=f1e66]
    - generic [ref=f1e67]:
      - heading "Data validation" [level=3] [ref=f1e68]
      - generic [ref=f1e69]:
        - text: Before
        - textbox "Before" [ref=f1e70]
      - generic [ref=f1e71]:
        - text: Allowed values
        - textbox "Allowed values" [ref=f1e72]
      - generic [ref=f1e73]:
        - text: Minimum
        - textbox "Minimum" [ref=f1e74]
      - generic [ref=f1e75]:
        - text: Maximum
        - textbox "Maximum" [ref=f1e76]
      - generic [ref=f1e77]:
        - text: Validation type
        - combobox "Validation type" [ref=f1e78]:
          - option "Dropdown" [selected]
          - option "Number range"
      - button "Apply validation" [ref=f1e79]
    - generic [ref=f1e80]:
      - heading "Pivot table editor" [level=3] [ref=f1e81]
      - generic [ref=f1e82]:
        - text: Rows
        - textbox "Rows" [ref=f1e83]
      - generic [ref=f1e84]:
        - text: Columns
        - textbox "Columns" [ref=f1e85]
      - generic [ref=f1e86]:
        - text: Values
        - textbox "Values" [ref=f1e87]
      - button "Refresh pivot table" [ref=f1e88]
      - button "Create pivot table" [ref=f1e89]
    - generic [ref=f1e90]:
      - generic [ref=f1e91]:
        - spinbutton "Please enter a number from 0 to 100" [ref=f1e92]
        - button "Delete row" [ref=f1e93]
      - button "Insert 1 column left" [ref=f1e95]
      - button "Insert 1 column right" [ref=f1e97]
      - button "Delete column" [ref=f1e99]
      - generic [ref=f1e100]:
        - generic [ref=f1e101]:
          - text: Range A1:B2
          - textbox "Range A1:B2" [ref=f1e102]:
            - /placeholder: A1:B2
        - generic [ref=f1e103]:
          - text: Range D1:E2
          - textbox "Range D1:E2" [ref=f1e104]:
            - /placeholder: D1:E2
        - button "Paste" [ref=f1e105]
  - generic [ref=f1e106]: .csvSheet2Worksheet name cannot be emptyWorksheet name already existsDeletePlease delete or rebuild dependent pivot tables firstInsert 1 row aboveInsert 1 row below
  - generic [ref=f1e107]:
    - generic [ref=f1e108]: .csv
    - generic [ref=f1e109]: Sheet2
    - generic [ref=f1e110]: Worksheet name cannot be empty
    - generic [ref=f1e111]: Worksheet name already exists
    - generic [ref=f1e112]: Delete
    - generic [ref=f1e113]: Please delete or rebuild dependent pivot tables first
    - generic [ref=f1e114]: Insert 1 row above
    - generic [ref=f1e115]: Insert 1 row below
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-1-3-1 Import CSV to Create a Workbook', () => {
  4  |   test('successful import of UTF-8 CSV with Chinese, English, and numbers', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('button', { name: /Import CSV/i }).click();
  7  |     const dialog = page.getByRole('dialog', { name: /Import CSV/i });
  8  |     await expect(dialog).toBeVisible();
  9  |     const csvContent = '名称,数量\n苹果,100\nBanana,200';
> 10 |     await dialog.getByLabel(/CSV file/i).setInputFiles({
     |     ^ Error: locator.setInputFiles: Test timeout of 60000ms exceeded.
  11 |       name: 'imported-cn.csv',
  12 |       mimeType: 'text/csv',
  13 |       buffer: Buffer.from(csvContent, 'utf-8')
  14 |     });
  15 |     await dialog.getByRole('button', { name: /Confirm import/i }).click();
  16 |     const grid = page.getByRole('grid', { name: /Worksheet grid/i });
  17 |     await expect(grid).toBeVisible();
  18 |     await expect(grid.getByRole('gridcell', { name: 'A1' })).toHaveText(/名称/);
  19 |     await expect(grid.getByRole('gridcell', { name: 'B1' })).toHaveText(/数量/);
  20 |     await expect(grid.getByRole('gridcell', { name: 'A2' })).toHaveText(/苹果/);
  21 |     await expect(grid.getByRole('gridcell', { name: 'B2' })).toHaveText(/100/);
  22 |     await expect(grid.getByRole('gridcell', { name: 'A3' })).toHaveText(/Banana/);
  23 |     await expect(grid.getByRole('gridcell', { name: 'B3' })).toHaveText(/200/);
  24 |     await page.reload();
  25 |     await expect(page.getByRole('grid', { name: /Worksheet grid/i })).toBeVisible();
  26 |     await expect(page.getByRole('gridcell', { name: 'A1' })).toHaveText(/名称/);
  27 |     await expect(page.getByRole('gridcell', { name: 'B2' })).toHaveText(/100/);
  28 |   });
  29 | });
```