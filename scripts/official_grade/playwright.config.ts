import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: process.env.PLAYWRIGHT_TEST_DIR || './specs/keep',
  timeout: Number(process.env.PLAYWRIGHT_TEST_TIMEOUT || 60_000),
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: process.env.GRADE_REPORT || 'grade-report.json' }]],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || 'test-results',
  use: {
    baseURL: process.env.TARGET_URL || 'http://127.0.0.1:3301',
    // 动作等待上限（0=沿用 test 超时，官方口径不变）。自测闸显式设 15s：
    // 9/23 实测一轮 32 用例跑 16 分钟，其中 13 条把 60s 预算整条耗在
    // locator.fill 挂起上——报错形状与 15s 完全相同，白等 45 秒 × 每轮修复。
    actionTimeout: Number(process.env.PLAYWRIGHT_ACTION_TIMEOUT || 0),
    navigationTimeout: Number(process.env.PLAYWRIGHT_NAVIGATION_TIMEOUT || 0),
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
