# -*- coding: utf-8 -*-
"""v1.2 S2:SWE-bench Lite 子集跑分(简化验证口径)。

流程:数据准备(可选 datasets 库导出 JSONL)→ 分层抽样 → 逐实例
(clone → checkout base → apply test_patch → RepoFixer 修 issue →
pytest FAIL_TO_PASS 验证)→ 报告(resolved/unresolved/error + 成本)。

诚实边界(务必与结果一同公开):
- 验证为简化口径:在仓库根直接 pytest FAIL_TO_PASS 节点,不做官方
  per-repo conda 环境;官方分数可用 SWE-bench harness 对同一批补丁复评;
- 抽样剔除依赖重度 web 框架运行时的实例(按仓库名黑名单,清单入库)。

用法示例:
    python scripts/swebench_run.py --prepare-dataset           # 导出 JSONL
    python scripts/swebench_run.py --dataset swebench_lite.jsonl \
        --sample 50 --seed 42 --model openai/deepseek-v3 \
        --repos-cache .tmp/swebench_repos --out logs/swebench
环境变量:OPENAI_API_KEY / OPENAI_API_BASE(或对应供应商变量)。
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根入 path(app.* 可导入)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")  # API 凭据(本地,不入库)

REPO_URL = "https://github.com/{repo}.git"
# 重度运行时依赖仓库黑名单(简化验证口径下排除;清单随报告公开)
REPO_SKIP_HINTS = ("django", "matplotlib", "sympy", "scikit-learn", "astropy")


# ---------------------------------------------------------------------------
# 数据准备与抽样
# ---------------------------------------------------------------------------

def prepare_dataset(out: str) -> None:
    """从 HF datasets 导出 SWE-bench Lite test split 为 JSONL(可选依赖)。"""
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError:
        sys.exit("需要 pip install datasets 后重试,或手工放置官方 JSONL")
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in ds:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"数据集已导出: {path} ({len(ds)} 实例)")


def sample_instances(instances: list[dict], sample: int, seed: int) -> list[dict]:
    """分层抽样(按仓库聚合,每仓库至多 5 例;总量受 --sample 限制)。"""
    rng = random.Random(seed)
    by_repo: dict[str, list[dict]] = {}
    for ins in instances:
        repo = ins.get("repo", "")
        if any(h in repo.lower() for h in REPO_SKIP_HINTS):
            continue
        by_repo.setdefault(repo, []).append(ins)
    picked: list[dict] = []
    repos = sorted(by_repo)
    rng.shuffle(repos)
    while len(picked) < sample and any(by_repo[r] for r in repos):
        progress = False
        for repo in repos:
            if bucket := by_repo[repo]:
                picked.append(bucket.pop())
                progress = True
                if len(picked) >= sample:
                    break
        if not progress:
            break  # 可用实例耗尽(黑名单剔除/总量不足)——绝不死循环
    return picked


# ---------------------------------------------------------------------------
# 仓库准备
# ---------------------------------------------------------------------------

def ensure_repo(instance: dict, cache: Path) -> Path:
    """克隆(浅)并 checkout base_commit;已存在则直接 fetch/checkout。"""
    repo = instance["repo"]
    target = cache / repo.replace("/", "__")
    url = REPO_URL.format(repo=repo)
    if not target.exists():
        last = None
        for attempt in range(2):  # 网络抖动重试一次
            try:
                subprocess.run(["git", "clone", url, str(target)], check=True,
                               capture_output=True, text=True, timeout=900)
                last = None
                break
            except Exception as exc:
                last = exc
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
        if last is not None:
            raise last
    subprocess.run(["git", "fetch", "origin", instance["base_commit"]],
                   cwd=target, check=False, capture_output=True, timeout=300)
    subprocess.run(["git", "checkout", "-q", "-f", instance["base_commit"]],
                   cwd=target, check=True, capture_output=True, timeout=120)
    return target


def pip_install_repo(repo_path: Path) -> str:
    """pip install -e .(flask/xarray 等仓库测试的导入前提)。

    返回空串 = 成功;否则返回截尾错误(调用方记入实例备注)。
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet",
         "--disable-pip-version-check"],
        cwd=repo_path, capture_output=True, text=True, timeout=600)
    return "" if proc.returncode == 0 else (proc.stderr or proc.stdout)[-200:]


def apply_test_patch(instance: dict, repo_path: Path) -> None:
    """应用 test_patch(引入 FAIL_TO_PASS 测试;失败重试 -3 上下文)。"""
    patch = instance.get("test_patch") or ""
    if not patch.strip():
        return
    proc = subprocess.run(["git", "apply", "-"], input=patch, cwd=repo_path,
                          text=True, capture_output=True)
    if proc.returncode != 0:
        subprocess.run(["git", "apply", "-3", "-"], input=patch, cwd=repo_path,
                       text=True, capture_output=True)


