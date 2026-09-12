"""ArcBench 平台桥接层（factory26 参赛适配，M8-4 事件的平台侧消费者）。

职责边界：
- 把 Pipeline 进度事件翻译为 arcbench_agent_runtime SDK 的高层调用
  （平台 Usage Rule：禁止手工构造事件 payload，只调 SDK 方法）；
- 只订阅事件，不改管线逻辑；回调内部异常一律吞掉（与 Pipeline._emit
  同一原则：进度上报失败不影响任务本身）。

降级策略：SDK 未安装（本地开发/单测）时自动 no-op，行为零差异。

事件映射（token-burner → 平台）：
- interfaces_ready       → upsert_interface（逐 export 登记，未实现态）
                           + mark_design_done（spec/契约定稿 = 设计完成）
- module_done SUCCESS    → mark_implementation_done + mark_test_passed
                           + set_interface_implemented + upsert_test(passed)
- module_done FROZEN     → mark_test_failed（修复上限耗尽，终态）
                           + upsert_test(failed)
- 每模块收尾             → runtime.git.commit（提交历史 + 预览刷新）
- run 生命周期           → mark_run_started / mark_run_completed /
                           mark_run_failed（main.py 显式调用）
- stage / tokens / research_* → 平台无对应面板，忽略

TODO(platform)（task pack 发布后复核）：
- node_map 缺省按 FOLDER 名称归一模糊匹配（显式 node_map 优先）；
- 生成代码写入平台 workspace 的目录约定（当前 runtime.git 提交整个
  workspace，目录约定确定后收窄到项目目录）。
"""

from __future__ import annotations

import re
import threading


