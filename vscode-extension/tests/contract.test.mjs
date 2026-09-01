// M12-10：插件消息协议契约测试（扩展宿主外，Node 内置 test runner）。
//
// 数据源 = 双侧源码文本（特征测试惯例，落盘验证）：
// - vscode-extension/src/extension.ts  宿主侧
// - vscode-extension/media/main.js     webview 侧
//
// 协议闭合性断言：
// 1. 宿主 post() 发出的每个 command，webview 的 message switch 必须有 case 处理；
// 2. webview vscode.postMessage 发出的每个 command，宿主 onMessage switch 必须有 case；
// 3. 双方 command 集合非空（防止提取正则失效导致假绿）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const extSrc = readFileSync(
  join(ROOT, "vscode-extension", "src", "extension.ts"), "utf-8");
const webSrc = readFileSync(
  join(ROOT, "vscode-extension", "media", "main.js"), "utf-8");

// 宿主 → webview：统一走 this.post({ command: "x", ... }) helper
function extractPostCommands(src) {
  return new Set([...src.matchAll(/\.post\(\{\s*command:\s*"([a-zA-Z]+)"/g)]
    .map((m) => m[1]));
}
// webview → 宿主：vscode.postMessage({ command: "x", ... })
function extractWebviewSends(src) {
  return new Set([...src.matchAll(/postMessage\(\{\s*command:\s*"([a-zA-Z]+)"/g)]
    .map((m) => m[1]));
}
// switch 消息处理分支（双侧同构）
function extractCaseCommands(src) {
  return new Set([...src.matchAll(/case\s+"([a-zA-Z]+)":/g)]
    .map((m) => m[1]));
}

test("webview 发出的 command 在宿主 onMessage 全部有处理分支", () => {
  const sends = extractWebviewSends(webSrc);
  const handled = extractCaseCommands(extSrc);
  assert.ok(sends.size > 0, "webview 未提取到任何发送 command（正则失效？）");
  const missing = [...sends].filter((c) => !handled.has(c));
  assert.deepEqual(missing, [],
    `宿主 onMessage 缺少 case 分支: ${missing.join(", ")}`);
});

test("宿主 post 发出的 command 在 webview message switch 全部有处理分支", () => {
  const sends = extractPostCommands(extSrc);
  const handled = extractCaseCommands(webSrc);
  assert.ok(sends.size > 0, "宿主未提取到任何发送 command（正则失效？）");
  const missing = [...sends].filter((c) => !handled.has(c));
  assert.deepEqual(missing, [],
    `webview message switch 缺少 case 分支: ${missing.join(", ")}`);
});

test("webview 消息处理分支与宿主发送集合对齐（无幽灵 case）", () => {
  const extSends = extractPostCommands(extSrc);
  const webCases = extractCaseCommands(webSrc);
  // 允许 webview 有额外非消息 case（如纯 UI 事件）——只约束宿主消息侧
  const ghost = [...extSends].filter((c) => !webCases.has(c));
  assert.deepEqual(ghost, [], `宿主发送但 webview 未处理: ${ghost.join(", ")}`);
});

test("关键协议字段在双侧一致（defaults / taskUpdate / serverState）", () => {
  // M12-4 defaults：宿主下发 { models, budgetTokens }，webview applyDefaults 消费
  assert.match(extSrc, /defaults/);
  assert.match(webSrc, /applyDefaults/);
  assert.match(webSrc, /budgetTokens/);
  // taskUpdate：宿主发 { task }，webview renderTaskUpdate 消费
  assert.match(webSrc, /renderTaskUpdate/);
  // serverState：webview renderServerState 消费
  assert.match(webSrc, /renderServerState/);
});
