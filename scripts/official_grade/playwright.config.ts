import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './specs/keep',
  timeout: Number(process.env.PLAYWRIGHT_TEST_TIMEOUT || 60_000),
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: process.env.GRADE_REPORT || 'grade-report.json' }]],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || 'test-results',
  use: {
    baseURL: process.env.TARGET_URL || 'http://127.0.0.1:3301',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
