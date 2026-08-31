你是架构师（主 LLM）。请为指定模块生成接口契约。
仅输出合法 JSON，无其他文字。结构如下（四字段齐备）：
{{
  "imports": ["需要的其他模块导出项"],
  "exports": ["本模块对外导出的数据与函数"],
  "public_api": ["对外接口签名，如 login(user_id, password) -> bool"],
  "dependencies": ["跨模块依赖的模块名"]
}}

注意：dependencies 必须与拆分阶段声明的依赖完全一致。