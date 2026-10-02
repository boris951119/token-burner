# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-3-2-2_Redo_button_reapplies_undone_edit.spec.ts >> REQ-3-2-2 Undo and Redo Recent Operations >> Redo button reapplies undone edit
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-3-2-2_Redo_button_reapplies_undone_edit.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByText(/Q3\s+Sales/i).first()
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
    - dialog "Import CSV" [ref=e34]:
      - generic [ref=e35]:
        - button "Choose File" [ref=e36]
        - button "Import CSV" [ref=e37]
      - paragraph [ref=e38]: "Accepted file type: .csv"
  - generic [ref=e39]:
    - heading "Workbook rules" [level=3] [ref=e40]
    - paragraph [ref=e41]: Workbook name cannot be empty
    - paragraph [ref=e42]: Invalid CSV file format. Import failed.
    - paragraph [ref=e43]: Worksheet name cannot be empty
    - paragraph [ref=e44]: Worksheet name already exists
    - paragraph [ref=e45]: Please delete or rebuild dependent pivot tables first
  - generic [ref=e46]:
    - heading "Data tools" [level=2] [ref=e47]
    - generic [ref=e48]:
      - text: Formula bar
      - textbox "Formula bar" [ref=e49]
    - generic [ref=e50]:
      - button "Save" [ref=e52]
      - button "Undo" [ref=e54]
      - button "Redo" [ref=e56]
    - generic [ref=e57]:
      - generic [ref=e58]:
        - text: Sort by
        - combobox "Sort by" [ref=e59]:
          - option "Region" [selected]
          - option "Q3 Sales"
      - generic [ref=e60]:
        - text: Order
        - combobox "Order" [ref=e61]:
          - option "Ascending" [selected]
          - option "Descending"
      - button "Apply sort" [ref=e62]
    - generic [ref=e63]:
      - generic [ref=e64]:
        - text: Range
        - textbox "Range" [ref=e65]:
          - /placeholder: A1:C6
      - button "Sort range" [ref=e66]
    - generic [ref=e67]:
      - generic [ref=e68]:
        - text: Condition
        - combobox "Condition" [ref=e69]:
          - option "Text contains" [selected]
          - option "Greater than"
      - generic [ref=e70]:
        - text: Value
        - textbox "Value" [ref=e71]
      - button "Apply filter" [ref=e72]
    - button "Create filter" [ref=e74]
    - button "Filter" [ref=e76]
    - generic [ref=e77]:
      - heading "Data validation" [level=3] [ref=e78]
      - generic [ref=e79]:
        - text: Before
        - textbox "Before" [ref=e80]
      - generic [ref=e81]:
        - text: Allowed values
        - textbox "Allowed values" [ref=e82]
      - generic [ref=e83]:
        - text: Minimum
        - textbox "Minimum" [ref=e84]
      - generic [ref=e85]:
        - text: Maximum
        - textbox "Maximum" [ref=e86]
      - generic [ref=e87]:
        - text: Validation type
        - combobox "Validation type" [ref=e88]:
          - option "Dropdown" [selected]
          - option "Number range"
      - button "Apply validation" [ref=e89]
    - generic [ref=e90]:
      - heading "Pivot table editor" [level=3] [ref=e91]
      - generic [ref=e92]:
        - text: Rows
        - textbox "Rows" [ref=e93]
      - generic [ref=e94]:
        - text: Columns
        - textbox "Columns" [ref=e95]
      - generic [ref=e96]:
        - text: Values
        - textbox "Values" [ref=e97]
      - button "Refresh pivot table" [ref=e98]
      - button "Create pivot table" [ref=e99]
    - generic [ref=e100]:
      - generic [ref=e101]:
        - spinbutton "Please enter a number from 0 to 100" [ref=e102]
        - button "Delete row" [ref=e103]
      - button "Insert 1 column left" [ref=e105]
      - button "Insert 1 column right" [ref=e107]
      - button "Delete column" [ref=e109]
      - generic [ref=e110]:
        - generic [ref=e111]:
          - text: Range A1:B2
          - textbox "Range A1:B2" [ref=e112]:
            - /placeholder: A1:B2
        - generic [ref=e113]:
          - text: Range D1:E2
          - textbox "Range D1:E2" [ref=e114]:
            - /placeholder: D1:E2
        - button "Paste" [ref=e115]
  - generic [ref=e116]: .csvSheet2Worksheet name cannot be emptyWorksheet name already existsDeletePlease delete or rebuild dependent pivot tables firstInsert 1 row aboveInsert 1 row below
  - generic [ref=e117]:
    - generic [ref=e118]: .csv
    - generic [ref=e119]: Sheet2
    - generic [ref=e120]: Worksheet name cannot be empty
    - generic [ref=e121]: Worksheet name already exists
    - generic [ref=e122]: Delete
    - generic [ref=e123]: Please delete or rebuild dependent pivot tables first
    - generic [ref=e124]: Insert 1 row above
    - generic [ref=e125]: Insert 1 row below
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-3-2-2 Undo and Redo Recent Operations', () => {
  4  |   test('Redo button reapplies undone edit', async ({ page }) => {
  5  |     await page.goto('/');
> 6  |     await page.getByText(/Q3\s+Sales/i).first().click();
     |                                                 ^ Error: locator.click: Test timeout of 60000ms exceeded.
  7  |     const cellItem = page.getByRole('cell', { name: /^Item$/i }).or(page.getByRole('gridcell', { name: /^Item$/i })).first();
  8  |     await expect(cellItem).toBeVisible();
  9  |     await cellItem.dblclick();
  10 |     await page.keyboard.type('Changed');
  11 |     await page.keyboard.press('Enter');
  12 |     const cellChanged = page.getByRole('cell', { name: /^Changed$/i }).or(page.getByRole('gridcell', { name: /^Changed$/i })).first();
  13 |     await expect(cellChanged).toBeVisible();
  14 |     await page.getByRole('button', { name: 'Undo' }).click();
  15 |     await expect(cellItem).toBeVisible();
  16 |     await page.getByRole('button', { name: 'Redo' }).click();
  17 |     await expect(cellChanged).toBeVisible();
  18 |   });
  19 | });
```