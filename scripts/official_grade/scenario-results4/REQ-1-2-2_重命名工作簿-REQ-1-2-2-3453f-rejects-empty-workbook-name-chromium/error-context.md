# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: REQ-1-2-2_重命名工作簿.spec.ts >> REQ-1-2-2 Rename a Workbook >> rejects empty workbook name
- Location: ../../../../../../private/tmp/prod_test/sheet_single/projects/arcbench-app_20261001_221030/tests/selftest/REQ-1-2-2_重命名工作簿.spec.ts:32:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('button', { name: /Rename workbook/i })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('button', { name: /Rename workbook/i }) with timeout 10000ms
  - waiting for getByRole('button', { name: /Rename workbook/i })

```

```yaml
- heading "Q3 Sales" [level=1]
- text: "Region: East, North"
- tablist:
  - tab "Sheet1" [selected]
  - tab "Sheet2"
- text: Formula bar
- textbox "Formula bar"
- grid "Worksheet grid":
  - rowgroup:
    - row "1 Delete row 1 Insert row above Insert row below A1 B1":
      - text: "1"
      - button "Delete row 1": Delete row
      - button "Insert row above"
      - button "Insert row below"
      - gridcell "A1": Region
      - gridcell "B1": Q3 Sales
    - row "2 Delete row 2 Insert row above Insert row below A2 B2":
      - text: "2"
      - button "Delete row 2": Delete row
      - button "Insert row above"
      - button "Insert row below"
      - gridcell "A2": East
      - gridcell "B2": "100"
    - row "3 Delete row 3 Insert row above Insert row below A3 B3":
      - text: "3"
      - button "Delete row 3": Delete row
      - button "Insert row above"
      - button "Insert row below"
      - gridcell "A3": North
      - gridcell "B3": "200"
- button "Insert 1 column left"
- button "Insert 1 column right"
- button "Delete column"
- button "Add worksheet"
- button "Export CSV"
- button "Delete worksheet"
- heading "Rename worksheet" [level=3]
- textbox "New name"
- button "Rename"
- link "Download current sheet":
  - /url: /editor/Q3%20Sales/download-csv?sheet=Sheet1
- heading "Pivot table editor" [level=3]
- text: Rows
- textbox "Rows"
- text: Columns
- textbox "Columns"
- text: Values
- textbox "Values"
- button "Refresh pivot table"
- button "Create pivot table"
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('REQ-1-2-2 Rename a Workbook', () => {
  4  |   test('renames workbook and persists new name on home page', async ({ page }) => {
  5  |     await page.goto('/');
  6  |     const workbookLink = page.getByRole('link', { name: /Q3 Sales/i });
  7  |     await expect(workbookLink).toBeVisible();
  8  |     await workbookLink.click();
  9  | 
  10 |     const renameButton = page.getByRole('button', { name: /Rename workbook/i });
  11 |     await expect(renameButton).toBeVisible();
  12 |     await renameButton.click();
  13 | 
  14 |     const nameInput = page.getByLabel(/Workbook name/i);
  15 |     await expect(nameInput).toBeVisible();
  16 |     await nameInput.fill('Renamed Sheet');
  17 | 
  18 |     const saveButton = page.getByRole('button', { name: /Save/i });
  19 |     await expect(saveButton).toBeVisible();
  20 |     await saveButton.click();
  21 | 
  22 |     await expect(page.getByText(/Renamed Sheet/i).first()).toBeVisible();
  23 | 
  24 |     await page.goto('/');
  25 |     const renamedLink = page.getByRole('link', { name: /Renamed Sheet/i });
  26 |     await expect(renamedLink).toBeVisible();
  27 | 
  28 |     await renamedLink.click();
  29 |     await expect(page.getByText(/Renamed Sheet/i).first()).toBeVisible();
  30 |   });
  31 | 
  32 |   test('rejects empty workbook name', async ({ page }) => {
  33 |     await page.goto('/');
  34 |     const workbookLink = page.getByRole('link', { name: /Q3 Sales/i });
  35 |     await expect(workbookLink).toBeVisible();
  36 |     await workbookLink.click();
  37 | 
  38 |     const renameButton = page.getByRole('button', { name: /Rename workbook/i });
> 39 |     await expect(renameButton).toBeVisible();
     |                                ^ Error: expect(locator).toBeVisible() failed
  40 |     await renameButton.click();
  41 | 
  42 |     const nameInput = page.getByLabel(/Workbook name/i);
  43 |     await expect(nameInput).toBeVisible();
  44 |     await nameInput.fill('');
  45 | 
  46 |     const saveButton = page.getByRole('button', { name: /Save/i });
  47 |     await expect(saveButton).toBeVisible();
  48 |     await saveButton.click();
  49 | 
  50 |     await expect(page.getByText(/Workbook name cannot be empty/i).first()).toBeVisible();
  51 |     await expect(page.getByText(/Q3 Sales/i).first()).toBeVisible();
  52 |   });
  53 | });
```