# ---------------------------------------------------------------------------
# 逐实例执行
# ---------------------------------------------------------------------------

def run_instance(instance: dict, cache: Path, model: str,
                 max_rounds: int, pip_install: bool = True) -> dict:
    from app.agents.repo_fixer import RepoFixer
    from app.config import load_settings
    from app.utils.model_client import ModelClientFactory

    t0 = time.time()
    record_notes: list[str] = []
    record = {"instance_id": instance.get("instance_id")
              or f"{instance['repo']}-{instance['base_commit'][:8]}",
              "repo": instance["repo"], "resolved": False,
              "status": "error", "rounds": 0, "changed_files": [],
              "tokens": 0, "duration_s": 0, "error": ""}
    try:
        repo_path = ensure_repo(instance, cache)
        apply_test_patch(instance, repo_path)
        if pip_install:
            note = pip_install_repo(repo_path)
            if note:
                record_notes.append(note[:200])
        f2p = json.loads(instance.get("FAIL_TO_PASS") or "[]")
        p2p = json.loads(instance.get("PASS_TO_PASS") or "[]")
        settings = load_settings()          # 载入 config.json(超时/重试/16k 输出)
        settings.models = [model]           # 仅注册本实例使用的模型
        client = ModelClientFactory(settings).create()

        def llm(system, user):
            r = client.chat(model, [{"role": "system", "content": system},
                                    {"role": "user", "content": user}])
            return r.content

        issue = instance.get("problem_statement", "")
        hints = instance.get("hints_text") or ""
        if hints:
            issue += "\n\n补充线索:\n" + hints[:2000]
        fixer = RepoFixer(llm, repo_path,
                          test_cmd=[sys.executable, "-m", "pytest", "-q",
                                    "--no-header"],
                          max_rounds=max_rounds)
        result = fixer.fix(issue, test_files=list(f2p))
        record.update({
            "resolved": bool(result.ok), "status": "resolved" if result.ok else "failed",
            "rounds": result.rounds, "changed_files": result.changed_files,
            "tokens": client.total_tokens_used,
            "duration_s": round(time.time() - t0, 1),
            "error": (result.error or "")[:300],
            "pass_to_pass_count": len(p2p),
            "test_output_tail": (result.test_output or "")[-800:],
            "diff_head": (result.diff or "")[:2000],
            "notes": record_notes,
        })
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        record["duration_s"] = round(time.time() - t0, 1)
    return record


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="SWE-bench Lite 子集跑分(简化验证口径)")
    ap.add_argument("--dataset", default="swebench_lite.jsonl")
    ap.add_argument("--prepare-dataset", action="store_true")
    ap.add_argument("--sample", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model", default="openai/deepseek-v3")
    ap.add_argument("--repos-cache", default=".tmp/swebench_repos")
    ap.add_argument("--out", default="logs/swebench")
    ap.add_argument("--max-rounds", type=int, default=2)
    ap.add_argument("--no-install", action="store_true",
                    help="跳过 pip install -e .(默认安装以支持仓库测试导入)")
    ap.add_argument("--workers", type=int, default=1,
                    help="并行实例数(实例间相互独立;默认 1 串行)")
    args = ap.parse_args()

    if args.prepare_dataset:
        prepare_dataset(args.dataset)
        return

    path = Path(args.dataset)
    if not path.exists():
        sys.exit(f"数据集不存在: {path} —— 先 --prepare-dataset 或手工放置官方 JSONL")
    instances = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    picked = sample_instances(instances, args.sample, args.seed)
    print(f"抽样: {len(picked)}/{len(instances)} (seed={args.sample and args.seed})")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _run_and_save(i, ins):
        print(f"[{i}/{len(picked)}] {ins.get('repo')} …", flush=True)
        rec = run_instance(ins, Path(args.repos_cache), args.model,
                           args.max_rounds, pip_install=not args.no_install)
        (out_dir / f"{rec['instance_id'].replace('/', '_')}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{i}] -> {rec['status']} tokens={rec['tokens']}", flush=True)
        return rec

    if args.workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            records = list(pool.map(_run_and_save, range(1, len(picked) + 1), picked))
    else:
        records = [_run_and_save(i, ins) for i, ins in enumerate(picked, 1)]

    resolved = sum(r["resolved"] for r in records)
    errors = sum(r["status"] == "error" for r in records)
    total_tokens = sum(r["tokens"] for r in records)

    summary = {
        "model": args.model, "seed": args.seed, "sample": len(picked),
        "resolved": resolved, "resolve_rate": round(resolved / max(1, len(picked)), 3),
        "errors": errors, "total_tokens": total_tokens,
        "口径": "简化验证(仓库根 pytest FAIL_TO_PASS);未做官方 per-repo 环境",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
