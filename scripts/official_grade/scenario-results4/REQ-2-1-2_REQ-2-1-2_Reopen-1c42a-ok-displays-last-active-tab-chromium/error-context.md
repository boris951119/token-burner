# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-2-1-2_REQ-2-1-2_Reopen_workbook_retains_last_active_shee.spec.ts >> REQ-2-1-2 Switch Worksheets >> reopen workbook displays last active tab
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-2-1-2_REQ-2-1-2_Reopen_workbook_retains_last_active_shee.spec.ts:4:7

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: /^Add worksheet$/i })

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
    - dialog "Import CSV" [ref=e23]:
      - generic [ref=e24]:
        - button "Choose File" [ref=e25]
        - button "Import CSV" [ref=e26]
      - paragraph [ref=e27]: "Accepted file type: .csv"
  - generic [ref=e28]:
    - heading "Workbook rules" [level=3] [ref=e29]
    - paragraph [ref=e30]: Workbook name cannot be empty
    - paragraph [ref=e31]: Invalid CSV file format. Import failed.
    - paragraph [ref=e32]: Worksheet name cannot be empty
    - paragraph [ref=e33]: Worksheet name already exists
    - paragraph [ref=e34]: Please delete or rebuild dependent pivot tables first
  - generic [ref=e35]:
    - heading "Data tools" [level=2] [ref=e36]
    - generic [ref=e37]:
      - text: Formula bar
      - textbox "Formula bar" [ref=e38]
    - generic [ref=e39]:
      - button "Save" [ref=e41]
      - button "Undo" [ref=e43]
      - button "Redo" [ref=e45]
    - generic [ref=e46]:
      - generic [ref=e47]:
        - text: Sort by
        - combobox "Sort by" [ref=e48]:
          - option "Region" [selected]
          - option "Q3 Sales"
      - generic [ref=e49]:
        - text: Order
        - combobox "Order" [ref=e50]:
          - option "Ascending" [selected]
          - option "Descending"
      - button "Apply sort" [ref=e51]
    - generic [ref=e52]:
      - generic [ref=e53]:
        - text: Range
        - textbox "Range" [ref=e54]:
          - /placeholder: A1:C6
      - button "Sort range" [ref=e55]
    - generic [ref=e56]:
      - generic [ref=e57]:
        - text: Condition
        - combobox "Condition" [ref=e58]:
          - option "Text contains" [selected]
          - option "Greater than"
      - generic [ref=e59]:
        - text: Value
        - textbox "Value" [ref=e60]
      - button "Apply filter" [ref=e61]
    - button "Create filter" [ref=e63]
    - button "Filter" [ref=e65]
    - generic [ref=e66]:
      - heading "Data validation" [level=3] [ref=e67]
      - generic [ref=e68]:
        - text: Before
        - textbox "Before" [ref=e69]
      - generic [ref=e70]:
        - text: Allowed values
        - textbox "Allowed values" [ref=e71]
      - generic [ref=e72]:
        - text: Minimum
        - textbox "Minimum" [ref=e73]
      - generic [ref=e74]:
        - text: Maximum
        - textbox "Maximum" [ref=e75]
      - generic [ref=e76]:
        - text: Validation type
        - combobox "Validation type" [ref=e77]:
          - option "Dropdown" [selected]
          - option "Number range"
      - button "Apply validation" [ref=e78]
    - generic [ref=e79]:
      - heading "Pivot table editor" [level=3] [ref=e80]
      - generic [ref=e81]:
        - text: Rows
        - textbox "Rows" [ref=e82]
      - generic [ref=e83]:
        - text: Columns
        - textbox "Columns" [ref=e84]
      - generic [ref=e85]:
        - text: Values
        - textbox "Values" [ref=e86]
      - button "Refresh pivot table" [ref=e87]
      - button "Create pivot table" [ref=e88]
    - generic [ref=e89]:
      - generic [ref=e90]:
        - spinbutton "Please enter a number from 0 to 100" [ref=e91]
        - button "Delete row" [ref=e92]
      - button "Insert 1 column left" [ref=e94]
      - button "Insert 1 column right" [ref=e96]
      - button "Delete column" [ref=e98]
      - generic [ref=e99]:
        - generic [ref=e100]:
          - text: Range A1:B2
          - textbox "Range A1:B2" [ref=e101]:
            - /placeholder: A1:B2
        - generic [ref=e102]:
          - text: Range D1:E2
          - textbox "Range D1:E2" [ref=e103]:
            - /placeholder: D1:E2
        - button "Paste" [ref=e104]
  - generic [ref=e105]: .csvSheet2Worksheet name cannot be emptyWorksheet name already existsDeletePlease delete or rebuild dependent pivot tables firstInsert 1 row aboveInsert 1 row below
  - generic [ref=e106]:
    - generic [ref=e107]: .csv
    - generic [ref=e108]: Sheet2
    - generic [ref=e109]: Worksheet name cannot be empty
    - generic [ref=e110]: Worksheet name already exists
    - generic [ref=e111]: Delete
    - generic [ref=e112]: Please delete or rebuild dependent pivot tables first
    - generic [ref=e113]: Insert 1 row above
    - generic [ref=e114]: Insert 1 row below
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-2-1-2 Switch Worksheets', () => {
  4  |   test('reopen workbook displays last active tab', async ({ page }) => {
  5  |     await page.goto('/');
  6  | 
  7  |     const workbookEntry = page
  8  |       .getByRole('article')
  9  |       .filter({ has: page.getByText(/Q3 Sales/i) })
  10 |       .or(page.getByText(/Q3 Sales/i).first());
  11 |     await workbookEntry.first().click();
  12 | 
  13 |     if (await page.getByRole('tab').count() < 2) {
> 14 |       await page.getByRole('button', { name: /^Add worksheet$/i }).click();
     |                                                                    ^ Error: locator.click: Test timeout of 60000ms exceeded.
  15 |     }
  16 | 
  17 |     const secondTab = page.getByRole('tab').nth(1);
  18 |     await secondTab.click();
  19 |     await expect(secondTab).toHaveAttribute('aria-selected', 'true');
  20 | 
  21 |     await page.reload();
  22 | 
  23 |     const reopenedSecondTab = page.getByRole('tab').nth(1);
  24 |     await expect(reopenedSecondTab).toHaveAttribute('aria-selected', 'true');
  25 |     await expect(page.getByText(/^A1$/i).first()).toBeVisible();
  26 |   });
  27 | });
```