# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-4-2-1_Recalculate_dependent_formulas_after_source_edit.spec.ts >> REQ-4-2-1 Recalculate Dependent Formulas After Source Data Changes >> editing a source cell updates dependent formulas and persists after refresh
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-4-2-1_Recalculate_dependent_formulas_after_source_edit.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('link', { name: /Q3 Sales/i }).or(getByText(/Q3 Sales/i).first()).first()
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
  3  | test.describe('REQ-4-2-1 Recalculate Dependent Formulas After Source Data Changes', () => {
  4  |   test('editing a source cell updates dependent formulas and persists after refresh', async ({ page }) => {
  5  |     await page.goto('/');
  6  | 
  7  |     // Open the seeded workbook Q3 Sales from the application home page
  8  |     const workbookEntry = page.getByRole('link', { name: /Q3 Sales/i })
  9  |       .or(page.getByText(/Q3 Sales/i).first());
> 10 |     await workbookEntry.first().click();
     |                                 ^ Error: locator.click: Test timeout of 60000ms exceeded.
  11 | 
  12 |     // Wait for the spreadsheet editor to appear by checking the name box (shows A1 by default)
  13 |     const nameBox = page.getByLabel(/名称/i)
  14 |       .or(page.getByRole('textbox').first())
  15 |       .first();
  16 |     await expect(nameBox).toBeVisible();
  17 | 
  18 |     // The formula bar is the next textbox after the name box
  19 |     const formulaBar = page.getByRole('textbox').nth(1);
  20 | 
  21 |     // Initial formula results: =A1+B1 should show 5 (A1=2, B1=3)
  22 |     // We locate C1 (assumed to contain =A1+B1) and verify the formula bar shows the original formula
  23 |     await nameBox.fill('C1');
  24 |     await nameBox.press('Enter');
  25 |     await expect(formulaBar).toHaveValue(/=A1\+B1/);
  26 |     await expect(page.getByText(/^5$/).first()).toBeVisible();
  27 | 
  28 |     // Edit the source cell A1 from 2 to 5
  29 |     await nameBox.fill('A1');
  30 |     await nameBox.press('Enter');
  31 |     await formulaBar.fill('5');
  32 |     await formulaBar.press('Enter');
  33 | 
  34 |     // Verify dependent formula in C1 recalculated to 8 (5+3)
  35 |     await nameBox.fill('C1');
  36 |     await nameBox.press('Enter');
  37 |     await expect(formulaBar).toHaveValue(/=A1\+B1/);
  38 |     await expect(page.getByText(/^8$/).first()).toBeVisible();
  39 | 
  40 |     // Verify indirect dependent formula =C1*2 now shows 16 (assuming it is in D1)
  41 |     await nameBox.fill('D1');
  42 |     await nameBox.press('Enter');
  43 |     await expect(formulaBar).toHaveValue(/=C1\*2/);
  44 |     await expect(page.getByText(/^16$/).first()).toBeVisible();
  45 | 
  46 |     // Refresh the page and reopen the workbook to confirm persistence
  47 |     await page.reload();
  48 |     const reopenedEntry = page.getByRole('link', { name: /Q3 Sales/i })
  49 |       .or(page.getByText(/Q3 Sales/i).first());
  50 |     await reopenedEntry.first().click();
  51 | 
  52 |     // After reopen, verify results are still 8 and 16, and formulas remain original
  53 |     await expect(nameBox).toBeVisible();
  54 |     await nameBox.fill('C1');
  55 |     await nameBox.press('Enter');
  56 |     await expect(formulaBar).toHaveValue(/=A1\+B1/);
  57 |     await expect(page.getByText(/^8$/).first()).toBeVisible();
  58 | 
  59 |     await nameBox.fill('D1');
  60 |     await nameBox.press('Enter');
  61 |     await expect(formulaBar).toHaveValue(/=C1\*2/);
  62 |     await expect(page.getByText(/^16$/).first()).toBeVisible();
  63 |   });
  64 | });
```