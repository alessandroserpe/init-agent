"""Evaluate init-agent context results against local benchmark cases."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "experiments" / "cases.json"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []
    skipped = []
    rebuilt_repos: set[Path] = set()
    for case in cases:
        repo = Path(case["repo"])
        if not repo.exists():
            skipped.append({"name": case["name"], "reason": f"missing repo: {repo}"})
            continue
        if args.rebuild_index and repo not in rebuilt_repos:
            _rebuild_index(repo)
            rebuilt_repos.add(repo)
        try:
            results.append(evaluate_case(case))
        except subprocess.CalledProcessError as exc:
            results.append(
                {
                    "name": case["name"],
                    "status": "error",
                    "elapsed_seconds": None,
                    "error": exc.stderr.strip() or str(exc),
                }
            )

    summary = summarize(results)
    strict_failures = strict_failures_for(summary, args) if args.strict else []
    report = {"summary": summary, "results": results, "skipped": skipped}
    if args.strict:
        report["strict"] = {
            "ok": not strict_failures,
            "failures": strict_failures,
            "min_top3_rate": args.min_top3_rate,
            "min_top5_rate": args.min_top5_rate,
            "max_noise": args.max_noise,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    if any(item.get("status") == "error" for item in results):
        return 1
    if strict_failures:
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate init-agent against local benchmark repositories.")
    parser.add_argument("--strict", action="store_true", help="Fail when summary metrics do not meet thresholds.")
    parser.add_argument("--rebuild-index", action="store_true", help="Run init/map/git before each case to avoid stale local indexes.")
    parser.add_argument("--min-top3-rate", type=float, default=0.85, help="Minimum top-3 hit rate for --strict.")
    parser.add_argument("--min-top5-rate", type=float, default=1.0, help="Minimum top-5 hit rate for --strict.")
    parser.add_argument("--max-noise", type=int, default=2, help="Maximum total noise hits for --strict.")
    return parser.parse_args(argv)


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "init_agent.cli", "run", case["query"], "--json"],
        cwd=case["repo"],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    elapsed = time.perf_counter() - started
    data = json.loads(proc.stdout)
    candidates = [item["path"] for item in data["context"]["candidate_files"]]
    expected = list(case.get("expected_files", []))
    noise_patterns = list(case.get("noise_patterns", []))
    expected_hits = [path for path in expected if path in candidates]
    noise_hits = [path for path in candidates if any(pattern in path for pattern in noise_patterns)]
    return {
        "name": case["name"],
        "status": "ok",
        "elapsed_seconds": round(elapsed, 3),
        "top1_hit": _top_hit(candidates, expected, 1),
        "top3_hit": _top_hit(candidates, expected, 3),
        "top5_hit": _top_hit(candidates, expected, 5),
        "expected_hits": expected_hits,
        "expected_hit_count": len(expected_hits),
        "expected_count": len(expected),
        "noise_hits": noise_hits,
        "noise_hit_count": len(noise_hits),
        "candidate_files": candidates,
    }


def _rebuild_index(repo: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    subprocess.run(
        [sys.executable, "-m", "init_agent.cli", "init"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "init_agent.cli", "map"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "init_agent.cli", "git"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_results = [item for item in results if item.get("status") == "ok"]
    total = len(ok_results)
    if total == 0:
        return {"cases": 0}
    top1_hits = sum(1 for item in ok_results if item["top1_hit"])
    top3_hits = sum(1 for item in ok_results if item["top3_hit"])
    top5_hits = sum(1 for item in ok_results if item["top5_hit"])
    noise_hits = sum(int(item["noise_hit_count"]) for item in ok_results)
    return {
        "cases": total,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top1_rate": round(top1_hits / total, 3),
        "top3_rate": round(top3_hits / total, 3),
        "top5_rate": round(top5_hits / total, 3),
        "noise_hits": noise_hits,
        "average_elapsed_seconds": round(sum(float(item["elapsed_seconds"]) for item in ok_results) / total, 3),
    }


def strict_failures_for(summary: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures = []
    if int(summary.get("cases", 0)) == 0:
        failures.append("no benchmark cases ran")
        return failures
    if float(summary.get("top3_rate", 0.0)) < args.min_top3_rate:
        failures.append(f"top3_rate {summary.get('top3_rate')} < {args.min_top3_rate}")
    if float(summary.get("top5_rate", 0.0)) < args.min_top5_rate:
        failures.append(f"top5_rate {summary.get('top5_rate')} < {args.min_top5_rate}")
    if int(summary.get("noise_hits", 0)) > args.max_noise:
        failures.append(f"noise_hits {summary.get('noise_hits')} > {args.max_noise}")
    return failures


def _top_hit(candidates: list[str], expected: list[str], limit: int) -> bool:
    return any(path in candidates[:limit] for path in expected)


if __name__ == "__main__":
    raise SystemExit(main())
