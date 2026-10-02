# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-4-1-1_calculates_AVERAGE_aggregate_over_a_range_and_pers.spec.ts >> REQ-4-1-1 Calculate Basic Expressions and Aggregate Functions >> calculates AVERAGE aggregate over a range and persists
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-4-1-1_calculates_AVERAGE_aggregate_over_a_range_and_pers.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('article').filter({ has: getByText(/Q3 Sales/i) }).first().or(getByText(/Q3 Sales/i).first()).first()
    - locator resolved to <option value="Q3 Sales">Q3 Sales</option>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is not visible
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is not visible
    - retrying click action
      - waiting 100ms
    116 × waiting for element to be visible, enabled and stable
        - element is not visible
      - retrying click action
        - waiting 500ms

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
  3  | test.describe('REQ-4-1-1 Calculate Basic Expressions and Aggregate Functions', () => {
  4  |   test('calculates AVERAGE aggregate over a range and persists', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookEntry = page.getByRole('article').filter({ has: page.getByText(/Q3 Sales/i) }).first()
  7  |       .or(page.getByText(/Q3 Sales/i).first()).first();
> 8  |     await workbookEntry.click();
     |                         ^ Error: locator.click: Test timeout of 60000ms exceeded.
  9  | 
  10 |     const nameBox = page.getByLabel(/^A1$/i).or(page.getByPlaceholder(/^A1$/i)).or(page.getByRole('textbox')).or(page.getByRole('searchbox')).first();
  11 |     const formulaBar = page.getByLabel(/fx/i).or(page.getByPlaceholder(/fx/i)).or(page.getByRole('textbox')).or(page.getByRole('searchbox')).nth(1);
  12 | 
  13 |     await nameBox.click();
  14 |     await nameBox.fill('D1');
  15 |     await nameBox.press('Enter');
  16 |     await formulaBar.click();
  17 |     await formulaBar.fill('=AVERAGE(A1:B1)');
  18 |     await formulaBar.press('Enter');
  19 | 
  20 |     await expect(page.getByText(/^2.5$/i).first()).toBeVisible();
  21 |     await expect(formulaBar).toHaveValue('=AVERAGE(A1:B1)');
  22 | 
  23 |     await page.goto('/');
  24 |     await workbookEntry.click();
  25 |     await nameBox.click();
  26 |     await nameBox.fill('D1');
  27 |     await nameBox.press('Enter');
  28 |     await expect(page.getByText(/^2.5$/i).first()).toBeVisible();
  29 |     await expect(formulaBar).toHaveValue('=AVERAGE(A1:B1)');
  30 |   });
  31 | });
```