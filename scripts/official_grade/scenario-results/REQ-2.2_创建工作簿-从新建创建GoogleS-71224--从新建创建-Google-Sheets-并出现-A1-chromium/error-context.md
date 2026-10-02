# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2.2_创建工作簿-从新建创建GoogleSheets.spec.ts >> 创建工作簿 >> 从新建创建 Google Sheets 并出现 A1
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2.2_创建工作簿-从新建创建GoogleSheets.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: /新建/ }).first()

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - heading "Workbooks" [level=1] [ref=e2]
  - article [ref=e4]:
    - heading [level=2] [ref=e5]:
      - link "Q3 Sales" [ref=e6] [cursor=pointer]:
        - /url: /editor/Q3%20Sales
    - generic [ref=e7]: "Sheets: Sheet1, Sheet2"
    - generic [ref=e8]: "Region: East, North"
    - generic [ref=e9]: "Last updated: 2025-01-01 10:00"
    - link "Open editor" [ref=e10] [cursor=pointer]:
      - /url: /editor/Q3%20Sales
    - generic [ref=e12]:
      - text: Rename workbook
      - textbox [ref=e13]: Q3 Sales
      - button "Rename" [ref=e14]
  - generic [ref=e15]:
    - heading "New blank workbook" [level=2] [ref=e16]
    - generic [ref=e17]:
      - generic [ref=e18]:
        - text: Workbook name
        - textbox "Workbook name" [ref=e19]
      - button "Create" [ref=e20]
  - generic [ref=e21]:
    - heading "Import CSV" [level=2] [ref=e22]
    - generic [ref=e23]:
      - button "Choose File" [ref=e24]
      - button "Import CSV" [ref=e25]
    - paragraph [ref=e26]: "Accepted file type: .csv"
  - generic [ref=e27]:
    - heading "Workbook rules" [level=3] [ref=e28]
    - paragraph [ref=e29]: Workbook name cannot be empty
    - paragraph [ref=e30]: Invalid CSV file format. Import failed.
    - paragraph [ref=e31]: Worksheet name cannot be empty
    - paragraph [ref=e32]: Worksheet name already exists
    - paragraph [ref=e33]: Please delete or rebuild dependent pivot tables first
  - generic [ref=e34]:
    - heading "Data tools" [level=2] [ref=e35]
    - generic [ref=e36]:
      - text: Formula bar
      - textbox "Formula bar" [ref=e37]
    - generic [ref=e38]:
      - button "Save" [ref=e40]
      - button "Undo" [ref=e42]
      - button "Redo" [ref=e44]
    - generic [ref=e45]:
      - generic [ref=e46]:
        - text: Sort by
        - combobox "Sort by" [ref=e47]:
          - option "Region" [selected]
          - option "Q3 Sales"
      - generic [ref=e48]:
        - text: Order
        - combobox "Order" [ref=e49]:
          - option "Ascending" [selected]
          - option "Descending"
      - button "Apply sort" [ref=e50]
    - generic [ref=e51]:
      - generic [ref=e52]:
        - text: Range
        - textbox "Range" [ref=e53]:
          - /placeholder: A1:C6
      - button "Sort range" [ref=e54]
    - generic [ref=e55]:
      - generic [ref=e56]:
        - text: Condition
        - combobox "Condition" [ref=e57]:
          - option "Text contains" [selected]
          - option "Greater than"
      - generic [ref=e58]:
        - text: Value
        - textbox "Value" [ref=e59]
      - button "Apply filter" [ref=e60]
    - button "Create filter" [ref=e62]
    - button "Filter" [ref=e64]
    - generic [ref=e65]:
      - heading "Data validation" [level=3] [ref=e66]
      - generic [ref=e67]:
        - text: Before
        - textbox "Before" [ref=e68]
      - generic [ref=e69]:
        - text: Allowed values
        - textbox "Allowed values" [ref=e70]
      - generic [ref=e71]:
        - text: Minimum
        - textbox "Minimum" [ref=e72]
      - generic [ref=e73]:
        - text: Maximum
        - textbox "Maximum" [ref=e74]
      - generic [ref=e75]:
        - text: Validation type
        - combobox "Validation type" [ref=e76]:
          - option "Dropdown" [selected]
          - option "Number range"
      - button "Apply validation" [ref=e77]
    - generic [ref=e78]:
      - heading "Pivot table editor" [level=3] [ref=e79]
      - generic [ref=e80]:
        - text: Rows
        - textbox "Rows" [ref=e81]
      - generic [ref=e82]:
        - text: Columns
        - textbox "Columns" [ref=e83]
      - generic [ref=e84]:
        - text: Values
        - textbox "Values" [ref=e85]
      - button "Refresh pivot table" [ref=e86]
      - button "Create pivot table" [ref=e87]
    - generic [ref=e88]:
      - generic [ref=e89]:
        - spinbutton "Please enter a number from 0 to 100" [ref=e90]
        - button "Delete row" [ref=e91]
      - button "Insert 1 column left" [ref=e93]
      - button "Insert 1 column right" [ref=e95]
      - button "Delete column" [ref=e97]
      - generic [ref=e98]:
        - generic [ref=e99]:
          - text: Range A1:B2
          - textbox "Range A1:B2" [ref=e100]:
            - /placeholder: A1:B2
        - generic [ref=e101]:
          - text: Range D1:E2
          - textbox "Range D1:E2" [ref=e102]:
            - /placeholder: D1:E2
        - button "Paste" [ref=e103]
  - generic [ref=e104]: .csvSheet2Worksheet name cannot be emptyWorksheet name already existsDeletePlease delete or rebuild dependent pivot tables firstInsert 1 row aboveInsert 1 row below
  - generic [ref=e105]:
    - generic [ref=e106]: .csv
    - generic [ref=e107]: Sheet2
    - generic [ref=e108]: Worksheet name cannot be empty
    - generic [ref=e109]: Worksheet name already exists
    - generic [ref=e110]: Delete
    - generic [ref=e111]: Please delete or rebuild dependent pivot tables first
    - generic [ref=e112]: Insert 1 row above
    - generic [ref=e113]: Insert 1 row below
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('创建工作簿', () => {
  4  |   test('从新建创建 Google Sheets 并出现 A1', async ({ page }) => {
  5  |     await page.goto('/');
> 6  |     await page.getByRole('button', { name: /新建/ }).first().click();
     |                                                            ^ Error: locator.click: Test timeout of 60000ms exceeded.
  7  |     await page.getByRole('menuitem', { name: /Google Sheets/i }).or(page.getByText(/Google Sheets/i)).first().click();
  8  |     await expect(page.getByText(/^A1$/i).first()).toBeVisible();
  9  |     await expect(page.getByText(/^工作表 1$/i).first()).toBeVisible();
  10 |   });
  11 | });
```