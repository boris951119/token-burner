# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-1-3-1_Reject_invalid_CSV_and_do_not_create_workbook_link.spec.ts >> REQ-1-3-1 Import CSV to Create a Workbook >> rejects invalid CSV and does not create workbook link
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-1-3-1_Reject_invalid_CSV_and_do_not_create_workbook_link.spec.ts:4:7

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
  - generic [ref=f1e4]:
    - article [ref=f1e5]:
      - heading [level=2] [ref=f1e6]:
        - link "C1" [ref=f1e7] [cursor=pointer]:
          - /url: /editor/C1
      - generic [ref=f1e8]: "Sheets: Sheet1, Sheet2"
      - generic [ref=f1e9]: "Region: East, North"
      - generic [ref=f1e10]: "Last updated: 2025-01-01 10:00"
      - link "Open editor" [ref=f1e11] [cursor=pointer]:
        - /url: /editor/C1
      - generic [ref=f1e13]:
        - text: Rename workbook
        - textbox [ref=f1e14]: C1
        - button "Rename" [ref=f1e15]
    - article [ref=f1e16]:
      - heading [level=2] [ref=f1e17]:
        - link "=A1+B1" [ref=f1e18] [cursor=pointer]:
          - /url: /editor/%3DA1%2BB1
      - generic [ref=f1e19]: "Sheets: Sheet1"
      - generic [ref=f1e20]: "Region: —"
      - generic [ref=f1e21]: "Last updated: 2025-01-01 10:00"
      - link "Open editor" [ref=f1e22] [cursor=pointer]:
        - /url: /editor/%3DA1%2BB1
      - generic [ref=f1e24]:
        - text: Rename workbook
        - textbox [ref=f1e25]: =A1+B1
        - button "Rename" [ref=f1e26]
  - generic [ref=f1e27]:
    - heading "New blank workbook" [level=2] [ref=f1e28]
    - generic [ref=f1e29]:
      - generic [ref=f1e30]:
        - text: Workbook name
        - textbox "Workbook name" [ref=f1e31]
      - button "Create" [ref=f1e32]
  - generic [ref=f1e33]:
    - heading "Import CSV" [level=2] [ref=f1e34]
    - dialog "Import CSV" [ref=f1e35]:
      - generic [ref=f1e36]:
        - button "Choose File" [ref=f1e37]
        - button "Import CSV" [ref=f1e38]
      - paragraph [ref=f1e39]: "Accepted file type: .csv"
  - generic [ref=f1e40]:
    - heading "Workbook rules" [level=3] [ref=f1e41]
    - paragraph [ref=f1e42]: Workbook name cannot be empty
    - paragraph [ref=f1e43]: Invalid CSV file format. Import failed.
    - paragraph [ref=f1e44]: Worksheet name cannot be empty
    - paragraph [ref=f1e45]: Worksheet name already exists
    - paragraph [ref=f1e46]: Please delete or rebuild dependent pivot tables first
  - generic [ref=f1e47]:
    - heading "Data tools" [level=2] [ref=f1e48]
    - generic [ref=f1e49]:
      - text: Formula bar
      - textbox "Formula bar" [ref=f1e50]
    - generic [ref=f1e51]:
      - button "Save" [ref=f1e53]
      - button "Undo" [ref=f1e55]
      - button "Redo" [ref=f1e57]
    - generic [ref=f1e58]:
      - generic [ref=f1e59]:
        - text: Sort by
        - combobox "Sort by" [ref=f1e60]:
          - option "Region" [selected]
          - option "Q3 Sales"
      - generic [ref=f1e61]:
        - text: Order
        - combobox "Order" [ref=f1e62]:
          - option "Ascending" [selected]
          - option "Descending"
      - button "Apply sort" [ref=f1e63]
    - generic [ref=f1e64]:
      - generic [ref=f1e65]:
        - text: Range
        - textbox "Range" [ref=f1e66]:
          - /placeholder: A1:C6
      - button "Sort range" [ref=f1e67]
    - generic [ref=f1e68]:
      - generic [ref=f1e69]:
        - text: Condition
        - combobox "Condition" [ref=f1e70]:
          - option "Text contains" [selected]
          - option "Greater than"
      - generic [ref=f1e71]:
        - text: Value
        - textbox "Value" [ref=f1e72]
      - button "Apply filter" [ref=f1e73]
    - button "Create filter" [ref=f1e75]
    - button "Filter" [ref=f1e77]
    - generic [ref=f1e78]:
      - heading "Data validation" [level=3] [ref=f1e79]
      - generic [ref=f1e80]:
        - text: Before
        - textbox "Before" [ref=f1e81]
      - generic [ref=f1e82]:
        - text: Allowed values
        - textbox "Allowed values" [ref=f1e83]
      - generic [ref=f1e84]:
        - text: Minimum
        - textbox "Minimum" [ref=f1e85]
      - generic [ref=f1e86]:
        - text: Maximum
        - textbox "Maximum" [ref=f1e87]
      - generic [ref=f1e88]:
        - text: Validation type
        - combobox "Validation type" [ref=f1e89]:
          - option "Dropdown" [selected]
          - option "Number range"
      - button "Apply validation" [ref=f1e90]
    - generic [ref=f1e91]:
      - heading "Pivot table editor" [level=3] [ref=f1e92]
      - generic [ref=f1e93]:
        - text: Rows
        - textbox "Rows" [ref=f1e94]
      - generic [ref=f1e95]:
        - text: Columns
        - textbox "Columns" [ref=f1e96]
      - generic [ref=f1e97]:
        - text: Values
        - textbox "Values" [ref=f1e98]
      - button "Refresh pivot table" [ref=f1e99]
      - button "Create pivot table" [ref=f1e100]
    - generic [ref=f1e101]:
      - generic [ref=f1e102]:
        - spinbutton "Please enter a number from 0 to 100" [ref=f1e103]
        - button "Delete row" [ref=f1e104]
      - button "Insert 1 column left" [ref=f1e106]
      - button "Insert 1 column right" [ref=f1e108]
      - button "Delete column" [ref=f1e110]
      - generic [ref=f1e111]:
        - generic [ref=f1e112]:
          - text: Range A1:B2
          - textbox "Range A1:B2" [ref=f1e113]:
            - /placeholder: A1:B2
        - generic [ref=f1e114]:
          - text: Range D1:E2
          - textbox "Range D1:E2" [ref=f1e115]:
            - /placeholder: D1:E2
        - button "Paste" [ref=f1e116]
  - generic [ref=f1e117]: .csvSheet2Worksheet name cannot be emptyWorksheet name already existsDeletePlease delete or rebuild dependent pivot tables firstInsert 1 row aboveInsert 1 row below
  - generic [ref=f1e118]:
    - generic [ref=f1e119]: .csv
    - generic [ref=f1e120]: Sheet2
    - generic [ref=f1e121]: Worksheet name cannot be empty
    - generic [ref=f1e122]: Worksheet name already exists
    - generic [ref=f1e123]: Delete
    - generic [ref=f1e124]: Please delete or rebuild dependent pivot tables first
    - generic [ref=f1e125]: Insert 1 row above
    - generic [ref=f1e126]: Insert 1 row below
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-1-3-1 Import CSV to Create a Workbook', () => {
  4  |   test('rejects invalid CSV and does not create workbook link', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     await page.getByRole('button', { name: /Import CSV/i }).click();
  7  |     const dialog = page.getByRole('dialog', { name: /Import CSV/i });
  8  |     await expect(dialog).toBeVisible();
  9  |     const invalidCsv = '"Name,Region\nAlice,East';
> 10 |     await dialog.getByLabel(/CSV file/i).setInputFiles({
     |     ^ Error: locator.setInputFiles: Test timeout of 60000ms exceeded.
  11 |       name: 'invalid.csv',
  12 |       mimeType: 'text/csv',
  13 |       buffer: Buffer.from(invalidCsv, 'utf-8')
  14 |     });
  15 |     await dialog.getByRole('button', { name: /Confirm import/i }).click();
  16 |     const error = page.getByRole('alert').or(page.getByRole('status')).or(page.getByText(/Invalid CSV file format\.\s*Import failed\./i));
  17 |     await expect(error.first()).toBeVisible();
  18 |     await page.goto('/');
  19 |     await expect(page.getByText(/^invalid$/i)).toHaveCount(0);
  20 |   });
  21 | });
```