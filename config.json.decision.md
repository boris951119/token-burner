# 编队决策记录（2026-10-02，用户定）

## 正式参赛（线上平台）
- models[0] = **openai/glm-5.3-flash**（多模态：直接审题吃参考截图，不依赖视觉兜底链）
- single 模式下整场全用它（方案/写码/测试/修复一个模型）
- 平台 MODEL 栏填：`glm-5.3-flash`

## 本地验证（官方测试 key）
- 本地 stage-1 验证 run 用 deepseek-v4-pro 跑基线（发车时编队还是 [pro,...]）
- glm-5.3-flash 视觉能力已于官方测试端点实测：吃图 OK（转写 Google Drive 截图质量高）

## multi 模式（如启用）
models[0]=glm 主帅、[1]=deepseek-v4-pro 重量备胎、[2]=qwen3.8-max 测试