def _norm(s: str) -> str:
    """名称归一：仅保留小写字母数字（模糊匹配的比对形态）。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class ArcBenchBridge:
    """Pipeline 事件 → ArcBench Runtime SDK 的单向翻译器（headless 用）。"""

    def __init__(
        self,
        node_map: dict[str, str] | None = None,
        runtime=None,  # 测试注入用；生产路径恒为 None（惰性 import SDK）
    ):
        self._injected = runtime
        self._runtime = None
        self._emit_lock = threading.Lock()
        # 模块名 → 平台 REQ 节点 id；显式映射优先，其余按 FOLDER 名模糊匹配
        self._node_map = dict(node_map or {})
        # store_tree 缓存的 FOLDER 索引（[{"id","name"}]）
        self._folders: list[dict] = []

    # ---- 内部 ----

    def _rt(self):
        """惰性取 SDK 单例；未安装返回 None（本地 no-op）。"""
        with self._emit_lock:
            if self._runtime is not None:
                return self._runtime
            if self._injected is not None:
                self._runtime = self._injected
                return self._runtime
            try:
                from arcbench_agent_runtime import AgentRuntime
            except ImportError:
                return None
            rt = AgentRuntime.from_env()
            rt.traceability.init_db()
            rt.git.ensure_repo(create_initial_commit=True)
            rt.git.ensure_arc_gitignore()
            self._runtime = rt
            return self._runtime

    def _node(self, module: str) -> str:
        if module in self._node_map:
            return self._node_map[module]
        matched = self._match_folder(module)
        if matched:
            self._node_map[module] = matched  # 记忆化：同一模块只匹配一次
            return matched
        return module

    def _match_folder(self, module: str) -> str | None:
        """模块名 → FOLDER id 模糊匹配（归一后 全等/互相包含/公共前缀）。

        确定性打分：全等 100 > 互相包含 80 > 公共前缀（≥4 字符且占
        短边 ≥2/3，取前缀长度）。无达标者返回 None（回落模块名自身，
        与缺省行为一致）。匹配失败的组合宁可不错——错挂节点比缺节点
        对评审可视化伤害更大。
        """
        m = _norm(module)
        if not m or not self._folders:
            return None
        best_id, best_score = None, 0
        for folder in self._folders:
            fid = str(folder.get("id") or "").strip()
            fname = _norm(str(folder.get("name") or ""))
            if not fid or not fname:
                continue
            if m == fname:
                score = 100
            elif m in fname or fname in m:
                score = 80
            else:
                common = 0
                for a, b in zip(m, fname):
                    if a != b:
                        break
                    common += 1
                short = min(len(m), len(fname))
                score = common if common >= 4 and common * 3 >= short * 2 else 0
            if score > best_score:
                best_id, best_score = fid, score
        return best_id if best_score else None

    # ---- 需求树登记（main.py 解析 requirements.yaml 后显式调用）----

    def store_tree(self, tree: dict) -> None:
        """把平台需求树原文写入 traceability（官方 workflow 同款起点动作）。"""
        try:
            rt = self._rt()
            if rt is not None:
                rt.traceability.store_requirement_tree(tree)
                self._folders = [
                    {"id": c.get("id"), "name": c.get("name")}
                    for c in (tree.get("children") or [])
                    if isinstance(c, dict) and c.get("type") == "FOLDER"
                ]
        except Exception:
            pass

    # ---- 生命周期（main.py 显式调用，不经事件推断）----

    def run_started(self, message: str = "") -> None:
        try:
            rt = self._rt()
            if rt is not None:
                rt.events.mark_run_started(message or None)
        except Exception:
            pass

    def run_completed(self, message: str = "") -> None:
        try:
            rt = self._rt()
            if rt is not None:
                rt.events.mark_run_completed(message or None)
        except Exception:
            pass

    def run_failed(self, message: str = "") -> None:
        try:
            rt = self._rt()
            if rt is not None:
                rt.events.mark_run_failed(message or None)
        except Exception:
            pass

    # ---- Pipeline on_event 适配（签名：kind, data → None）----

    def handle(self, kind: str, data: dict) -> None:
        """Pipeline._on_event 入口；任何异常不上抛（进度上报不影响任务）。"""
        try:
            self._handle(kind, data)
        except Exception:
            pass

    def _handle(self, kind: str, data: dict) -> None:
        if kind == "interfaces_ready":
            self._register_interfaces(data.get("interfaces") or {})
            return
        if kind != "module_done":
            return  # stage / tokens / research_* 平台无对应面板
        rt = self._rt()
        if rt is None:
            return
        module = str(data.get("module", ""))
        node = self._node(module)
        status = str(data.get("status", ""))
        message = (str(data.get("message", "")).strip() or None)
        if status == "SUCCESS":
            rt.events.mark_implementation_done(node, message)
            rt.events.mark_test_passed(node, message)
        elif status == "FROZEN":
            rt.events.mark_test_failed(node, message)
        # AWAITING_FEEDBACK 仅出现在安全模式交互闭环，平台 headless 不触发
        try:
            rt.git.commit(f"module:{module} {status}")
        except Exception:
            pass
        self._register_module_test(rt, module, node, status)

    # ---- traceability 登记（失败静默，不影响事件主链路）----

    def _register_interfaces(self, interfaces: dict) -> None:
        """契约快照 → interfaces 表（未实现态）+ 设计完成事件。"""
        try:
            rt = self._rt()
        except Exception:
            return
        if rt is None or not interfaces:
            return
        try:
            for module, contract in interfaces.items():
                if not isinstance(contract, dict):
                    continue
                node = self._node(str(module))
                exports = [
                    str(e).strip()
                    for e in (contract.get("exports") or [])
                    if str(e).strip()
                ]
                for sym in exports:
                    name_part = _norm(sym.split("(")[0]) or _norm(sym)
                    rt.traceability.upsert_interface(
                        interface_id=f"{_norm(str(module))}::{name_part}",
                        req_ids=[node],
                        type="function",
                        content=sym,
                        implemented=False,
                    )
                rt.events.mark_design_done(node, "spec 与接口契约定稿")
        except Exception:
            pass

    def _register_module_test(self, rt, module: str, node: str, status: str) -> None:
        """模块终态 → tests 表登记（SUCCESS/FROZEN 才有确定通过态）。"""
        if status not in ("SUCCESS", "FROZEN"):
            return
        passed = status == "SUCCESS"
        try:
            rt.traceability.upsert_test(
                test_id=f"test_{module}",
                req_id=node,
                type="pytest",
                file_path=f"tests/{module}/test_{module}.py",
                passed=passed,
            )
            if passed:
                for row in rt.traceability.list_interfaces(req_id=node):
                    interface_id = str(row.get("interface_id") or "").strip()
                    if interface_id:
                        rt.traceability.set_interface_implemented(
                            interface_id, True
                        )
        except Exception:
            pass
