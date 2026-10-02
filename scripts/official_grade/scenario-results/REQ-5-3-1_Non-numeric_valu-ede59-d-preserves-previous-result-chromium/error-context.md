# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-5-3-1_Non-numeric_value_field_shows_error_and_preserves_.spec.ts >> REQ-5-3-1 Create and Refresh a Basic Pivot Table >> Non-numeric value field shows error and preserves previous result
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-5-3-1_Non-numeric_value_field_shows_error_and_preserves_.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('link', { name: /Q3 Sales/i }).or(getByRole('row', { name: /Q3 Sales/i })).first()

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - heading "Workbooks" [level=1] [ref=e2]
  - generic [ref=e3]:
    - article [ref=e4]:
      - heading [level=2] [ref=e5]:
        - link "C1" [ref=e6] [cursor=pointer]:
          - /url: /editor/C1
      - generic [ref=e7]: "Sheets: Sheet1, Sheet2"
      - generic [ref=e8]: "Region: East, North"
      - generic [ref=e9]: "Last updated: 2025-01-01 10:00"
      - link "Open editor" [ref=e10] [cursor=pointer]:
        - /url: /editor/C1
      - generic [ref=e12]:
        - text: Rename workbook
        - textbox [ref=e13]: C1
        - button "Rename" [ref=e14]
    - article [ref=e15]:
      - heading [level=2] [ref=e16]:
        - link "=A1+B1" [ref=e17] [cursor=pointer]:
          - /url: /editor/%3DA1%2BB1
      - generic [ref=e18]: "Sheets: Sheet1"
      - generic [ref=e19]: "Region: —"
      - generic [ref=e20]: "Last updated: 2025-01-01 10:00"
      - link "Open editor" [ref=e21] [cursor=pointer]:
        - /url: /editor/%3DA1%2BB1
      - generic [ref=e23]:
        - text: Rename workbook
        - textbox [ref=e24]: =A1+B1
        - button "Rename" [ref=e25]
  - generic [ref=e26]:
    - heading "New blank workbook" [level=2] [ref=e27]
    - generic [ref=e28]:
      - generic [ref=e29]:
        - text: Workbook name
        - textbox "Workbook name" [ref=e30]
      - button "Create" [ref=e31]
  - generic [ref=e32]:
    - heading "Import CSV" [level=2] [ref=e33]
    - generic [ref=e34]:
      - button "Choose File" [ref=e35]
      - button "Import CSV" [ref=e36]
    - paragraph [ref=e37]: "Accepted file type: .csv"
  - generic [ref=e38]:
    - heading "Workbook rules" [level=3] [ref=e39]
    - paragraph [ref=e40]: Workbook name cannot be empty
    - paragraph [ref=e41]: Invalid CSV file format. Import failed.
    - paragraph [ref=e42]: Worksheet name cannot be empty
    - paragraph [ref=e43]: Worksheet name already exists
    - paragraph [ref=e44]: Please delete or rebuild dependent pivot tables first
  - generic [ref=e45]:
    - heading "Data tools" [level=2] [ref=e46]
    - generic [ref=e47]:
      - text: Formula bar
      - textbox "Formula bar" [ref=e48]
    - generic [ref=e49]:
      - button "Save" [ref=e51]
      - button "Undo" [ref=e53]
      - button "Redo" [ref=e55]
    - generic [ref=e56]:
      - generic [ref=e57]:
        - text: Sort by
        - combobox "Sort by" [ref=e58]:
          - option "Region" [selected]
          - option "Q3 Sales"
      - generic [ref=e59]:
        - text: Order
        - combobox "Order" [ref=e60]:
          - option "Ascending" [selected]
          - option "Descending"
      - button "Apply sort" [ref=e61]
    - generic [ref=e62]:
      - generic [ref=e63]:
        - text: Range
        - textbox "Range" [ref=e64]:
          - /placeholder: A1:C6
      - button "Sort range" [ref=e65]
    - generic [ref=e66]:
      - generic [ref=e67]:
        - text: Condition
        - combobox "Condition" [ref=e68]:
          - option "Text contains" [selected]
          - option "Greater than"
      - generic [ref=e69]:
        - text: Value
        - textbox "Value" [ref=e70]
      - button "Apply filter" [ref=e71]
    - button "Create filter" [ref=e73]
    - button "Filter" [ref=e75]
    - generic [ref=e76]:
      - heading "Data validation" [level=3] [ref=e77]
      - generic [ref=e78]:
        - text: Before
        - textbox "Before" [ref=e79]
      - generic [ref=e80]:
        - text: Allowed values
        - textbox "Allowed values" [ref=e81]
      - generic [ref=e82]:
        - text: Minimum
        - textbox "Minimum" [ref=e83]
      - generic [ref=e84]:
        - text: Maximum
        - textbox "Maximum" [ref=e85]
      - generic [ref=e86]:
        - text: Validation type
        - combobox "Validation type" [ref=e87]:
          - option "Dropdown" [selected]
          - option "Number range"
      - button "Apply validation" [ref=e88]
    - generic [ref=e89]:
      - heading "Pivot table editor" [level=3] [ref=e90]
      - generic [ref=e91]:
        - text: Rows
        - textbox "Rows" [ref=e92]
      - generic [ref=e93]:
        - text: Columns
        - textbox "Columns" [ref=e94]
      - generic [ref=e95]:
        - text: Values
        - textbox "Values" [ref=e96]
      - button "Refresh pivot table" [ref=e97]
      - button "Create pivot table" [ref=e98]
    - generic [ref=e99]:
      - generic [ref=e100]:
        - spinbutton "Please enter a number from 0 to 100" [ref=e101]
        - button "Delete row" [ref=e102]
      - button "Insert 1 column left" [ref=e104]
      - button "Insert 1 column right" [ref=e106]
      - button "Delete column" [ref=e108]
      - generic [ref=e109]:
        - generic [ref=e110]:
          - text: Range A1:B2
          - textbox "Range A1:B2" [ref=e111]:
            - /placeholder: A1:B2
        - generic [ref=e112]:
          - text: Range D1:E2
          - textbox "Range D1:E2" [ref=e113]:
            - /placeholder: D1:E2
        - button "Paste" [ref=e114]
  - generic [ref=e115]: .csvSheet2Worksheet name cannot be emptyWorksheet name already existsDeletePlease delete or rebuild dependent pivot tables firstInsert 1 row aboveInsert 1 row below
  - generic [ref=e116]:
    - generic [ref=e117]: .csv
    - generic [ref=e118]: Sheet2
    - generic [ref=e119]: Worksheet name cannot be empty
    - generic [ref=e120]: Worksheet name already exists
    - generic [ref=e121]: Delete
    - generic [ref=e122]: Please delete or rebuild dependent pivot tables first
    - generic [ref=e123]: Insert 1 row above
    - generic [ref=e124]: Insert 1 row below
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-5-3-1 Create and Refresh a Basic Pivot Table', () => {
  4  |   test('Non-numeric value field shows error and preserves previous result', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookEntry = page.getByRole('link', { name: /Q3 Sales/i }).or(page.getByRole('row', { name: /Q3 Sales/i })).first();
> 7  |     await workbookEntry.click();
     |                         ^ Error: locator.click: Test timeout of 60000ms exceeded.
  8  |     const nameBox = page.getByRole('textbox').first();
  9  |     await expect(nameBox).toBeVisible();
  10 |     await nameBox.click();
  11 |     await nameBox.fill('A1:C6');
  12 |     await nameBox.press('Enter');
  13 |     await page.getByRole('button', { name: 'Data' }).click();
  14 |     await page.getByRole('menuitem', { name: 'Create pivot table' }).click();
  15 |     const dialog = page.getByRole('dialog', { name: 'Create pivot table' });
  16 |     await expect(dialog).toBeVisible();
  17 |     await expect(dialog).toContainText(/Source range:\s*A1:C6/i);
  18 |     await dialog.getByRole('radio', { name: 'New worksheet' }).check();
  19 |     await dialog.getByRole('button', { name: 'Create' }).click();
  20 |     const editor = page.getByRole('region', { name: 'Pivot table editor' });
  21 |     await expect(editor).toBeVisible();
  22 |     await page.getByRole('combobox', { name: 'Rows' }).click();
  23 |     await page.getByRole('option', { name: 'Region' }).click();
  24 |     await page.getByRole('combobox', { name: 'Values' }).click();
  25 |     await page.getByRole('option', { name: 'Sales' }).click();
  26 |     await page.getByRole('combobox', { name: 'Summarize by' }).click();
  27 |     await page.getByRole('option', { name: 'SUM' }).click();
  28 |     await editor.getByRole('button', { name: 'Apply' }).click();
  29 |     await expect(page.getByRole('tab', { name: 'Pivot1' })).toBeVisible();
  30 |     await page.getByRole('combobox', { name: 'Values' }).click();
  31 |     await page.getByRole('option', { name: 'Status' }).click();
  32 |     await editor.getByRole('button', { name: 'Apply' }).click();
  33 |     const errorFeedback = page.getByRole('alert').or(page.getByRole('status')).or(page.getByText(/Value field requires numeric values/i)).first();
  34 |     await expect(errorFeedback).toBeVisible();
  35 |     await expect(page.getByText(/^Grand Total$/i).first()).toBeVisible();
  36 |     await expect(page.getByText(/^2700$/i).first()).toBeVisible();
  37 |   });
  38 | });
```