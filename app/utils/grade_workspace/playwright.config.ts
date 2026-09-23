import { defineConfig, devices } from '@playwright/test';

// 随包判分工作区：官方容器里没有 scripts/（打包白名单只放 app/ 等根条目），
// 自测闸的 playwright.config.ts 必须住在 app/ 内部才能进包。
export default defineConfig({
  testDir: process.env.PLAYWRIGHT_TEST_DIR || './specs',
  timeout: Number(process.env.PLAYWRIGHT_TEST_TIMEOUT || 60_000),
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: process.env.GRADE_REPORT || 'grade-report.json' }]],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || 'test-results',
  use: {
    baseURL: process.env.TARGET_URL || 'http://127.0.0.1:3301',
    actionTimeout: Number(process.env.PLAYWRIGHT_ACTION_TIMEOUT || 0),
    navigationTimeout: Number(process.env.PLAYWRIGHT_NAVIGATION_TIMEOUT || 0),
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
